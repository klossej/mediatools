"""Auto-detection of the stereo mix track."""

import csv

import numpy as np

from aafgen import Clip, Combine, Effect, Gap, Media, Track, build_aaf, ramp
from aaf_extractor.batch.models import BatchSettings, ChannelRef, JobState
from aaf_extractor.batch.preflight import preflight
from aaf_extractor.batch.runner import run_batch
from conftest import make_job, read_samples

SR = 48000
SPF = SR // 25
LEN = 250   # sequence length in frames (10 s)


def _stereo(seconds, seed):
    n = SR * seconds
    return np.stack([ramp(n, seed), ramp(n, -seed - 3)], axis=1)


def _media(**named):
    return {k: Media(v, split=True, mob_edit_rate=25) if v.ndim == 2 else Media(v) for k, v in named.items()}


def _auto(out_dir, **kw):
    return BatchSettings(output_dir=str(out_dir), auto_mix=True, **kw)


def _build(path, tracks, media):
    build_aaf(path, tracks, media, tc_start=900000, picture_length=LEN)
    return make_job(path)


def test_single_full_length_stereo_track(tmp_path, out_dir):
    job = _build(tmp_path / "e.aaf",
                 [Track(1, "DX", [Clip("dx", 0, LEN)]), Track(7, "", [Combine("mix", 0, LEN)])],
                 _media(dx=ramp(SR * 10), mix=_stereo(10, 1)))
    preflight([job], _auto(out_dir))
    assert job.state == JobState.READY, job.messages
    assert (job.left_label, job.right_label, job.selection) == ("A7 ch1", "A7 ch2", "auto-detected")
    assert any("auto-detected: A7" in w for w in job.warnings)


def test_partial_stereo_music_is_not_the_mix(tmp_path, out_dir):
    tracks = [Track(20, "MUSIK", [Gap(100), Combine("music", 0, 100), Gap(50)]),
              Track(31, "", [Combine("mix", 0, LEN)])]
    job = _build(tmp_path / "e.aaf", tracks, _media(music=_stereo(4, 2), mix=_stereo(10, 1)))
    preflight([job], _auto(out_dir))
    assert job.left_label == "A31 ch1"


def test_mix_name_breaks_tie(tmp_path, out_dir):
    tracks = [Track(30, "", [Combine("ambience", 0, LEN)]),
              Track(31, "", [Combine("EP_MIX_R128", 0, LEN)])]
    job = _build(tmp_path / "e.aaf", tracks, _media(ambience=_stereo(10, 2), EP_MIX_R128=_stereo(10, 1)))
    preflight([job], _auto(out_dir))
    assert job.state == JobState.READY
    assert job.left_label == "A31 ch1"
    assert any("only one named MIX" in w for w in job.warnings)


def test_ambiguous_candidates_need_attention(tmp_path, out_dir):
    tracks = [Track(30, "", [Combine("a", 0, LEN)]), Track(31, "", [Combine("b", 0, LEN)])]
    job = _build(tmp_path / "e.aaf", tracks, _media(a=_stereo(10, 2), b=_stereo(10, 1)))
    preflight([job], _auto(out_dir))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "several full-length stereo tracks" in job.messages[0]
    assert "A30" in job.messages[0] and "A31" in job.messages[0]


def test_no_mix_found_lists_candidates(tmp_path, out_dir):
    tracks = [Track(1, "", [Clip("dx", 0, LEN)]),
              Track(20, "", [Gap(150), Combine("music", 0, 100)]),
              Track(22, "", [Effect(Clip("dx", 0, LEN), "gain", 0.5)])]
    job = _build(tmp_path / "e.aaf", tracks, _media(dx=ramp(SR * 10), music=_stereo(4, 2)))
    preflight([job], _auto(out_dir))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "no full-length stereo mix track" in job.messages[0]
    assert "A20 (40%)" in job.messages[0]


def test_unsupported_stereo_track_is_reported(tmp_path, out_dir):
    tracks = [Track(31, "", [Combine("mix", 0, 200), "transition", Combine("mix", 200, 60)])]
    job = _build(tmp_path / "e.aaf", tracks, _media(mix=_stereo(12, 1)))
    preflight([job], _auto(out_dir))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "unsupported stereo tracks: A31" in job.messages[0]


def test_mix_starting_late_still_detected_and_padded(tmp_path, out_dir):
    mix = _stereo(10, 1)
    job = _build(tmp_path / "e.aaf", [Track(31, "", [Gap(10), Combine("mix", 0, LEN - 10)])], _media(mix=mix))
    result = run_batch([job], _auto(out_dir))
    assert result.count("Completed") == 1, job.messages
    s = read_samples(job.exported_path)
    assert (s[:10 * SPF] == 0).all()
    assert np.array_equal(s[10 * SPF:], mix[:(LEN - 10) * SPF])


def test_override_beats_auto_detect(tmp_path, out_dir):
    tracks = [Track(1, "", [Clip("dx", 0, LEN)]), Track(31, "", [Combine("mix", 0, LEN)])]
    job = _build(tmp_path / "e.aaf", tracks, _media(dx=ramp(SR * 10), mix=_stereo(10, 1)))
    dx = job.sequence.tracks[0]
    job.override_left = job.override_right = ChannelRef(dx.slot_id, 0)
    preflight([job], _auto(out_dir))
    assert (job.left_label, job.selection) == ("A1", "per-file override")


def test_batch_with_mix_on_different_tracks(tmp_path, out_dir):
    """The production case: the mix is not always on A31."""
    jobs, mixes = [], {}
    for ep, mix_track in ((501, 31), (502, 29), (503, 12)):
        mixes[ep] = _stereo(10, ep)
        tracks = [Track(1, "SYNK", [Clip("dx", 0, LEN)]),
                  Track(20, "MUSIK", [Gap(50), Combine("music", 0, 100), Gap(100)]),
                  Track(mix_track, "", [Combine("mix", 0, LEN)])]
        jobs.append(_build(tmp_path / f"{ep}.aaf", tracks,
                           _media(dx=ramp(SR * 10), music=_stereo(4, 9), mix=mixes[ep])))
    result = run_batch(jobs, _auto(out_dir))
    assert result.count("Completed") == 3
    for job, (ep, track_no) in zip(jobs, ((501, 31), (502, 29), (503, 12))):
        assert job.left_label == f"A{track_no} ch1"
        assert np.array_equal(read_samples(out_dir / f"{ep}_MIX.wav"), mixes[ep])
    rows = list(csv.DictReader(open(result.report_path, encoding="utf-8-sig")))
    assert [r["Track selection"] for r in rows] == ["auto-detected"] * 3
    assert [r["Left track"] for r in rows] == ["A31 ch1", "A29 ch1", "A12 ch1"]
