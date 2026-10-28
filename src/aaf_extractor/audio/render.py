"""Rebuild selected AAF tracks on the record timeline and stream them out.

A *plan* lists, for one output channel, which media samples land at which
output sample positions. Everything not covered by a segment is silence.
Rendering walks the programme in fixed-size blocks so memory use does not
depend on programme length.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable

import numpy as np

from ..aaf.model import AudioTrack
from ..media.reader import PCMReader
from ..media.resolver import ResolvedMedia
from ..timecode import round_half_up, units_to_samples

BLOCK_FRAMES = 48000 * 4


class PlanError(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class PlacedSegment:
    out_start: int
    length: int
    media: ResolvedMedia
    src_start: int
    description: str = ""

    @property
    def out_end(self) -> int:
        return self.out_start + self.length


@dataclass
class ChannelPlan:
    label: str
    segments: list[PlacedSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        lines = []
        for s in self.segments:
            ref = s.media.ref
            lines.append(
                f"out {s.out_start}..{s.out_end} ({s.length} samples) <- media "
                f"'{ref.mob_name}' [{ref.mob_id}] ch{ref.channel_index + 1} from sample {s.src_start} "
                f"({s.media.location})")
        return lines


def total_samples(duration_seconds: Fraction, sample_rate: int) -> int:
    return round_half_up(Fraction(duration_seconds) * sample_rate)


def plan_track(track: AudioTrack, resolved: dict[str, ResolvedMedia], sample_rate: int,
               programme_samples: int) -> ChannelPlan:
    """Convert a track's segments into output sample positions.

    Segment boundaries are each rounded from exact rational positions, so
    adjacent clips always meet without gaps or overlaps.
    """
    if track.errors:
        raise PlanError("; ".join(track.errors))
    plan = ChannelPlan(track.label)
    for seg in track.segments:
        if seg.kind != "audio":
            continue
        start = units_to_samples(seg.record_start, track.edit_rate, sample_rate)
        end = units_to_samples(seg.record_start + seg.length, track.edit_rate, sample_rate)
        if end <= start:
            continue
        media = resolved.get(seg.media.mob_id)
        if media is None:
            raise PlanError(f"media for {seg.description} was not resolved")
        if media.fmt.sample_rate != sample_rate:
            raise PlanError(f"media '{seg.media.mob_name}' is {media.fmt.sample_rate} Hz; sample-rate "
                            f"conversion to {sample_rate} Hz is not supported in this version")
        src = round_half_up(seg.source_start * media.fmt.sample_rate)
        length = end - start
        if src < 0:
            raise PlanError(f"{seg.description}: negative source offset")
        if src + length > media.frames:
            short = src + length - media.frames
            raise PlanError(f"{seg.description}: clip needs {short} samples beyond the end of media "
                            f"'{seg.media.mob_name}' ({media.frames} samples available)")
        if end > programme_samples:
            plan.warnings.append(f"{seg.description}: {end - programme_samples} samples past the "
                                 "sequence end were trimmed")
            length = programme_samples - start
            if length <= 0:
                continue
        plan.segments.append(PlacedSegment(start, length, media, src, seg.description))
    plan.segments.sort(key=lambda s: s.out_start)
    for a, b in zip(plan.segments, plan.segments[1:]):
        if b.out_start < a.out_end:
            raise PlanError(f"clips overlap at sample {b.out_start}")
    return plan


def pack_int24_interleaved(channels: list[np.ndarray]) -> bytes:
    frames = len(channels[0])
    stacked = np.empty((frames, len(channels)), dtype="<i4")
    for i, ch in enumerate(channels):
        stacked[:, i] = ch
    return stacked.view(np.uint8).reshape(frames, len(channels), 4)[:, :, :3].tobytes()


def render(plans: list[ChannelPlan], frames: int, sink: Callable[[bytes], None],
           open_reader: Callable[[ResolvedMedia], PCMReader],
           progress: Callable[[int, int], None] | None = None,
           cancel: threading.Event | None = None, block: int = BLOCK_FRAMES) -> int:
    """Stream ``frames`` interleaved 24-bit frames to ``sink``. Returns frames written."""
    readers: dict[int, PCMReader] = {}
    written = 0
    try:
        pos = 0
        while pos < frames:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            n = min(block, frames - pos)
            outs = []
            for plan in plans:
                buf = np.zeros(n, dtype=np.int32)
                for seg in plan.segments:
                    a = max(seg.out_start, pos)
                    b = min(seg.out_end, pos + n)
                    if a >= b:
                        continue
                    key = id(seg.media)
                    reader = readers.get(key)
                    if reader is None:
                        reader = readers[key] = open_reader(seg.media)
                    buf[a - pos:b - pos] = reader.read(seg.src_start + (a - seg.out_start), b - a)
                outs.append(buf)
            sink(pack_int24_interleaved(outs))
            pos += n
            written += n
            if progress:
                progress(pos, frames)
    finally:
        for r in readers.values():
            r.close()
    return written
