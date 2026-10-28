"""Timeline reconstruction and export, verified sample-for-sample against the fixture media."""

from fractions import Fraction

import numpy as np
import pytest

from aafgen import Clip, Gap, Media, Track, build_aaf, ramp
from aaf_extractor.bwf.reader import read_bwf
from conftest import export, name, read_samples

SR = 48000
SPF = SR // 25   # samples per frame at 25 fps


def _ok(job, result):
    assert result.count("Completed") == 1, (job.state, job.messages)
    return read_samples(job.exported_path)


def test_single_embedded_mono_clip_per_track(tmp_path, out_dir):
    a, b = ramp(SR * 4), ramp(SR * 4, 777)
    build_aaf(tmp_path / "501.aaf", [Track(1, "", [Clip("a", 0, 100)]), Track(2, "", [Clip("b", 0, 100)])],
              {"a": Media(a), "b": Media(b)}, tc_start=900000)
    job, res = export(tmp_path / "501.aaf", out_dir)
    s = _ok(job, res)
    assert s.shape == (SR * 4, 2)
    assert np.array_equal(s[:, 0], a) and np.array_equal(s[:, 1], b)
    assert job.exported_path.endswith("501_MIX.wav")


def test_stereo_interleaving_left_right_assignment(tmp_path, out_dir):
    a, b = np.full(SR, 1000, np.int32), np.full(SR, -2000, np.int32)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("b", 0, 25)])],
              {"a": Media(a), "b": Media(b)})
    # swap: A2 -> left, A1 -> right
    job, res = export(tmp_path / "x.aaf", out_dir, left=2, right=1)
    s = _ok(job, res)
    assert (s[:, 0] == -2000).all() and (s[:, 1] == 1000).all()
    raw = open(job.exported_path, "rb").read()
    off = read_bwf(job.exported_path).data_offset
    # first frame bytes: L = -2000 (0x...F830) then R = 1000 (0x0003E8)
    assert raw[off:off + 6] == (-2000 & 0xFFFFFF).to_bytes(3, "little") + (1000).to_bytes(3, "little")


def test_different_source_in_points(tmp_path, out_dir):
    a, b = ramp(SR * 10), ramp(SR * 10, 5)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", SR * 2, 50)]), Track(2, "", [Clip("b", SR * 5 + 17, 50)])],
              {"a": Media(a), "b": Media(b)})
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert np.array_equal(s[:, 0], a[SR * 2:SR * 4])
    assert np.array_equal(s[:, 1], b[SR * 5 + 17:SR * 7 + 17])


def test_different_record_start_positions_and_gaps(tmp_path, out_dir):
    a, b = ramp(SR * 4), ramp(SR * 4, 99)
    tracks = [Track(1, "", [Gap(10), Clip("a", 0, 40)]),
              Track(2, "", [Gap(30), Clip("b", 0, 20), Gap(25), Clip("b", 0, 25)])]
    build_aaf(tmp_path / "x.aaf", tracks, {"a": Media(a), "b": Media(b)})
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert s.shape[0] == 100 * SPF
    L, R = s[:, 0], s[:, 1]
    assert (L[:10 * SPF] == 0).all()
    assert np.array_equal(L[10 * SPF:50 * SPF], a[:40 * SPF])
    assert (L[50 * SPF:] == 0).all()            # track shorter than programme -> trailing silence
    assert (R[:30 * SPF] == 0).all()
    assert np.array_equal(R[30 * SPF:50 * SPF], b[:20 * SPF])
    assert (R[50 * SPF:75 * SPF] == 0).all()    # gap -> silence
    assert np.array_equal(R[75 * SPF:], b[:25 * SPF])


def test_programme_length_follows_longest_track_and_picture(tmp_path, out_dir):
    a = ramp(SR * 2)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 50)])],
              {"a": Media(a)}, picture_length=200)
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert s.shape[0] == 200 * SPF               # picture track defines the sequence length
    assert (s[25 * SPF:, 0] == 0).all() and (s[50 * SPF:, 1] == 0).all()


def test_multiple_consecutive_clips_are_contiguous(tmp_path, out_dir):
    a, b = ramp(SR * 6), ramp(SR * 6, 12345)
    tracks = [Track(1, "", [Clip("a", 0, 25), Clip("b", SR * 2, 25), Clip("a", SR * 4, 25)]),
              Track(2, "", [Clip("b", 0, 75)])]
    build_aaf(tmp_path / "x.aaf", tracks, {"a": Media(a), "b": Media(b)})
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    expected = np.concatenate([a[:SR], b[2 * SR:3 * SR], a[4 * SR:5 * SR]])
    assert np.array_equal(s[:, 0], expected)


def test_non_zero_record_timecode_written_to_time_reference(tmp_path, out_dir):
    a = ramp(SR)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 25)])],
              {"a": Media(a)}, tc_start=10 * 3600 * 25 + 12)       # 10:00:00:12
    job, res = export(tmp_path / "x.aaf", out_dir)
    _ok(job, res)
    info = read_bwf(job.exported_path)
    assert info.bext["time_reference"] == (10 * 3600 * 25 + 12) * SPF
    assert job.timecode.label == "10:00:00:12"
    assert "10:00:00:12" in info.bext["description"]


def test_29_97_drop_frame_sequence(tmp_path, out_dir):
    """Non-integer samples per frame: clip edges must be contiguous and TC exact."""
    er = Fraction(30000, 1001)
    a, b = ramp(SR * 4), ramp(SR * 4, 3)
    tracks = [Track(1, "", [Clip("a", 0, 7), Clip("a", 7, 13), Gap(3), Clip("a", 23, 7)]),
              Track(2, "", [Clip("b", 0, 30)])]
    media = {"a": Media(a, mob_edit_rate=er), "b": Media(b, mob_edit_rate=er)}
    build_aaf(tmp_path / "x.aaf", tracks, media, edit_rate=er, tc_fps=30, drop=True,
              tc_start=1078920)                                     # 10:00:00;00
    job, res = export(tmp_path / "x.aaf", out_dir)
    s = _ok(job, res)

    def edge(frames):
        return int((Fraction(frames) * SR / er) + Fraction(1, 2))
    assert s.shape[0] == edge(30)
    L = s[:, 0]
    assert np.array_equal(L[:edge(20)], a[:edge(20)])               # two clips join seamlessly
    assert (L[edge(20):edge(23)] == 0).all()
    assert np.array_equal(L[edge(23):edge(30)], a[edge(23):edge(30)])
    assert job.timecode.label == "10:00:00;00"
    assert read_bwf(job.exported_path).bext["time_reference"] == 1_727_998_272   # 1078920 * 1601.6


def test_audio_rate_track_edit_rate(tmp_path, out_dir):
    """Avid audio tracks may use the sample rate as edit rate."""
    a, b = ramp(SR * 2), ramp(SR * 2, 9)
    tracks = [Track(1, "", [Gap(1000), Clip("a", 333, SR)]), Track(2, "", [Clip("b", 0, SR + 1000)])]
    build_aaf(tmp_path / "x.aaf", tracks, {"a": Media(a), "b": Media(b)}, edit_rate=SR, tc_fps=25,
              tc_edit_rate=25, tc_start=0)
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert (s[:1000, 0] == 0).all()
    assert np.array_equal(s[1000:, 0], a[333:333 + SR])


@pytest.mark.parametrize("kind", ["wave", "aiff"])
def test_embedded_wave_and_aifc_essence(tmp_path, out_dir, kind):
    a, b = ramp(SR * 2), ramp(SR * 2, 50)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 100, 25)]), Track(2, "", [Clip("b", 0, 25)])],
              {"a": Media(a, kind=kind), "b": Media(b, kind=kind)})
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert np.array_equal(s[:, 0], a[100:100 + SR]) and np.array_equal(s[:, 1], b[:SR])


def test_16_bit_source_promoted_losslessly(tmp_path, out_dir):
    a = ramp(SR, 0, bits=16)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 25)])],
              {"a": Media(a, bits=16)})
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert np.array_equal(s[:, 0], a.astype(np.int32) << 8)
    assert "W=16" in read_bwf(next(out_dir.glob("*.wav"))).bext["coding_history"]


def test_external_wav_media(tmp_path, out_dir):
    a, b = ramp(SR), ramp(SR, 4)
    media = {"a": Media(a, kind="external", external_path=tmp_path / "a.wav"),
             "b": Media(b, kind="external", external_path=tmp_path / "b.wav")}
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("b", 0, 25)])], media)
    s = _ok(*export(tmp_path / "x.aaf", out_dir))
    assert np.array_equal(s[:, 0], a) and np.array_equal(s[:, 1], b)


def test_external_media_found_in_search_folder(tmp_path, out_dir):
    a = ramp(SR)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 25)])],
              {"a": Media(a, kind="external", external_path=tmp_path / "a.wav")})
    moved = media_dir / "sub"
    moved.mkdir()
    (tmp_path / "a.wav").rename(moved / "a.wav")
    s = _ok(*export(tmp_path / "x.aaf", out_dir, media_folders=[str(media_dir)]))
    assert np.array_equal(s[:, 0], a)


def test_match_by_track_name(tmp_path, out_dir):
    a, b = ramp(SR), ramp(SR, 8)
    tracks = [Track(1, "DIALOG", [Clip("a", 0, 25)]), Track(5, "MIX L", [Clip("a", 0, 25)]),
              Track(6, "MIX R", [Clip("b", 0, 25)])]
    build_aaf(tmp_path / "x.aaf", tracks, {"a": Media(a), "b": Media(b)})
    job, res = export(tmp_path / "x.aaf", out_dir, left=name("mix l"), right=name("MIX R"))
    s = _ok(job, res)
    assert job.left_track.track_number == 5 and job.right_track.track_number == 6
    assert np.array_equal(s[:, 1], b)


def test_unity_gain_operation_is_pass_through(tmp_path, out_dir):
    from aafgen import Effect
    a = ramp(SR)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Effect(Clip("a", 0, 25), "gain", 1)]),
                                   Track(2, "", [Clip("a", 0, 25)])], {"a": Media(a)})
    job, res = export(tmp_path / "x.aaf", out_dir)
    s = _ok(job, res)
    assert np.array_equal(s[:, 0], a)
    assert any("unity gain" in w for w in job.warnings)
