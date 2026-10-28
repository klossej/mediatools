"""Automatic detection of the premixed stereo mix track.

A Media Composer edit can contain several stereo tracks (music, effects, the
delivered mix). The mix is recognised as a *usable* stereo track whose audio
spans (nearly) the whole sequence. If several qualify, a "MIX" token in the
clip or track names breaks the tie. Anything still ambiguous is reported for
the operator to decide; nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from ..aaf.model import AudioTrack, SequenceInfo

MIN_COVERAGE = Fraction(9, 10)
_MIX_TOKEN = re.compile(r"(?i)(?:^|[^a-z])mix(?:[^a-z]|$)")


class DetectionError(Exception):
    pass


@dataclass
class Detection:
    track: AudioTrack
    coverage: Fraction
    named_mix: bool
    note: str


def coverage(track: AudioTrack) -> Fraction:
    """Fraction of the track length that carries audio on every channel."""
    if not track.length:
        return Fraction(0)
    per_channel = [0] * track.channels
    for seg in track.segments:
        if seg.kind == "audio":
            per_channel[seg.channel] += seg.length
    return Fraction(min(per_channel), track.length)


def _named_mix(track: AudioTrack) -> bool:
    if _MIX_TOKEN.search(track.name or ""):
        return True
    return any(_MIX_TOKEN.search(seg.media.mob_name or "") or _MIX_TOKEN.search(seg.description)
               for seg in track.segments if seg.media is not None)


def _describe(track: AudioTrack, cov: Fraction) -> str:
    return f"{track.label} ({float(cov):.0%})"


def detect_mix_track(seq: SequenceInfo) -> Detection:
    """Return the single stereo mix track of ``seq`` or raise DetectionError."""
    sequence_length = seq.duration
    usable = []
    for t in seq.tracks:
        if t.channels != 2 or t.errors:
            continue
        # Relative to the whole sequence, not just the track's own length.
        cov = coverage(t) * (t.duration / sequence_length) if sequence_length else Fraction(0)
        if cov > 0:
            usable.append((t, min(cov, Fraction(1))))
    full = [(t, c) for t, c in usable if c >= MIN_COVERAGE]

    if not full:
        parts = []
        if usable:
            parts.append("partial stereo tracks: " + ", ".join(_describe(t, c) for t, c in usable))
        broken = [t for t in seq.tracks if t.channels == 2 and t.errors]
        if broken:
            parts.append("unsupported stereo tracks: " + "; ".join(f"{t.label}: {t.errors[0]}" for t in broken))
        detail = f" ({'; '.join(parts)})" if parts else ""
        raise DetectionError(f"no full-length stereo mix track found{detail}")

    chosen = full
    if len(full) > 1:
        chosen = [(t, c) for t, c in full if _named_mix(t)]
        if len(chosen) != 1:
            raise DetectionError("several full-length stereo tracks could be the mix: "
                                 + ", ".join(_describe(t, c) for t, c in full) + "; choose the tracks manually")
    track, cov = chosen[0]
    named = _named_mix(track)
    why = f"stereo, audio over {float(cov):.1%} of the sequence"
    if len(full) > 1:
        why += f", only one named MIX among {len(full)} full-length stereo tracks"
    return Detection(track, cov, named, f"mix track auto-detected: {track.label} ({why})")
