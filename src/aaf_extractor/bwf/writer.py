"""Streaming Broadcast Wave (EBU Tech 3285, bext version 1) writer.

Layout: RIFF/WAVE, ``bext``, ``fmt `` (WAVE_FORMAT_PCM), ``data``. The header
is written first with placeholder sizes, sample data is streamed, and the sizes
are patched on close. Files that would exceed the 4 GiB RIFF limit are refused
(about 4 h 8 min of 48 kHz / 24-bit stereo).
"""

from __future__ import annotations

import struct
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime

BEXT_FIXED_SIZE = 602
RIFF_LIMIT = 0xFFFFFFFF


class BWFWriteError(Exception):
    pass


def to_ascii(value: str) -> str:
    """bext text fields are ASCII; transliterate rather than drop characters."""
    value = value.replace("\u2014", "-").replace("\u2013", "-").replace("\u201c", '"').replace("\u201d", '"')
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


@dataclass
class BextInfo:
    description: str = ""
    originator: str = ""
    originator_reference: str = ""
    origination: datetime = field(default_factory=datetime.now)
    time_reference: int = 0
    coding_history: str = ""

    def pack(self) -> bytes:
        def text(value: str, size: int) -> bytes:
            raw = to_ascii(value).encode("ascii", "replace")[:size]
            return raw.ljust(size, b"\0")

        ref = self.originator_reference or ("AAFX" + uuid.uuid4().hex[:28].upper())
        body = b"".join([
            text(self.description, 256),
            text(self.originator, 32),
            text(ref, 32),
            text(self.origination.strftime("%Y-%m-%d"), 10),
            text(self.origination.strftime("%H:%M:%S"), 8),
            struct.pack("<II", self.time_reference & 0xFFFFFFFF, (self.time_reference >> 32) & 0xFFFFFFFF),
            struct.pack("<H", 1),          # BWF version 1
            b"\0" * 64,                    # UMID (not used)
            b"\0" * 190,                   # reserved
        ])
        assert len(body) == BEXT_FIXED_SIZE
        history = to_ascii(self.coding_history).encode("ascii")
        if history and not history.endswith(b"\r\n"):
            history += b"\r\n"
        return body + history


class BWFWriter:
    def __init__(self, path, sample_rate: int, channels: int, bits: int, bext: BextInfo):
        if bits % 8:
            raise BWFWriteError("bit depth must be a whole number of bytes")
        self.path = str(path)
        self.sample_rate = sample_rate
        self.channels = channels
        self.bits = bits
        self.block_align = channels * bits // 8
        self.data_bytes = 0
        self._fh = open(self.path, "wb")
        try:
            self._write_header(bext)
        except Exception:
            self._fh.close()
            raise

    def _write_header(self, bext: BextInfo):
        bext_body = bext.pack()
        fmt = struct.pack("<HHIIHH", 1, self.channels, self.sample_rate,
                          self.sample_rate * self.block_align, self.block_align, self.bits)
        fh = self._fh
        fh.write(b"RIFF\0\0\0\0WAVE")
        fh.write(b"bext" + struct.pack("<I", len(bext_body)) + bext_body)
        if len(bext_body) & 1:
            fh.write(b"\0")
        fh.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        self._data_size_pos = fh.tell() + 4
        fh.write(b"data\0\0\0\0")
        self._data_start = fh.tell()

    def write(self, data: bytes):
        if len(data) % self.block_align:
            raise BWFWriteError("partial sample frame written")
        if self._data_start + self.data_bytes + len(data) > RIFF_LIMIT - 1:
            raise BWFWriteError("output exceeds the 4 GiB WAV size limit")
        self._fh.write(data)
        self.data_bytes += len(data)

    @property
    def frames(self) -> int:
        return self.data_bytes // self.block_align

    def close(self):
        fh = self._fh
        if fh.closed:
            return
        try:
            if self.data_bytes & 1:
                fh.write(b"\0")
            end = fh.tell()
            fh.seek(self._data_size_pos)
            fh.write(struct.pack("<I", self.data_bytes))
            fh.seek(4)
            fh.write(struct.pack("<I", end - 8))
            fh.flush()
        finally:
            fh.close()

    def abort(self):
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            self.abort()
