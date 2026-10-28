"""Preflight: problems must be reported, never silently worked around."""

from fractions import Fraction

from aafgen import Clip, Effect, Gap, Media, Track, build_aaf, ramp
from aaf_extractor.aaf.model import RecordTimecode
from aaf_extractor.batch.models import BatchSettings, ChannelRef, JobState
from aaf_extractor.batch.preflight import preflight
from aaf_extractor.timecode import TimecodeRate
from conftest import make_job, name, number

SR = 48000


def _two(tmp_path, fname="x.aaf", **kw):
    a = ramp(SR * 2)
    tracks = kw.pop("tracks", [Track(1, "MIX L", [Clip("a", 0, 25)]), Track(2, "MIX R", [Clip("a", 0, 25)])])
    media = kw.pop("media", {"a": Media(a)})
    return build_aaf(tmp_path / fname, tracks, media, **kw)


def _check(path, out_dir, left=number(1), right=number(2), **kw):
    job = make_job(path)
    preflight([job], BatchSettings(output_dir=str(out_dir), left=left, right=right, **kw))
    return job


def test_ready(tmp_path, out_dir):
    job = _check(_two(tmp_path), out_dir)
    assert job.state == JobState.READY, job.messages


def test_missing_track(tmp_path, out_dir):
    job = _check(_two(tmp_path), out_dir, right=number(3))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "A3 not found" in job.messages[0]


def test_ambiguous_track_name(tmp_path, out_dir):
    tracks = [Track(1, "MIX", [Clip("a", 0, 25)]), Track(2, "MIX", [Clip("a", 0, 25)])]
    job = _check(_two(tmp_path, tracks=tracks), out_dir, left=name("MIX"), right=number(2))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "ambiguous" in job.messages[0]


def test_missing_external_media(tmp_path, out_dir):
    media = {"a": Media(ramp(SR), kind="external", external_path=tmp_path / "gone.wav")}
    path = _two(tmp_path, media=media)
    (tmp_path / "gone.wav").unlink()
    job = _check(path, out_dir)
    assert job.state == JobState.NEEDS_ATTENTION
    assert "not found" in job.messages[0]


def test_external_media_with_wrong_format_is_rejected(tmp_path, out_dir):
    import wave
    media = {"a": Media(ramp(SR), kind="external", external_path=tmp_path / "a.wav")}
    path = _two(tmp_path, media=media)
    with wave.open(str(tmp_path / "a.wav"), "wb") as w:   # replaced by a different file
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"\0\0" * SR)
    job = _check(path, out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "differs" in job.messages[0]


def test_unsupported_effect(tmp_path, out_dir):
    tracks = [Track(1, "", [Effect(Clip("a", 0, 25), "eq")]), Track(2, "", [Clip("a", 0, 25)])]
    job = _check(_two(tmp_path, tracks=tracks), out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "effect" in job.messages[0]


def test_non_unity_gain_is_unsupported(tmp_path, out_dir):
    tracks = [Track(1, "", [Effect(Clip("a", 0, 25), "gain", Fraction(1, 2))]), Track(2, "", [Clip("a", 0, 25)])]
    job = _check(_two(tmp_path, tracks=tracks), out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "non-unity gain" in job.messages[0]


def test_transition_is_unsupported(tmp_path, out_dir):
    tracks = [Track(1, "", [Clip("a", 0, 20), "transition", Clip("a", 20, 15)]), Track(2, "", [Clip("a", 0, 25)])]
    job = _check(_two(tmp_path, tracks=tracks), out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "transition" in job.messages[0]


def test_unsupported_track_not_selected_does_not_block(tmp_path, out_dir):
    tracks = [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 25)]),
              Track(3, "", [Effect(Clip("a", 0, 25), "eq")])]
    job = _check(_two(tmp_path, tracks=tracks), out_dir)
    assert job.state == JobState.READY


def test_unsupported_sample_rate(tmp_path, out_dir):
    media = {"a": Media(ramp(44100), sample_rate=44100)}
    job = _check(_two(tmp_path, media=media), out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "44100" in job.messages[0]


def test_clip_beyond_end_of_media(tmp_path, out_dir):
    # media is 2 s long; a 1 s clip starting at 1.5 s needs 0.5 s that does not exist
    tracks = [Track(1, "", [Clip("a", SR * 3 // 2, 25)]), Track(2, "", [Clip("a", 0, 25)])]
    job = _check(_two(tmp_path, tracks=tracks), out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "beyond the end" in job.messages[0]


def test_missing_timecode_needs_attention_then_manual_override(tmp_path, out_dir):
    job = _check(_two(tmp_path, tc_start=None), out_dir)
    assert job.state == JobState.NEEDS_ATTENTION
    assert "timecode" in job.messages[0]
    job.timecode_override = RecordTimecode(900000, TimecodeRate.from_nominal(25), "manual override", manual=True)
    preflight([job], BatchSettings(output_dir=str(out_dir), left=number(1), right=number(2)))
    assert job.state == JobState.READY
    assert any("manually" in w for w in job.warnings)


def test_multiple_sequences_require_choice(tmp_path, out_dir):
    job = _check(_two(tmp_path, extra_sequences=1), out_dir)
    assert job.state == JobState.NEEDS_ATTENTION
    assert "choose" in job.messages[0]
    job.sequence_index = 1
    preflight([job], BatchSettings(output_dir=str(out_dir), left=number(1), right=number(2)))
    assert job.state == JobState.READY
    assert job.sequence.name.endswith("ALT 1")


def test_non_toplevel_single_composition_is_found(tmp_path, out_dir):
    job = _check(_two(tmp_path, toplevel=False), out_dir)
    assert job.state == JobState.READY


def test_not_an_aaf(tmp_path, out_dir):
    p = tmp_path / "bad.aaf"
    p.write_bytes(b"this is not an AAF file")
    job = _check(p, out_dir)
    assert job.state == JobState.UNSUPPORTED
    assert "cannot open" in job.messages[0]


def test_output_filename_collisions(tmp_path, out_dir):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    p1 = _two(tmp_path / "a", "501.aaf")
    p2 = _two(tmp_path / "b", "501.aaf")
    p3 = _two(tmp_path, "502.aaf")
    jobs = [make_job(p1), make_job(p2), make_job(p3)]
    preflight(jobs, BatchSettings(output_dir=str(out_dir), left=number(1), right=number(2)))
    assert [j.state for j in jobs] == [JobState.NEEDS_ATTENTION, JobState.NEEDS_ATTENTION, JobState.READY]
    assert "collides" in jobs[0].messages[0]


def test_case_insensitive_collision(tmp_path, out_dir):
    """Windows file names are case-insensitive: Ep1.aaf and EP1.AAF both want Ep1_MIX.wav."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    jobs = [make_job(_two(tmp_path / "a", "Ep1.aaf")), make_job(_two(tmp_path / "b", "EP1.AAF"))]
    preflight(jobs, BatchSettings(output_dir=str(out_dir), left=number(1), right=number(2)))
    assert all(j.state == JobState.NEEDS_ATTENTION for j in jobs)


def test_no_output_folder(tmp_path):
    job = make_job(_two(tmp_path))
    preflight([job], BatchSettings(output_dir="", left=number(1), right=number(2)))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "output folder" in job.messages[-1]


def test_per_file_override(tmp_path, out_dir):
    tracks = [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 25)]), Track(3, "", [Gap(5), Clip("a", 0, 20)])]
    p1, p2 = _two(tmp_path, "1.aaf", tracks=tracks), _two(tmp_path, "2.aaf", tracks=tracks)
    jobs = [make_job(p1), make_job(p2)]
    third = jobs[1].sequence.tracks[2]
    jobs[1].override_right = ChannelRef(third.slot_id)
    preflight(jobs, BatchSettings(output_dir=str(out_dir), left=number(1), right=number(2)))
    assert jobs[0].right_track.track_number == 2
    assert jobs[1].right_track.track_number == 3
