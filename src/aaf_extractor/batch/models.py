"""Batch queue state."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

from ..aaf.model import AAFInspection, AudioTrack, RecordTimecode, SequenceInfo
from .naming import DEFAULT_SUFFIX

OUTPUT_SAMPLE_RATE = 48000
OUTPUT_BITS = 24
OUTPUT_CHANNELS = 2


class JobState(str, enum.Enum):
    PENDING = "Inspecting"
    READY = "Ready"
    NEEDS_ATTENTION = "Needs attention"
    UNSUPPORTED = "Unsupported"
    EXPORTING = "Exporting"
    COMPLETED = "Completed"
    SKIPPED = "Skipped"
    FAILED = "Failed"


class MatchMethod(str, enum.Enum):
    NUMBER = "number"
    NAME = "name"


class OverwritePolicy(str, enum.Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"


@dataclass
class TrackSelector:
    """How the batch mapping identifies a track (and channel) in every file.

    ``channel`` is None for a mono track, or the 0-based channel of a
    multichannel (stereo) track.
    """
    method: MatchMethod
    value: str | int
    channel: int | None = None

    @property
    def label(self) -> str:
        base = f"A{self.value}" if self.method == MatchMethod.NUMBER else f"\u201c{self.value}\u201d"
        return base if self.channel is None else f"{base} ch{self.channel + 1}"


@dataclass(frozen=True)
class ChannelRef:
    """One output source: a track (by slot id) and a channel within it."""
    slot_id: int
    channel: int = 0


@dataclass
class BatchSettings:
    output_dir: str = ""
    suffix: str = DEFAULT_SUFFIX
    left: TrackSelector | None = None
    right: TrackSelector | None = None
    overwrite: OverwritePolicy = OverwritePolicy.SKIP
    media_folders: list[str] = field(default_factory=list)
    auto_mix: bool = False        # detect the stereo mix track per file instead of left/right


@dataclass
class Job:
    path: str
    inspection: AAFInspection | None = None
    sequence_index: int | None = None        # None until chosen (auto when only one)
    override_left: ChannelRef | None = None  # per-file override
    override_right: ChannelRef | None = None
    timecode_override: RecordTimecode | None = None
    state: JobState = JobState.PENDING
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    left_track: AudioTrack | None = None     # resolved by preflight
    right_track: AudioTrack | None = None
    left_channel: int = 0
    right_channel: int = 0
    selection: str = ""                      # how the tracks were chosen (for display / report)
    output_path: str | None = None
    exported_path: str | None = None
    exported_frames: int | None = None
    time_reference: int | None = None
    diagnostics: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return Path(self.path).name

    @property
    def sequence(self) -> SequenceInfo | None:
        if not self.inspection or not self.inspection.sequences:
            return None
        if self.sequence_index is None:
            if len(self.inspection.sequences) == 1:
                return self.inspection.sequences[0]
            return None
        return self.inspection.sequences[self.sequence_index]

    @property
    def timecode(self) -> RecordTimecode | None:
        if self.timecode_override is not None:
            return self.timecode_override
        seq = self.sequence
        return seq.timecode if seq else None

    @property
    def left_label(self) -> str:
        return self.left_track.channel_label(self.left_channel) if self.left_track else ""

    @property
    def right_label(self) -> str:
        return self.right_track.channel_label(self.right_channel) if self.right_track else ""

    @property
    def has_override(self) -> bool:
        return self.override_left is not None or self.override_right is not None

    @property
    def status_text(self) -> str:
        if self.messages:
            return f"{self.state.value}: {self.messages[0]}"
        return self.state.value
