"""Chunked PCM sample reading.

Samples are returned as int32 numpy arrays scaled to 24-bit full scale: 24-bit
sources pass through unchanged, 16-bit sources are shifted left by 8 bits
(an exact, lossless conversion). Other bit depths are refused.
"""

from __future__ import annotations

import numpy as np

from ..aaf.model import EssenceFormat

SUPPORTED_BITS = (16, 24)


class SegmentedFile:
    """Present several byte runs of a file (MXF essence KLVs) as one stream."""

    def __init__(self, fh, runs: list[tuple[int, int]]):
        self.fh = fh
        self.runs = runs
        self.pos = 0
        self.size = sum(n for _, n in runs)

    def seek(self, pos: int, whence: int = 0):
        self.pos = pos
        return pos

    def read(self, n: int) -> bytes:
        out = bytearray()
        offset = 0
        for start, length in self.runs:
            if n <= 0:
                break
            if self.pos < offset + length:
                within = self.pos - offset
                take = min(length - within, n)
                self.fh.seek(start + within)
                chunk = self.fh.read(take)
                out += chunk
                self.pos += len(chunk)
                n -= len(chunk)
                if len(chunk) < take:
                    break
            offset += length
        return bytes(out)

    def close(self):
        self.fh.close()


class PCMReader:
    def __init__(self, handle, fmt: EssenceFormat, channel: int, owns_handle: bool):
        if fmt.bits not in SUPPORTED_BITS:
            raise ValueError(f"{fmt.bits}-bit source audio is not supported (16 or 24-bit integer PCM only)")
        if not 0 <= channel < fmt.channels:
            raise ValueError(f"channel {channel + 1} does not exist in {fmt.channels}-channel media")
        self.handle = handle
        self.fmt = fmt
        self.channel = channel
        self.owns_handle = owns_handle
        self.width = (fmt.bits + 7) // 8
        self.frames = fmt.frames

    def read(self, start: int, count: int) -> np.ndarray:
        """Read ``count`` frames from frame ``start`` of the selected channel."""
        if count <= 0:
            return np.zeros(0, dtype=np.int32)
        if start < 0 or start + count > self.frames:
            raise EOFError(f"read of frames {start}..{start + count} exceeds media length {self.frames}")
        block = self.fmt.block_align
        # Never seek past the end: pyaaf2 streams would extend themselves.
        self.handle.seek(self.fmt.data_offset + start * block)
        raw = self.handle.read(count * block)
        if len(raw) != count * block:
            raise EOFError(f"media ended early: wanted {count * block} bytes, got {len(raw)}")
        b = np.frombuffer(raw, dtype=np.uint8).reshape(count, self.fmt.channels, self.width)[:, self.channel, :]
        if self.fmt.big_endian:
            b = b[:, ::-1]
        if self.width == 3:
            v = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)
            v = np.where(v & 0x800000, v - 0x1000000, v).astype(np.int32)
        else:  # 16-bit, promoted losslessly to 24-bit
            v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8))
            v = np.where(v & 0x8000, v - 0x10000, v).astype(np.int32) << 8
        return v

    def close(self):
        if self.owns_handle:
            self.handle.close()
