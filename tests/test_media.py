"""Media containers and locator handling."""

import io
import os
import struct

import numpy as np
import pytest

from aafgen import aiff_bytes, pcm_bytes, ramp, wav_bytes
from aaf_extractor.aaf.model import EssenceFormat, MediaRef
from aaf_extractor.media.containers import ContainerError, parse_aiff, parse_wave, scan_mxf_sound_essence
from aaf_extractor.media.reader import PCMReader, SegmentedFile
from aaf_extractor.media.resolver import MediaError, resolve, url_to_path


def test_parse_wave_and_aiff():
    s = ramp(100)
    fmt = parse_wave(io.BytesIO(wav_bytes(s, 48000, 24)))
    assert (fmt.sample_rate, fmt.channels, fmt.bits, fmt.data_offset, fmt.frames) == (48000, 1, 24, 44, 100)
    fmt = parse_aiff(io.BytesIO(aiff_bytes(s, 48000, 24)))
    assert (fmt.sample_rate, fmt.channels, fmt.bits, fmt.big_endian, fmt.frames) == (48000, 1, 24, True, 100)


def test_reject_float_wave():
    data = bytearray(wav_bytes(ramp(10), 48000, 24))
    struct.pack_into("<H", data, 20, 3)   # WAVE_FORMAT_IEEE_FLOAT
    with pytest.raises(ContainerError):
        parse_wave(io.BytesIO(bytes(data)))


def test_reader_multichannel_and_big_endian():
    stereo = np.stack([ramp(50), ramp(50, 1000)], axis=1)
    fmt = EssenceFormat(48000, 2, 24, False, 0, 50 * 6)
    r = PCMReader(io.BytesIO(pcm_bytes(stereo, 24)), fmt, 1, owns_handle=False)
    assert np.array_equal(r.read(10, 20), ramp(50, 1000)[10:30])
    be = EssenceFormat(48000, 1, 16, True, 0, 100)
    r = PCMReader(io.BytesIO(pcm_bytes(ramp(50, -100, bits=16), 16, big_endian=True)), be, 0, owns_handle=False)
    assert np.array_equal(r.read(0, 50), ramp(50, -100, bits=16).astype(np.int32) << 8)
    with pytest.raises(EOFError):
        r.read(40, 20)


def _klv(key: bytes, value: bytes) -> bytes:
    n = len(value)
    return key + bytes([0x83]) + n.to_bytes(3, "big") + value


def _mxf(tmp_path, element_type=0x01, chunks=3):
    s = ramp(300, 5)
    raw = pcm_bytes(s, 24)
    partition = bytes.fromhex("060e2b34020501010d01020101020400")
    element = bytes.fromhex("060e2b34010201010d010301") + bytes([0x16, 0x01, element_type, 0x01])
    body = _klv(partition, b"\0" * 88)
    step = len(raw) // chunks
    for i in range(chunks):
        body += _klv(element, raw[i * step:(i + 1) * step if i < chunks - 1 else len(raw)])
    p = tmp_path / "audio.mxf"
    p.write_bytes(body)
    return p, s


def test_mxf_frame_wrapped_pcm(tmp_path):
    p, s = _mxf(tmp_path)
    with open(p, "rb") as fh:
        runs, etype = scan_mxf_sound_essence(fh, os.path.getsize(p))
        assert etype == 1 and len(runs) == 3
        fmt = EssenceFormat(48000, 1, 24, False, 0, sum(n for _, n in runs))
        r = PCMReader(SegmentedFile(fh, runs), fmt, 0, owns_handle=False)
        assert np.array_equal(r.read(90, 120), s[90:210])   # spans a KLV boundary


def test_mxf_aes3_rejected(tmp_path):
    p, _ = _mxf(tmp_path, element_type=0x03)
    with open(p, "rb") as fh, pytest.raises(ContainerError, match="AES3"):
        scan_mxf_sound_essence(fh, os.path.getsize(p))


def test_resolve_mxf_by_locator(tmp_path):
    p, s = _mxf(tmp_path, element_type=0x02, chunks=1)
    ref = MediaRef("urn:x", "A1", "PCMDescriptor", 0, EssenceFormat(48000, 1, 24), 300, False,
                   locators=[p.resolve().as_uri()])
    res = resolve(ref, str(tmp_path / "x.aaf"))
    assert res.frames == 300 and res.runs


@pytest.mark.parametrize("url,expected_nt,expected_posix", [
    ("file:///C:/Avid%20MediaFiles/MXF/1/a.mxf", r"C:\Avid MediaFiles\MXF\1\a.mxf", "C:/Avid MediaFiles/MXF/1/a.mxf"),
    ("file://?/C:/Media/a.wav", r"C:\Media\a.wav", "C:/Media/a.wav"),
    ("file:///C|/Media/a.wav", r"C:\Media\a.wav", "C:/Media/a.wav"),
    ("file://server/share/a.wav", r"\\server\share\a.wav", "//server/share/a.wav"),
    ("file:///home/user/a.wav", r"\home\user\a.wav", "/home/user/a.wav"),
])
def test_url_to_path(url, expected_nt, expected_posix):
    assert url_to_path(url) == (expected_nt if os.name == "nt" else expected_posix)


def test_missing_media_error_is_specific(tmp_path):
    ref = MediaRef("urn:x", "A1.PHYS", "PCMDescriptor", 0, EssenceFormat(48000, 1, 24), 10, False, locators=[])
    with pytest.raises(MediaError) as exc:
        resolve(ref, str(tmp_path / "x.aaf"))
    assert exc.value.code == "missing"
    assert "not embedded" in str(exc.value)


def test_ambiguous_search_folder_match(tmp_path):
    from aaf_extractor.media.resolver import MediaIndex
    for sub in ("one", "two"):
        (tmp_path / "m" / sub).mkdir(parents=True)
        (tmp_path / "m" / sub / "a.wav").write_bytes(wav_bytes(ramp(10), 48000, 24))
    ref = MediaRef("urn:x", "A1", "PCMDescriptor", 0, EssenceFormat(48000, 1, 24), 10, False,
                   locators=["file:///nowhere/a.wav"])
    with pytest.raises(MediaError) as exc:
        resolve(ref, str(tmp_path / "x.aaf"), MediaIndex([str(tmp_path / "m")]))
    assert exc.value.code == "ambiguous"
