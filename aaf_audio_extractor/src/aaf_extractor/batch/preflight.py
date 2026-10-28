"""Track matching and preflight checks.

``prepare`` performs every check that can be made without rendering audio and
returns the render plan. Preflight runs it for display; export runs it again
immediately before rendering so nothing stale is used.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..aaf.model import AudioTrack, RecordTimecode, SequenceInfo
from ..audio.render import ChannelPlan, PlanError, plan_track, total_samples
from ..media.resolver import MediaError, MediaIndex, ResolvedMedia, resolve
from ..timecode import timecode_to_time_reference
from .models import (OUTPUT_SAMPLE_RATE, BatchSettings, Job, JobState, MatchMethod,
                     OverwritePolicy, TrackSelector)
from .detect import DetectionError, detect_mix_track
from .naming import output_name

SELECTION_OVERRIDE = "per-file override"
SELECTION_AUTO = "auto-detected"
SELECTION_MAPPING = "batch mapping"

log = logging.getLogger(__name__)


class PreflightIssue(Exception):
    def __init__(self, state: JobState, message: str):
        super().__init__(message)
        self.state = state


@dataclass
class Prepared:
    sequence: SequenceInfo
    left: AudioTrack
    right: AudioTrack
    left_channel: int
    right_channel: int
    selection: str
    selection_note: str | None
    plans: list[ChannelPlan]
    frames: int
    timecode: RecordTimecode
    time_reference: int


def match_track(seq: SequenceInfo, selector: TrackSelector) -> tuple[AudioTrack, int]:
    """Find exactly one (track, channel) for ``selector`` or raise PreflightIssue."""
    if selector.method == MatchMethod.NUMBER:
        hits = [t for t in seq.tracks if t.track_number == int(selector.value)]
    else:
        wanted = str(selector.value).strip().casefold()
        hits = [t for t in seq.tracks if t.name.strip().casefold() == wanted]
    if not hits:
        raise PreflightIssue(JobState.NEEDS_ATTENTION, f"track {selector.label} not found")
    if len(hits) > 1:
        raise PreflightIssue(JobState.NEEDS_ATTENTION,
                             f"track {selector.label} is ambiguous ({len(hits)} tracks match)")
    track = hits[0]
    if selector.channel is None:
        if track.channels > 1:
            raise PreflightIssue(JobState.NEEDS_ATTENTION,
                                 f"track {track.label} is {track.channels}-channel in this file; choose a channel")
        return track, 0
    if selector.channel >= track.channels:
        what = "mono" if track.channels == 1 else f"{track.channels}-channel"
        raise PreflightIssue(JobState.NEEDS_ATTENTION,
                             f"{selector.label} not found: {track.label} is {what} in this file")
    return track, selector.channel


def _detect(seq: SequenceInfo):
    try:
        return detect_mix_track(seq)
    except DetectionError as exc:
        raise PreflightIssue(JobState.NEEDS_ATTENTION, f"auto-detect: {exc}")


def _pick(job: Job, seq: SequenceInfo, side: str, settings: BatchSettings,
          detection=None) -> tuple[AudioTrack, int]:
    ref = job.override_left if side == "left" else job.override_right
    if ref is not None:
        track = seq.track_by_slot(ref.slot_id)
        if track is None or ref.channel >= track.channels:
            raise PreflightIssue(JobState.NEEDS_ATTENTION, f"override {side} track no longer exists")
        return track, ref.channel
    if settings.auto_mix:
        detection = detection or _detect(seq)
        return detection.track, 0 if side == "left" else 1
    selector = settings.left if side == "left" else settings.right
    if selector is None:
        raise PreflightIssue(JobState.NEEDS_ATTENTION, f"no {side} track selected")
    return match_track(seq, selector)


def _resolve_media(job: Job, tracks: list[AudioTrack], index: MediaIndex) -> dict[str, ResolvedMedia]:
    resolved: dict[str, ResolvedMedia] = {}
    for track in tracks:
        for ref in track.media_refs():
            if ref.mob_id in resolved:
                continue
            try:
                res = resolve(ref, job.path, index)
            except MediaError as exc:
                state = JobState.NEEDS_ATTENTION if exc.code in ("missing", "ambiguous") else JobState.UNSUPPORTED
                raise PreflightIssue(state, f"{track.label}: {exc}")
            if res.fmt.bits not in (16, 24):
                raise PreflightIssue(JobState.UNSUPPORTED,
                                     f"{track.label}: {res.fmt.bits}-bit media is not supported (16/24-bit PCM only)")
            resolved[ref.mob_id] = res
    return resolved


def prepare(job: Job, settings: BatchSettings, index: MediaIndex) -> Prepared:
    insp = job.inspection
    if insp is None:
        raise PreflightIssue(JobState.PENDING, "not inspected yet")
    if insp.error:
        raise PreflightIssue(JobState.UNSUPPORTED, insp.error)
    seq = job.sequence
    if seq is None:
        raise PreflightIssue(JobState.NEEDS_ATTENTION,
                             f"{len(insp.sequences)} sequences found; choose one")
    tc = job.timecode
    if tc is None:
        raise PreflightIssue(JobState.NEEDS_ATTENTION,
                             f"record timecode unavailable ({seq.timecode_problem}); set it manually")
    detection = None
    if settings.auto_mix and (job.override_left is None or job.override_right is None):
        detection = _detect(seq)
    left, left_ch = _pick(job, seq, "left", settings, detection)
    right, right_ch = _pick(job, seq, "right", settings, detection)
    if job.has_override:
        selection, note = SELECTION_OVERRIDE, None
    elif detection is not None:
        selection, note = SELECTION_AUTO, detection.note
    else:
        selection, note = SELECTION_MAPPING, None
    for side, track in (("left", left), ("right", right)):
        if track.errors:
            raise PreflightIssue(JobState.UNSUPPORTED, f"{side} track {track.label}: {track.errors[0]}")
    resolved = _resolve_media(job, [left, right], index)
    frames = total_samples(seq.duration, OUTPUT_SAMPLE_RATE)
    if frames <= 0:
        raise PreflightIssue(JobState.UNSUPPORTED, "sequence has zero duration")
    plans = []
    for side, track, ch in (("left", left, left_ch), ("right", right, right_ch)):
        try:
            plans.append(plan_track(track, resolved, OUTPUT_SAMPLE_RATE, frames, ch))
        except PlanError as exc:
            raise PreflightIssue(JobState.UNSUPPORTED, f"{side} track {track.channel_label(ch)}: {exc}")
    if not any(p.segments for p in plans):
        raise PreflightIssue(JobState.NEEDS_ATTENTION, "both selected tracks are empty (silence only)")
    tref = timecode_to_time_reference(tc.start_frames, tc.rate, OUTPUT_SAMPLE_RATE)
    return Prepared(seq, left, right, left_ch, right_ch, selection, note, plans, frames, tc, tref)


def diagnostics_for(job: Job, prep: Prepared) -> list[str]:
    seq = prep.sequence
    lines = [
        f"AAF: {job.path}",
        f"Sequence: '{seq.name}' [{seq.mob_id}]",
        f"Sequence edit rate: {seq.edit_rate}  duration: {seq.duration_label} ({prep.frames} samples @ {OUTPUT_SAMPLE_RATE})",
        f"Record start: {prep.timecode.display} (frame {prep.timecode.start_frames}) from {prep.timecode.source}",
        f"BWF TimeReference: {prep.time_reference}",
        f"Track selection: {prep.selection}" + (f" - {prep.selection_note}" if prep.selection_note else ""),
    ]
    for side, track, ch, plan in (("Left", prep.left, prep.left_channel, prep.plans[0]),
                                  ("Right", prep.right, prep.right_channel, prep.plans[1])):
        lines.append(f"{side}: {track.channel_label(ch)} (slot {track.slot_id}, channel {ch + 1} of "
                     f"{track.channels}, edit rate {track.edit_rate}, {len(track.segments)} components)")
        for seg in track.segments:
            if seg.channel != ch:
                continue
            media = f" media={seg.media.mob_id} src_start={seg.source_start}s" if seg.media else ""
            lines.append(f"    record {seg.record_start}+{seg.length} units: {seg.kind} {seg.description}{media}")
        lines.extend("    " + l for l in plan.describe())
        lines.extend(f"    warning: {w}" for w in track.warnings + plan.warnings)
    return lines


def preflight(jobs: list[Job], settings: BatchSettings, index: MediaIndex | None = None) -> None:
    """Check every job that is not completed and set its state and messages."""
    index = index or MediaIndex(settings.media_folders)
    claimed: dict[str, list[Job]] = {}

    for job in jobs:
        if job.state in (JobState.COMPLETED, JobState.EXPORTING):
            if job.exported_path:
                claimed.setdefault(job.exported_path.lower(), []).append(job)
            continue
        if job.state == JobState.PENDING and job.inspection is None:
            continue
        job.messages, job.warnings, job.diagnostics = [], [], []
        job.left_track = job.right_track = None
        job.left_channel = job.right_channel = 0
        job.selection = ""
        job.output_path = None
        try:
            prep = prepare(job, settings, index)
        except PreflightIssue as issue:
            job.state = issue.state
            job.messages.append(str(issue))
            seq = job.sequence
            if seq is not None and issue.state != JobState.PENDING:
                for side in ("left", "right"):
                    try:
                        track, ch = _pick(job, seq, side, settings)
                        setattr(job, f"{side}_track", track)
                        setattr(job, f"{side}_channel", ch)
                    except PreflightIssue:
                        pass
            log.info("preflight %s: %s - %s", job.filename, issue.state.value, issue)
        else:
            job.left_track, job.right_track = prep.left, prep.right
            job.left_channel, job.right_channel = prep.left_channel, prep.right_channel
            job.selection = prep.selection
            if prep.selection_note:
                job.warnings.append(prep.selection_note)
            job.time_reference = prep.time_reference
            job.diagnostics = diagnostics_for(job, prep)
            job.warnings.extend(prep.sequence.warnings)
            job.warnings.extend(w for t in {id(prep.left): prep.left, id(prep.right): prep.right}.values()
                                for w in t.warnings)
            job.warnings.extend(w for p in prep.plans for w in p.warnings)
            if prep.left is prep.right and prep.left_channel == prep.right_channel:
                job.warnings.append("the same track is used for both channels")
            if prep.timecode.manual:
                job.warnings.append(f"record timecode set manually: {prep.timecode.display}")
            job.state = JobState.READY
        if not settings.output_dir:
            if job.state == JobState.READY:
                job.state = JobState.NEEDS_ATTENTION
                job.messages.append("choose an output folder")
            continue
        out = str(Path(settings.output_dir) / output_name(job.path, settings.suffix))
        job.output_path = out
        claimed.setdefault(out.lower(), []).append(job)

    for _key, owners in claimed.items():
        if len(owners) < 2:
            continue
        for job in owners:
            if job.state in (JobState.COMPLETED, JobState.EXPORTING):
                continue
            others = ", ".join(o.filename for o in owners if o is not job)
            msg = f"output name {Path(job.output_path).name} collides with {others}"
            if job.state == JobState.READY:
                job.state = JobState.NEEDS_ATTENTION
                job.messages.insert(0, msg)
            else:
                job.messages.append(msg)

    for job in jobs:
        if job.state == JobState.READY and job.output_path and Path(job.output_path).exists():
            policy = settings.overwrite
            action = {OverwritePolicy.SKIP: "will be skipped", OverwritePolicy.OVERWRITE: "will be overwritten",
                      OverwritePolicy.RENAME: "a numbered name will be used"}[policy]
            job.warnings.append(f"{Path(job.output_path).name} already exists; {action}")
