"""Header parsers for the PCM containers we can read: RIFF/WAVE, AIFF/AIFC, MXF.

Each parser returns an :class:`EssenceFormat` describing where the PCM samples
live. None of them reads sample data.
"""

from __future__ import annotations

import struct
from typing import BinaryIO

from ..aaf.model import EssenceFormat

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_EXTENSIBLE = 0xFFFE
# KSDATAFORMAT_SUBTYPE_PCM
_PCM_SUBFORMAT = bytes.fromhex("0100000000001000800000aa00389b71")


class ContainerError(ValueError):
    pass


def _read_exact(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise ContainerError("unexpected end of data")
    return data


def parse_wave_fmt(fmt: bytes) -> tuple[int, int, int]:
    """Return (sample_rate, channels, bits) from a ``fmt `` chunk body."""
    if len(fmt) < 16:
        raise ContainerError("fmt chunk too short")
    tag, channels, rate, _avg, block_align, bits = struct.unpack_from("<HHIIHH", fmt)
    if tag == WAVE_FORMAT_EXTENSIBLE:
        if len(fmt) < 40:
            raise ContainerError("WAVE_FORMAT_EXTENSIBLE fmt chunk too short")
        if fmt[24:40] != _PCM_SUBFORMAT:
            raise ContainerError("extensible WAVE sub-format is not integer PCM")
    elif tag != WAVE_FORMAT_PCM:
        raise ContainerError(f"WAVE format tag 0x{tag:04x} is not integer PCM")
    if channels < 1:
        raise ContainerError("WAVE file declares no channels")
    container_bytes = (bits + 7) // 8
    if block_align != channels * container_bytes:
        raise ContainerError(f"unsupported WAVE block alignment {block_align} for {channels} x {bits}-bit")
    return rate, channels, bits


def parse_wave(f: BinaryIO, total_size: int | None = None, base: int = 0) -> EssenceFormat:
    """Parse a RIFF/WAVE (or RF64/BW64) header starting at ``base``."""
    f.seek(base)
    header = _read_exact(f, 12)
    riff, _size, wave = struct.unpack("<4sI4s", header)
    if riff not in (b"RIFF", b"RF64", b"BW64") or wave != b"WAVE":
        raise ContainerError("not a RIFF/WAVE stream")
    pos = base + 12
    fmt = None
    ds64_data_size = None
    while True:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            break
        cid, size = struct.unpack("<4sI", head)
        body = pos + 8
        if cid == b"ds64":
            ds64 = _read_exact(f, min(size, 28))
            ds64_data_size = struct.unpack_from("<Q", ds64, 8)[0]
        elif cid == b"fmt ":
            fmt = _read_exact(f, size)
        elif cid == b"data":
            if fmt is None:
                raise ContainerError("WAVE data chunk precedes fmt chunk")
            rate, channels, bits = parse_wave_fmt(fmt)
            if size == 0xFFFFFFFF and ds64_data_size is not None:
                size = ds64_data_size
            available = size
            if total_size is not None:
                available = min(size, max(0, base + total_size - body))
            return EssenceFormat(rate, channels, bits, False, body, available)
        pos = body + size + (size & 1)
    raise ContainerError("WAVE stream has no data chunk")


def _ieee_extended_to_int(data: bytes) -> int:
    exponent, mantissa = struct.unpack(">HQ", data)
    exponent &= 0x7FFF
    if exponent == 0 and mantissa == 0:
        return 0
    value = mantissa * 2.0 ** (exponent - 16383 - 63)
    return int(round(value))


def parse_aiff(f: BinaryIO, total_size: int | None = None, base: int = 0) -> EssenceFormat:
    """Parse an AIFF/AIFC header. Only uncompressed integer PCM is accepted."""
    f.seek(base)
    form, _size, kind = struct.unpack(">4sI4s", _read_exact(f, 12))
    if form != b"FORM" or kind not in (b"AIFF", b"AIFC"):
        raise ContainerError("not an AIFF/AIFC stream")
    pos = base + 12
    comm = None
    big_endian = True
    while True:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            break
        cid, size = struct.unpack(">4sI", head)
        body = pos + 8
        if cid == b"COMM":
            comm = _read_exact(f, size)
            channels, _frames, bits = struct.unpack_from(">hIh", comm)
            rate = _ieee_extended_to_int(comm[8:18])
            if kind == b"AIFC":
                compression = comm[18:22]
                if compression in (b"sowt",):
                    big_endian = False
                elif compression not in (b"NONE", b"twos"):
                    raise ContainerError(f"AIFC compression {compression!r} is not supported")
            comm = (rate, channels, bits)
        elif cid == b"SSND":
            if comm is None:
                raise ContainerError("AIFF SSND chunk precedes COMM chunk")
            offset, _block = struct.unpack(">II", _read_exact(f, 8))
            start = body + 8 + offset
            available = size - 8 - offset
            if total_size is not None:
                available = min(available, max(0, base + total_size - start))
            rate, channels, bits = comm
            return EssenceFormat(rate, channels, bits, big_endian, start, available)
        pos = body + size + (size & 1)
    raise ContainerError("AIFF stream has no SSND chunk")


def sniff(f: BinaryIO, base: int = 0) -> str | None:
    f.seek(base)
    head = f.read(12)
    if head[:4] in (b"RIFF", b"RF64", b"BW64") and head[8:12] == b"WAVE":
        return "wave"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:4] == bytes.fromhex("060e2b34"):
        return "mxf"
    return None


def parse_any(f: BinaryIO, total_size: int | None = None) -> EssenceFormat:
    kind = sniff(f)
    if kind == "wave":
        return parse_wave(f, total_size)
    if kind == "aiff":
        return parse_aiff(f, total_size)
    raise ContainerError("unrecognised audio container")


# --- MXF ---------------------------------------------------------------------

# Generic Container sound essence element: 06.0e.2b.34.01.02.01.01.0d.01.03.01 | 16 cc tt nn
_GC_ELEMENT_PREFIX = bytes.fromhex("060e2b34010201010d010301")
_GC_SOUND_ITEM = 0x16
_BWF_ELEMENT_TYPES = (0x01, 0x02)   # BWF frame-wrapped, BWF clip-wrapped
_AES3_ELEMENT_TYPES = (0x03, 0x04)


def _read_ber_length(f: BinaryIO) -> int:
    first = _read_exact(f, 1)[0]
    if first < 0x80:
        return first
    n = first & 0x7F
    if n == 0 or n > 8:
        raise ContainerError("invalid MXF BER length")
    return int.from_bytes(_read_exact(f, n), "big")


def scan_mxf_sound_essence(f: BinaryIO, file_size: int) -> tuple[list[tuple[int, int]], int]:
    """Return the (offset, length) runs of PCM sound essence and the element type.

    Supports OP-Atom / OP1a files with a single BWF sound track, frame- or
    clip-wrapped. AES3 element types are rejected because their sample layout
    differs from plain PCM.
    """
    runs: list[tuple[int, int]] = []
    element_key = None
    element_type = 0
    pos = 0
    while pos + 17 <= file_size:
        f.seek(pos)
        key = f.read(16)
        if len(key) < 16:
            break
        if key[:4] != bytes.fromhex("060e2b34"):
            raise ContainerError(f"MXF KLV stream is not aligned at byte {pos}")
        length = _read_ber_length(f)
        value_pos = f.tell()
        if key[:12] == _GC_ELEMENT_PREFIX and key[12] == _GC_SOUND_ITEM:
            if element_key is None:
                element_key = key
                element_type = key[14]
            elif key != element_key:
                raise ContainerError("MXF file contains more than one sound essence element; "
                                     "only single-track (OP-Atom style) audio files are supported")
            if length:
                runs.append((value_pos, length))
        pos = value_pos + length
    if element_key is None:
        raise ContainerError("MXF file contains no sound essence")
    if element_type in _AES3_ELEMENT_TYPES:
        raise ContainerError("MXF AES3 sound essence is not supported (only BWF/PCM wrapping)")
    if element_type not in _BWF_ELEMENT_TYPES:
        raise ContainerError(f"MXF sound element type 0x{element_type:02x} is not supported")
    return runs, element_type
