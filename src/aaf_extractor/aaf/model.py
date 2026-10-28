"""Plain data describing what was found in an AAF file.

These objects are produced by :mod:`aaf_extractor.aaf.inspector` and are safe to
pass between threads: they hold no reference to the open AAF file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ..timecode import TimecodeRate, format_duration, frames_to_label


@dataclass
class EssenceFormat:
    """Layout of PCM sample data inside an essence stream or media file."""

    sample_rate: int
    channels: int
    bits: int
    big_endian: bool = False
    data_offset: int = 0      # byte offset of the first sample in the stream/file
    data_size: int = 0        # bytes of sample data available

    @property
    def block_align(self) -> int:
        return self.channels * ((self.bits + 7) // 8)

    @property
    def frames(self) -> int:
        return self.data_size // self.block_align if self.block_align else 0

    def describe(self) -> str:
        ch = "mono" if self.channels == 1 else f"{self.channels} ch"
        return f"{self.sample_rate / 1000:g} kHz / {self.bits}-bit / {ch}"


@dataclass
class MediaRef:
    """A file SourceMob that ultimately provides the samples of a clip."""

    mob_id: str
    mob_name: str
    descriptor: str               # PCMDescriptor, WAVEDescriptor, AIFCDescriptor, ...
    channel_index: int            # 0-based channel inside the media
    declared: EssenceFormat | None  # format declared by the AAF descriptor
    length_samples: int | None    # descriptor Length (in sample frames), if present
    embedded: bool
    embedded_format: EssenceFormat | None = None  # format found in the embedded stream
    locators: list[str] = field(default_factory=list)
    problem: str | None = None    # set when the descriptor itself is unusable

    @property
    def short_id(self) -> str:
        return self.mob_id.split(".")[-1][-12:] if self.mob_id else "?"


@dataclass
class TrackSegment:
    """One piece of a composition track, in the track's edit units."""

    record_start: int             # position on the record timeline (edit units)
    length: int                   # edit units
    kind: str                     # "audio" or "silence"
    media: MediaRef | None = None
    source_start: Fraction = Fraction(0)  # seconds into the media
    description: str = ""
    channel: int = 0              # channel of a multichannel (e.g. stereo) track
    combined: bool = False        # came from a channel combiner input


@dataclass
class AudioTrack:
    slot_id: int
    track_number: int | None      # PhysicalTrackNumber (A1 -> 1)
    name: str
    edit_rate: Fraction
    length: int                   # edit units
    channels: int = 1             # 2 for an Avid stereo track (Audio Channel Combiner)
    segments: list[TrackSegment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)    # unsupported structures
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.track_number is not None:
            base = f"A{self.track_number}"
            if self.name and self.name != base:
                return f"{base} — {self.name}"
            return base
        return self.name or f"Slot {self.slot_id}"

    @property
    def duration(self) -> Fraction:
        return Fraction(self.length) / self.edit_rate

    def channel_label(self, channel: int) -> str:
        """``A31`` for a mono track, ``A31 ch1`` for channel 1 of a multichannel track."""
        base = f"A{self.track_number}" if self.track_number is not None else (self.name or f"Slot {self.slot_id}")
        return f"{base} ch{channel + 1}" if self.channels > 1 else base

    @property
    def supported(self) -> bool:
        return not self.errors

    def media_refs(self) -> list[MediaRef]:
        seen: dict[str, MediaRef] = {}
        for seg in self.segments:
            if seg.media is not None:
                seen.setdefault(seg.media.mob_id, seg.media)
        return list(seen.values())

    def format_summary(self) -> str:
        formats = set()
        for ref in self.media_refs():
            fmt = ref.embedded_format or ref.declared
            if fmt:
                formats.add(f"{fmt.sample_rate / 1000:g} kHz / {fmt.bits}-bit")
        if not formats:
            return "—"
        layout = "" if self.channels == 1 else (" · stereo" if self.channels == 2 else f" · {self.channels} ch")
        return ", ".join(sorted(formats)) + layout


@dataclass
class RecordTimecode:
    start_frames: int
    rate: TimecodeRate
    source: str                   # human readable origin, e.g. "slot 'TC1' (manual)"
    manual: bool = False

    @property
    def label(self) -> str:
        return frames_to_label(self.start_frames, self.rate)

    @property
    def display(self) -> str:
        return f"{self.label} @ {self.rate.label}"


@dataclass
class SequenceInfo:
    mob_id: str
    name: str
    edit_rate: Fraction | None
    duration: Fraction            # seconds, longest picture/sound track
    timecode: RecordTimecode | None
    timecode_problem: str | None
    tracks: list[AudioTrack] = field(default_factory=list)
    toplevel: bool = True
    warnings: list[str] = field(default_factory=list)

    def track_by_slot(self, slot_id: int) -> AudioTrack | None:
        for t in self.tracks:
            if t.slot_id == slot_id:
                return t
        return None

    @property
    def duration_label(self) -> str:
        return format_duration(self.duration)


@dataclass
class AAFInspection:
    path: str
    sequences: list[SequenceInfo] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.sequences)
