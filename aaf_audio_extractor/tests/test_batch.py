"""Batch execution: mixed results, cancellation, overwrite policies, retry and report."""

import csv
import threading

import numpy as np

from aafgen import Clip, Media, Track, build_aaf, ramp
from aaf_extractor.batch.models import BatchSettings, JobState, OverwritePolicy
from aaf_extractor.batch.runner import run_batch
from aaf_extractor.bwf.reader import read_bwf
from conftest import make_job, number, read_samples

SR = 48000


def _episode(folder, ep, seconds=2, tracks=None, tc=None):
    a, b = ramp(SR * seconds, ep), ramp(SR * seconds, -ep)
    frames = seconds * 25
    tracks = tracks or [Track(1, "", [Clip("a", 0, frames)]), Track(2, "", [Clip("b", 0, frames)])]
    return build_aaf(folder / f"{ep}.aaf", tracks, {"a": Media(a), "b": Media(b)},
                     name=f"EP {ep}", tc_start=tc if tc is not None else 10 * 3600 * 25 + ep)


def _settings(out_dir, **kw):
    return BatchSettings(output_dir=str(out_dir), left=number(1), right=number(2), **kw)


def test_batch_with_success_and_failures(tmp_path, out_dir):
    paths = [_episode(tmp_path, ep) for ep in (501, 502, 503)]
    paths.append(_episode(tmp_path, 504, tracks=[Track(1, "", [Clip("a", 0, 50)])]))   # no A2
    bad = tmp_path / "505.aaf"
    bad.write_bytes(b"garbage")
    paths.append(bad)
    jobs = [make_job(p) for p in paths]
    result = run_batch(jobs, _settings(out_dir))
    assert result.count("Completed") == 3
    assert result.count("Skipped") == 2
    assert [j.state for j in jobs] == [JobState.COMPLETED] * 3 + [JobState.NEEDS_ATTENTION, JobState.UNSUPPORTED]
    for ep, job in zip((501, 502, 503), jobs):
        info = read_bwf(out_dir / f"{ep}_MIX.wav")
        assert info.bext["time_reference"] == (10 * 3600 * 25 + ep) * 1920   # each file keeps its own TC
    assert result.report_path
    rows = list(csv.DictReader(open(result.report_path, encoding="utf-8-sig")))
    assert [r["Input AAF"] for r in rows] == [p.name for p in paths]
    assert rows[0]["Result"] == "Completed" and rows[0]["Exported file"] == "501_MIX.wav"
    assert rows[0]["Record timecode"] == "10:00:20:01" and rows[0]["Timecode rate"] == "25 NDF"
    assert rows[0]["Sample rate"] == "48000" and rows[0]["Bit depth"] == "24"
    assert rows[0]["Duration (samples)"] == str(SR * 2)
    assert rows[3]["Result"] == "Skipped" and rows[3]["Message"] == "Needs attention: track A2 not found"


def test_failure_during_render_does_not_stop_batch(tmp_path, out_dir, monkeypatch):
    paths = [_episode(tmp_path, ep) for ep in (1, 2, 3)]
    jobs = [make_job(p) for p in paths]
    from aaf_extractor.batch import runner
    real = runner.render

    def flaky(plans, frames, sink, *a, **kw):
        if flaky.calls == 1:
            flaky.calls += 1
            sink(b"\0" * 6 * 10)
            raise IOError("disk full (simulated)")
        flaky.calls += 1
        return real(plans, frames, sink, *a, **kw)
    flaky.calls = 0
    monkeypatch.setattr(runner, "render", flaky)
    result = run_batch(jobs, _settings(out_dir))
    assert [r.result for r in result.results] == ["Completed", "Failed", "Completed"]
    assert "disk full" in result.results[1].message
    assert not (out_dir / "2_MIX.wav").exists()
    assert not list(out_dir.glob("*.partial"))

    # Retry: only the failed file is rendered again.
    monkeypatch.setattr(runner, "render", real)
    before = (out_dir / "1_MIX.wav").stat().st_mtime_ns
    result = run_batch(jobs, _settings(out_dir))
    assert [r.result for r in result.results] == ["Skipped", "Completed", "Skipped"]
    assert result.results[0].message == "already exported"
    assert (out_dir / "1_MIX.wav").stat().st_mtime_ns == before


def test_cancellation_mid_render(tmp_path, out_dir):
    paths = [_episode(tmp_path, ep, seconds=12) for ep in (1, 2, 3)]
    jobs = [make_job(p) for p in paths]
    cancel = threading.Event()

    def progress(job, done, total):
        if job is jobs[1] and done >= total // 2:
            cancel.set()
    result = run_batch(jobs, _settings(out_dir), cancel=cancel, on_progress=progress)
    assert result.cancelled
    assert [r.result for r in result.results] == ["Completed", "Cancelled", "Cancelled"]
    assert (out_dir / "1_MIX.wav").exists()                      # completed file preserved
    assert not (out_dir / "2_MIX.wav").exists()                  # incomplete file removed
    assert not list(out_dir.glob("*.partial"))
    assert [j.state for j in jobs] == [JobState.COMPLETED, JobState.READY, JobState.READY]
    # The untouched files are still available for another run.
    result = run_batch(jobs, _settings(out_dir))
    assert [r.result for r in result.results] == ["Skipped", "Completed", "Completed"]


def test_overwrite_policies(tmp_path, out_dir):
    path = _episode(tmp_path, 7)
    existing = out_dir / "7_MIX.wav"
    existing.write_bytes(b"precious")

    job = make_job(path)
    result = run_batch([job], _settings(out_dir, overwrite=OverwritePolicy.SKIP))
    assert result.results[0].result == "Skipped"
    assert existing.read_bytes() == b"precious"

    job = make_job(path)
    result = run_batch([job], _settings(out_dir, overwrite=OverwritePolicy.RENAME))
    assert result.results[0].result == "Completed"
    assert existing.read_bytes() == b"precious"
    assert job.exported_path.endswith("7_MIX_1.wav")
    assert read_bwf(job.exported_path).frames == SR * 2

    job = make_job(path)
    result = run_batch([job], _settings(out_dir, overwrite=OverwritePolicy.OVERWRITE))
    assert result.results[0].result == "Completed"
    assert read_bwf(existing).frames == SR * 2


def test_collision_does_not_block_other_files(tmp_path, out_dir):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    jobs = [make_job(_episode(tmp_path / "a", 9)), make_job(_episode(tmp_path / "b", 9)),
            make_job(_episode(tmp_path, 10))]
    result = run_batch(jobs, _settings(out_dir))
    assert [r.result for r in result.results] == ["Skipped", "Skipped", "Completed"]
    assert "collides" in result.results[0].message


def test_thirty_two_episode_batch(tmp_path, out_dir):
    """The production scenario: 32 AAFs, shared mapping, individual record timecodes."""
    jobs = []
    for i, ep in enumerate(range(501, 533)):
        tc = (9 + i % 3) * 3600 * 25 + i * 37
        jobs.append(make_job(_episode(tmp_path, ep, seconds=1, tc=tc)))
    result = run_batch(jobs, _settings(out_dir))
    assert result.count("Completed") == 32
    for i, ep in enumerate(range(501, 533)):
        out = out_dir / f"{ep}_MIX.wav"
        info = read_bwf(out)
        assert info.bext["time_reference"] == ((9 + i % 3) * 3600 * 25 + i * 37) * 1920
        s = read_samples(out)
        assert np.array_equal(s[:, 0], ramp(SR, ep)) and np.array_equal(s[:, 1], ramp(SR, -ep))
