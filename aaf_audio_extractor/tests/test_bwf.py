import struct

import numpy as np

from aaf_extractor.audio.render import pack_int24_interleaved
from aaf_extractor.bwf.reader import read_bwf, verify_bwf
from aaf_extractor.bwf.writer import BextInfo, BWFWriter
from conftest import read_samples


def _write(path, frames=1000, tref=1_728_000_000, desc="test"):
    left = np.arange(frames, dtype=np.int32) - 500
    right = -left
    with BWFWriter(path, 48000, 2, 24, BextInfo(description=desc, originator="AAF Audio Extractor",
                                                time_reference=tref, coding_history="A=PCM,F=48000,W=24,M=stereo")) as w:
        w.write(pack_int24_interleaved([left, right]))
    return left, right


def test_roundtrip_header_and_samples(tmp_path):
    p = tmp_path / "a.wav"
    left, right = _write(p)
    info = read_bwf(p)
    assert (info.format_tag, info.channels, info.sample_rate, info.bits, info.block_align) == (1, 2, 48000, 24, 6)
    assert info.frames == 1000
    assert info.riff_size == p.stat().st_size - 8
    assert [c[0] for c in info.chunks] == ["bext", "fmt ", "data"]
    assert info.bext["time_reference"] == 1_728_000_000
    assert info.bext["version"] == 1
    assert info.bext["originator"] == "AAF Audio Extractor"
    assert info.bext["coding_history"] == "A=PCM,F=48000,W=24,M=stereo\r\n"
    s = read_samples(p)
    assert np.array_equal(s[:, 0], left) and np.array_equal(s[:, 1], right)
    assert verify_bwf(p, sample_rate=48000, channels=2, bits=24, frames=1000, time_reference=1_728_000_000) == []


def test_bext_layout_offsets(tmp_path):
    """TimeReference must sit at byte 338 of the bext body (EBU Tech 3285)."""
    p = tmp_path / "a.wav"
    _write(p, tref=(5 << 32) + 7)
    raw = p.read_bytes()
    body = raw.index(b"bext") + 8
    low, high = struct.unpack_from("<II", raw, body + 338)
    assert (low, high) == (7, 5)
    assert raw[body + 320:body + 330] .decode().count("-") == 2   # YYYY-MM-DD
    assert raw[body + 330:body + 338].decode().count(":") == 2   # HH:MM:SS
    assert read_bwf(p).bext["time_reference"] == (5 << 32) + 7


def test_non_ascii_description_is_transliterated(tmp_path):
    p = tmp_path / "a.wav"
    _write(p, desc="Epé — L=A1")
    assert read_bwf(p).bext["description"] == "Epe - L=A1"


def test_verify_detects_problems(tmp_path):
    p = tmp_path / "a.wav"
    _write(p)
    problems = verify_bwf(p, sample_rate=44100, channels=2, bits=24, frames=999, time_reference=1)
    text = " ".join(problems)
    assert "sample rate" in text and "sample count" in text and "TimeReference" in text
    # truncate the file: RIFF size no longer matches
    data = p.read_bytes()
    p.write_bytes(data[:-6])
    assert any("past the end" in x or "RIFF size" in x for x in
               verify_bwf(p, sample_rate=48000, channels=2, bits=24, frames=1000, time_reference=1_728_000_000))


def test_odd_sized_data_is_padded(tmp_path):
    p = tmp_path / "mono.wav"
    with BWFWriter(p, 48000, 1, 24, BextInfo()) as w:
        w.write(b"\x01\x02\x03")
    info = read_bwf(p)
    assert info.data_size == 3
    assert p.stat().st_size == info.data_offset + 4
    assert info.riff_size == p.stat().st_size - 8
