"""Exact timecode arithmetic.

All timing uses ``fractions.Fraction`` so that no floating point error can
accumulate. Frame counts follow the AAF convention: a Timecode component's
``Start`` is the number of *real* frames since midnight, counted at the
timecode's actual rate (e.g. 30000/1001 for 29.97). Drop-frame only changes how
that frame count is *labelled*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

FRAMES_PER_DAY_NOMINAL = 24 * 60 * 60

# Nominal fps values whose drop-frame labelling we implement (SMPTE 12M).
DROP_FRAME_FPS = (30, 60)


class TimecodeError(ValueError):
    pass


@dataclass(frozen=True)
class TimecodeRate:
    """Frame rate of a timecode track.

    ``fps`` is the integer nominal frame count per labelled second (24, 25, 30...),
    ``rate`` the real number of frames per second (e.g. 30000/1001).
    """

    fps: int
    drop: bool
    rate: Fraction

    def __post_init__(self):
        if self.fps <= 0:
            raise TimecodeError(f"invalid timecode fps {self.fps}")
        if self.drop and self.fps not in DROP_FRAME_FPS:
            raise TimecodeError(f"drop-frame is not defined for {self.fps} fps")

    @classmethod
    def from_nominal(cls, fps: int, drop: bool = False, pulldown: bool | None = None) -> "TimecodeRate":
        """Build a rate from a nominal fps.

        ``pulldown`` selects the 1000/1001 rate. It defaults to True for drop-frame
        (drop-frame only exists for 29.97/59.94) and False otherwise.
        """
        if pulldown is None:
            pulldown = drop
        rate = Fraction(fps * 1000, 1001) if pulldown else Fraction(fps)
        return cls(fps, drop, rate)

    @property
    def label(self) -> str:
        if self.rate.denominator == 1:
            text = f"{self.rate.numerator}"
        else:
            text = f"{float(self.rate):.3f}".rstrip("0").rstrip(".")
        return f"{text} {'DF' if self.drop else 'NDF'}"


def _drop_frames_per_minute(fps: int) -> int:
    # 2 frames per minute at 29.97, 4 at 59.94.
    return fps // 15


def frames_to_label(frames: int, rate: TimecodeRate) -> str:
    """Format a real-frame count as HH:MM:SS:FF (``;`` before frames for DF)."""
    if frames < 0:
        raise TimecodeError("negative frame count")
    fps = rate.fps
    if rate.drop:
        drop = _drop_frames_per_minute(fps)
        frames_per_10min = fps * 600 - drop * 9
        frames_per_min = fps * 60 - drop
        tens, rem = divmod(frames, frames_per_10min)
        if rem > drop:
            frames = frames + drop * 9 * tens + drop * ((rem - drop) // frames_per_min)
        else:
            frames = frames + drop * 9 * tens
    ff = frames % fps
    total_seconds = frames // fps
    ss = total_seconds % 60
    mm = (total_seconds // 60) % 60
    hh = total_seconds // 3600
    sep = ";" if rate.drop else ":"
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


_TC_RE = re.compile(r"^\s*(\d{1,2})[:;.](\d{2})[:;.](\d{2})[:;.,](\d{2,3})\s*$")


def label_to_frames(label: str, rate: TimecodeRate) -> int:
    """Parse HH:MM:SS:FF (or ;FF) into a real-frame count."""
    m = _TC_RE.match(label)
    if not m:
        raise TimecodeError(f"not a timecode: {label!r}")
    hh, mm, ss, ff = (int(g) for g in m.groups())
    fps = rate.fps
    if mm > 59 or ss > 59 or ff >= fps or hh > 23:
        raise TimecodeError(f"timecode out of range for {rate.label}: {label!r}")
    frames = ((hh * 60 + mm) * 60 + ss) * fps + ff
    if rate.drop:
        drop = _drop_frames_per_minute(fps)
        if ss == 0 and ff < drop and mm % 10 != 0:
            raise TimecodeError(f"{label!r} does not exist in drop-frame timecode")
        total_minutes = hh * 60 + mm
        frames -= drop * (total_minutes - total_minutes // 10)
    return frames


def frames_to_seconds(frames: int, rate: TimecodeRate) -> Fraction:
    return Fraction(frames) / rate.rate


def round_half_up(value: Fraction) -> int:
    """Round a non-negative or negative Fraction to the nearest integer, halves away from zero."""
    if value >= 0:
        return int((value + Fraction(1, 2)).__floor__())
    return -round_half_up(-value)


def units_to_samples(units: int | Fraction, edit_rate: Fraction, sample_rate: int) -> int:
    """Convert a position expressed in edit units to an integer sample index."""
    return round_half_up(Fraction(units) * sample_rate / Fraction(edit_rate))


def timecode_to_time_reference(frames: int, rate: TimecodeRate, sample_rate: int) -> int:
    """BWF TimeReference: samples since midnight at ``sample_rate``."""
    return round_half_up(Fraction(frames) * sample_rate / rate.rate)


def samples_to_label(samples: int, sample_rate: int, rate: TimecodeRate) -> str:
    """Label of the frame containing ``samples`` (used for durations and readback display)."""
    frames = (Fraction(samples) * rate.rate / sample_rate).__floor__()
    return frames_to_label(int(frames), rate)


def format_duration(seconds: Fraction | float) -> str:
    total = float(seconds)
    hh = int(total // 3600)
    mm = int((total % 3600) // 60)
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:06.3f}"
