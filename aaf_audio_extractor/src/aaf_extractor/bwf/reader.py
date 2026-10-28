"""Independent BWF header reader used to verify exported files.

Deliberately shares no code with the writer, so a writer bug cannot hide
itself during verification.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field


@dataclass
class BWFInfo:
    path: str
    file_size: int
    riff_size: int
    chunks: list[tuple[str, int, int]] = field(default_factory=list)  # (id, offset, size)
    format_tag: int = 0
    channels: int = 0
    sample_rate: int = 0
    bits: int = 0
    block_align: int = 0
    data_offset: int = 0
    data_size: int = 0
    bext: dict | None = None

    @property
    def frames(self) -> int:
        return self.data_size // self.block_align if self.block_align else 0

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


class BWFReadError(Exception):
    pass


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", "replace")


def parse_bext(body: bytes) -> dict:
    if len(body) < 602:
        raise BWFReadError("bext chunk shorter than 602 bytes")
    low, high = struct.unpack_from("<II", body, 338)
    (version,) = struct.unpack_from("<H", body, 346)
    return {
        "description": _cstr(body[0:256]),
        "originator": _cstr(body[256:288]),
        "originator_reference": _cstr(body[288:320]),
        "origination_date": _cstr(body[320:330]),
        "origination_time": _cstr(body[330:338]),
        "time_reference": low | (high << 32),
        "version": version,
        "coding_history": body[602:].split(b"\0", 1)[0].decode("ascii", "replace"),
    }


def read_bwf(path) -> BWFInfo:
    path = str(path)
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise BWFReadError("not a RIFF/WAVE file")
        info = BWFInfo(path, size, struct.unpack_from("<I", head, 4)[0])
        pos = 12
        while pos + 8 <= size:
            fh.seek(pos)
            cid, csize = struct.unpack("<4sI", fh.read(8))
            name = cid.decode("ascii", "replace")
            info.chunks.append((name, pos, csize))
            if pos + 8 + csize > size:
                raise BWFReadError(f"chunk '{name}' runs past the end of the file")
            if cid == b"fmt ":
                body = fh.read(csize)
                (info.format_tag, info.channels, info.sample_rate, _avg,
                 info.block_align, info.bits) = struct.unpack_from("<HHIIHH", body)
            elif cid == b"bext":
                info.bext = parse_bext(fh.read(csize))
            elif cid == b"data":
                info.data_offset = pos + 8
                info.data_size = csize
            pos += 8 + csize + (csize & 1)
    return info


def verify_bwf(path, *, sample_rate: int, channels: int, bits: int, frames: int,
               time_reference: int) -> list[str]:
    """Return a list of problems (empty when the file is as expected)."""
    problems: list[str] = []
    try:
        info = read_bwf(path)
    except (OSError, BWFReadError, struct.error) as exc:
        return [f"cannot read back output: {exc}"]
    if info.riff_size != info.file_size - 8:
        problems.append(f"RIFF size {info.riff_size} does not match file size {info.file_size}")
    names = [c[0] for c in info.chunks]
    for required in ("bext", "fmt ", "data"):
        if names.count(required) != 1:
            problems.append(f"expected exactly one '{required.strip()}' chunk, found {names.count(required)}")
    if info.format_tag != 1:
        problems.append(f"format tag {info.format_tag} is not PCM")
    if info.sample_rate != sample_rate:
        problems.append(f"sample rate {info.sample_rate} != {sample_rate}")
    if info.channels != channels:
        problems.append(f"channel count {info.channels} != {channels}")
    if info.bits != bits:
        problems.append(f"bit depth {info.bits} != {bits}")
    if info.block_align != channels * bits // 8:
        problems.append(f"block align {info.block_align} is wrong")
    if info.block_align and info.data_size % info.block_align:
        problems.append("data size is not a whole number of sample frames")
    if info.frames != frames:
        problems.append(f"sample count {info.frames} != expected {frames}")
    if info.bext is None:
        problems.append("bext chunk missing")
    elif info.bext["time_reference"] != time_reference:
        problems.append(f"TimeReference {info.bext['time_reference']} != expected {time_reference}")
    return problems
