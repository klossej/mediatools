"""Sequential batch export."""

from __future__ import annotations

import csv
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import aaf2

from .. import __version__
from ..audio.render import Cancelled, render
from ..bwf.reader import verify_bwf
from ..bwf.writer import BextInfo, BWFWriter
from ..media.resolver import MediaIndex, open_reader
from ..timecode import format_duration
from .models import (OUTPUT_BITS, OUTPUT_CHANNELS, OUTPUT_SAMPLE_RATE, BatchSettings, Job, JobState,
                     OverwritePolicy)
from .naming import numbered_alternative
from .preflight import PreflightIssue, Prepared, diagnostics_for, preflight, prepare

log = logging.getLogger(__name__)

RESULT_COMPLETED = "Completed"
RESULT_FAILED = "Failed"
RESULT_SKIPPED = "Skipped"
RESULT_CANCELLED = "Cancelled"


@dataclass
class JobResult:
    job: Job
    result: str
    message: str = ""
    seconds: float = 0.0


@dataclass
class BatchResult:
    results: list[JobResult] = field(default_factory=list)
    elapsed: float = 0.0
    output_dir: str = ""
    report_path: str | None = None
    cancelled: bool = False

    def count(self, result: str) -> int:
        return sum(1 for r in self.results if r.result == result)

    def summary(self) -> str:
        return (f"{len(self.results)} files: {self.count(RESULT_COMPLETED)} exported, "
                f"{self.count(RESULT_FAILED)} failed, {self.count(RESULT_SKIPPED)} skipped"
                + (f", {self.count(RESULT_CANCELLED)} cancelled" if self.count(RESULT_CANCELLED) else "")
                + f" in {format_duration(self.elapsed)}")


ProgressFn = Callable[[Job, int, int], None]


def _bext_for(job: Job, prep: Prepared) -> BextInfo:
    tc = prep.timecode
    left = prep.left.channel_label(prep.left_channel)
    right = prep.right.channel_label(prep.right_channel)
    desc = (f"{Path(job.path).name} | {prep.sequence.name} | L={left} R={right} | "
            f"TC {tc.label} {tc.rate.label}")
    formats = sorted({(p.media.fmt.bits, p.media.fmt.sample_rate) for plan in prep.plans for p in plan.segments})
    history = [f"A=PCM,F={rate},W={bits},M=mono,T=AAF essence" for bits, rate in formats]
    history.append(f"A=PCM,F={OUTPUT_SAMPLE_RATE},W={OUTPUT_BITS},M=stereo,T=AAF Audio Extractor {__version__}")
    return BextInfo(description=desc[:256], originator="AAF Audio Extractor",
                    time_reference=prep.time_reference, coding_history="\r\n".join(history))


def _remove(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("could not remove %s: %s", path, exc)


def export_job(job: Job, settings: BatchSettings, index: MediaIndex, claimed: set[str],
               cancel: threading.Event | None = None, progress: ProgressFn | None = None) -> JobResult:
    started = time.monotonic()
    try:
        prep = prepare(job, settings, index)
    except PreflightIssue as issue:
        job.state = issue.state
        job.messages = [str(issue)]
        return JobResult(job, RESULT_FAILED, str(issue))
    job.diagnostics = diagnostics_for(job, prep)

    dest = Path(job.output_path)
    if dest.exists():
        if settings.overwrite == OverwritePolicy.SKIP:
            job.messages = [f"{dest.name} already exists (skipped)"]
            return JobResult(job, RESULT_SKIPPED, job.messages[0])
        if settings.overwrite == OverwritePolicy.RENAME:
            dest = numbered_alternative(dest, claimed)
    claimed.add(str(dest).lower())
    temp = dest.with_name(dest.name + ".partial")

    job.state = JobState.EXPORTING
    job.messages = []
    log.info("export start file=%s sequence=%r tc=%s edit_rate=%s left=%s right=%s output=%s "
             "time_reference=%d samples=%d", job.filename, prep.sequence.name, prep.timecode.display,
             prep.sequence.edit_rate, job.left_label, job.right_label, dest.name,
             prep.time_reference, prep.frames)
    for line in job.diagnostics:
        log.debug("  %s", line)

    writer = None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        needs_aaf = any(seg.media.location == "embedded" for p in prep.plans for seg in p.segments)
        aaf_file = aaf2.open(job.path, "r") if needs_aaf else None
        try:
            writer = BWFWriter(temp, OUTPUT_SAMPLE_RATE, OUTPUT_CHANNELS, OUTPUT_BITS, _bext_for(job, prep))
            written = render(prep.plans, prep.frames, writer.write,
                             lambda res: open_reader(res, aaf_file),
                             progress=(lambda done, total: progress(job, done, total)) if progress else None,
                             cancel=cancel)
            writer.close()
        finally:
            if aaf_file is not None:
                aaf_file.close()
        problems = verify_bwf(temp, sample_rate=OUTPUT_SAMPLE_RATE, channels=OUTPUT_CHANNELS,
                              bits=OUTPUT_BITS, frames=prep.frames, time_reference=prep.time_reference)
        if written != prep.frames:
            problems.append(f"rendered {written} samples, expected {prep.frames}")
        if problems:
            raise RuntimeError("verification failed: " + "; ".join(problems))
        os.replace(temp, dest)
    except Cancelled:
        if writer:
            writer.abort()
        _remove(temp)
        claimed.discard(str(dest).lower())
        job.state = JobState.READY
        job.messages = ["export cancelled; incomplete file removed"]
        log.info("export cancelled file=%s", job.filename)
        return JobResult(job, RESULT_CANCELLED, job.messages[0], time.monotonic() - started)
    except Exception as exc:
        if writer:
            writer.abort()
        _remove(temp)
        claimed.discard(str(dest).lower())
        job.state = JobState.FAILED
        job.messages = [str(exc)]
        log.exception("export failed file=%s", job.filename)
        return JobResult(job, RESULT_FAILED, str(exc), time.monotonic() - started)

    job.state = JobState.COMPLETED
    job.exported_path = str(dest)
    job.exported_frames = prep.frames
    job.time_reference = prep.time_reference
    job.messages = [f"exported {dest.name}"]
    log.info("export done file=%s output=%s samples=%d time_reference=%d verified=yes",
             job.filename, dest, prep.frames, prep.time_reference)
    return JobResult(job, RESULT_COMPLETED, "", time.monotonic() - started)


def run_batch(jobs: list[Job], settings: BatchSettings, cancel: threading.Event | None = None,
              on_job_start: Callable[[Job, int, int], None] | None = None,
              on_progress: ProgressFn | None = None,
              on_job_done: Callable[[JobResult], None] | None = None,
              all_jobs: list[Job] | None = None) -> BatchResult:
    """Export every Ready job in ``jobs``. ``all_jobs`` (the whole queue) is used for collision checks."""
    started = time.monotonic()
    index = MediaIndex(settings.media_folders)
    preflight(all_jobs or jobs, settings, index)
    result = BatchResult(output_dir=settings.output_dir)
    claimed = {j.output_path.lower() for j in (all_jobs or jobs) if j.output_path}
    claimed |= {j.exported_path.lower() for j in (all_jobs or jobs) if j.exported_path}
    todo = [j for j in jobs if j.state == JobState.READY]
    log.info("batch start: %d files queued, %d ready", len(jobs), len(todo))

    for job in jobs:
        if job.state != JobState.READY:
            if job.state == JobState.COMPLETED:
                msg = "already exported"
            else:
                msg = f"{job.state.value}: {job.messages[0]}" if job.messages else job.state.value
            result.results.append(JobResult(job, RESULT_SKIPPED, msg))
    for i, job in enumerate(todo):
        if cancel is not None and cancel.is_set():
            result.results.append(JobResult(job, RESULT_CANCELLED, "not started"))
            continue
        if on_job_start:
            on_job_start(job, i, len(todo))
        if job.output_path:
            claimed.discard(job.output_path.lower())
        jr = export_job(job, settings, index, claimed, cancel, on_progress)
        result.results.append(jr)
        if jr.result == RESULT_CANCELLED:
            result.cancelled = True
        if on_job_done:
            on_job_done(jr)

    result.cancelled = result.cancelled or bool(cancel is not None and cancel.is_set())
    result.elapsed = time.monotonic() - started
    order = {id(j): n for n, j in enumerate(jobs)}
    result.results.sort(key=lambda r: order.get(id(r.job), 0))
    if settings.output_dir:
        try:
            result.report_path = write_report(result, settings)
        except OSError as exc:
            log.error("could not write batch report: %s", exc)
    log.info("batch done: %s", result.summary())
    return result


REPORT_COLUMNS = [
    "Input AAF", "Sequence", "Track selection", "Left track", "Right track", "Record timecode", "Timecode rate",
    "Timecode source", "Exported file", "Duration", "Duration (samples)", "Sample rate", "Bit depth",
    "BWF TimeReference", "Result", "Message", "Warnings",
]


def report_rows(result: BatchResult) -> list[dict]:
    rows = []
    for r in result.results:
        job = r.job
        seq = job.sequence
        tc = job.timecode
        rows.append({
            "Input AAF": job.filename,
            "Sequence": seq.name if seq else "",
            "Track selection": job.selection,
            "Left track": job.left_label,
            "Right track": job.right_label,
            "Record timecode": tc.label if tc else "",
            "Timecode rate": tc.rate.label if tc else "",
            "Timecode source": ("manual override" if tc.manual else tc.source) if tc else "",
            "Exported file": Path(job.exported_path).name if job.exported_path and r.result == RESULT_COMPLETED else "",
            "Duration": seq.duration_label if seq else "",
            "Duration (samples)": job.exported_frames if r.result == RESULT_COMPLETED else "",
            "Sample rate": OUTPUT_SAMPLE_RATE if r.result == RESULT_COMPLETED else "",
            "Bit depth": OUTPUT_BITS if r.result == RESULT_COMPLETED else "",
            "BWF TimeReference": job.time_reference if job.time_reference is not None else "",
            "Result": r.result,
            "Message": r.message,
            "Warnings": " | ".join(job.warnings),
        })
    return rows


def write_report(result: BatchResult, settings: BatchSettings) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(settings.output_dir) / f"AAF_Export_Report_{stamp}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel opens non-ASCII names correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(report_rows(result))
    return str(path)
