"""Avid stereo tracks: an Audio Channel Combiner over a two-slot master clip.

Mirrors the structure of the Love Island S5 AAFs: the premixed stereo mix sits
on one track (A31) as consecutive combiner clips (main mix, an insert, main mix
again), each channel backed by its own mono embedded PCM source.
"""

import numpy as np

from aafgen import Clip, Combine, Gap, Media, Track, build_aaf, ramp
from aaf_extractor.batch.models import BatchSettings, ChannelRef, JobState, MatchMethod, TrackSelector
from aaf_extractor.batch.preflight import preflight
from aaf_extractor.batch.runner import run_batch
from aaf_extractor.bwf.reader import read_bwf
from conftest import make_job, read_samples

SR = 48000
SPF = SR // 25


def _stereo(n, seed):
    return np.stack([ramp(n, seed), ramp(n, -seed - 7)], axis=1)


def _love_island_like(path):
    mix, insert, tail = _stereo(SR * 6, 1), _stereo(SR * 2, 100), _stereo(SR * 4, 200)
    media = {"mix": Media(mix, split=True, mob_edit_rate=25),
             "insert": Media(insert, split=True, mob_edit_rate=25),
             "tail": Media(tail, split=True, mob_edit_rate=25),
             "dx": Media(ramp(SR * 12, 5))}
    tracks = [Track(1, "SYNK", [Clip("dx", 0, 300)]),
              Track(31, "", [Combine("mix", 0, 150), Combine("insert", 0, 50), Combine("tail", 0, 100)]),
              Track(32, "", [Gap(300)])]
    build_aaf(path, tracks, media, tc_start=0, picture_length=300)
    expected = np.concatenate([mix[:150 * SPF], insert[:50 * SPF], tail[:100 * SPF]])
    return expected


def _a31(channel):
    return TrackSelector(MatchMethod.NUMBER, 31, channel)


def test_stereo_track_is_inspected_as_two_channels(tmp_path):
    _love_island_like(tmp_path / "LI_501.aaf")
    job = make_job(tmp_path / "LI_501.aaf")
    a31 = [t for t in job.sequence.tracks if t.track_number == 31][0]
    assert a31.errors == [] and a31.channels == 2
    assert a31.format_summary() == "48 kHz / 24-bit · stereo"
    assert [s.channel for s in a31.segments] == [0, 1, 0, 1, 0, 1]
    assert a31.channel_label(1) == "A31 ch2"


def test_stereo_track_exports_left_and_right(tmp_path, out_dir):
    expected = _love_island_like(tmp_path / "LI_501.aaf")
    job = make_job(tmp_path / "LI_501.aaf")
    result = run_batch([job], BatchSettings(output_dir=str(out_dir), left=_a31(0), right=_a31(1)))
    assert result.count("Completed") == 1, job.messages
    s = read_samples(job.exported_path)
    assert s.shape == (300 * SPF, 2)
    assert np.array_equal(s, expected)                      # L = ch1, R = ch2, insert in place
    assert job.left_label == "A31 ch1" and job.right_label == "A31 ch2"
    info = read_bwf(job.exported_path)
    assert info.bext["time_reference"] == 0
    assert "L=A31 ch1 R=A31 ch2" in info.bext["description"]


def test_swapped_channels(tmp_path, out_dir):
    expected = _love_island_like(tmp_path / "x.aaf")
    job = make_job(tmp_path / "x.aaf")
    run_batch([job], BatchSettings(output_dir=str(out_dir), left=_a31(1), right=_a31(0)))
    s = read_samples(job.exported_path)
    assert np.array_equal(s[:, 0], expected[:, 1]) and np.array_equal(s[:, 1], expected[:, 0])


def test_stereo_track_without_channel_needs_attention(tmp_path, out_dir):
    _love_island_like(tmp_path / "x.aaf")
    job = make_job(tmp_path / "x.aaf")
    preflight([job], BatchSettings(output_dir=str(out_dir), left=TrackSelector(MatchMethod.NUMBER, 31),
                                   right=_a31(1)))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "2-channel" in job.messages[0] and "choose a channel" in job.messages[0]


def test_channel_selector_on_mono_track_in_other_episode(tmp_path, out_dir):
    """An episode where A31 is mono must not silently use it for 'A31 ch2'."""
    build_aaf(tmp_path / "y.aaf", [Track(31, "", [Clip("m", 0, 25)])], {"m": Media(ramp(SR))})
    job = make_job(tmp_path / "y.aaf")
    preflight([job], BatchSettings(output_dir=str(out_dir), left=_a31(0), right=_a31(1)))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "A31 ch2 not found" in job.messages[0]


def test_empty_a32_is_reported_not_exported_silently(tmp_path, out_dir):
    _love_island_like(tmp_path / "x.aaf")
    job = make_job(tmp_path / "x.aaf")
    sel = TrackSelector(MatchMethod.NUMBER, 32)
    preflight([job], BatchSettings(output_dir=str(out_dir), left=sel, right=sel))
    assert job.state == JobState.NEEDS_ATTENTION
    assert "empty" in job.messages[0]


def test_per_file_channel_override(tmp_path, out_dir):
    expected = _love_island_like(tmp_path / "x.aaf")
    job = make_job(tmp_path / "x.aaf")
    a31 = [t for t in job.sequence.tracks if t.track_number == 31][0]
    job.override_left = ChannelRef(a31.slot_id, 1)
    job.override_right = ChannelRef(a31.slot_id, 1)
    run_batch([job], BatchSettings(output_dir=str(out_dir), left=_a31(0), right=_a31(1)))
    s = read_samples(job.exported_path)
    assert np.array_equal(s[:, 0], expected[:, 1]) and np.array_equal(s[:, 1], expected[:, 1])


def test_avid_stream_padding_is_never_read(tmp_path, out_dir):
    """Avid pads embedded essence to 4 KiB; frames past the declared Length are not audio."""
    import aaf2
    a = ramp(SR)
    build_aaf(tmp_path / "x.aaf", [Track(1, "", [Clip("a", 0, 25)]), Track(2, "", [Clip("a", 0, 25)])],
              {"a": Media(a)})
    with aaf2.open(str(tmp_path / "x.aaf"), "rw") as f:
        ed = next(iter(f.content.essencedata))
        stream = ed.open("rw")
        stream.seek(0, 2)
        stream.write(b"\x7f" * 2176)                       # junk padding after the samples
    job = make_job(tmp_path / "x.aaf")
    ref = job.sequence.tracks[0].segments[0].media
    assert ref.embedded_format.frames == SR == ref.length_samples
