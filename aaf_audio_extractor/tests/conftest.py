import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Settings and logs of test runs go to a throw-away folder, never the operator's.
os.environ["AAF_EXTRACTOR_DATA_DIR"] = tempfile.mkdtemp(prefix="aaf_extractor_test_data_")

from aaf_extractor.aaf.inspector import inspect_aaf  # noqa: E402
from aaf_extractor.batch.models import (BatchSettings, Job, JobState, MatchMethod,  # noqa: E402
                                        OverwritePolicy, TrackSelector)
from aaf_extractor.batch.runner import run_batch  # noqa: E402
from aaf_extractor.bwf.reader import read_bwf  # noqa: E402


def read_samples(path) -> np.ndarray:
    """Return (frames, channels) int32 samples of a 24-bit WAV."""
    info = read_bwf(path)
    assert info.bits == 24
    with open(path, "rb") as fh:
        fh.seek(info.data_offset)
        raw = fh.read(info.data_size)
    b = np.frombuffer(raw, np.uint8).reshape(-1, info.channels, 3).astype(np.int32)
    v = b[..., 0] | (b[..., 1] << 8) | (b[..., 2] << 16)
    return np.where(v & 0x800000, v - 0x1000000, v).astype(np.int32)


def number(n):
    return TrackSelector(MatchMethod.NUMBER, n)


def name(n):
    return TrackSelector(MatchMethod.NAME, n)


def make_job(path) -> Job:
    job = Job(str(path))
    job.inspection = inspect_aaf(str(path))
    job.sequence_index = 0 if len(job.inspection.sequences) == 1 else None
    job.state = JobState.READY
    return job


def export(aaf_path, out_dir, left=1, right=2, **settings_kw):
    """Inspect + export a single AAF; return (job, BatchResult)."""
    job = make_job(aaf_path)
    left = left if isinstance(left, TrackSelector) else number(left)
    right = right if isinstance(right, TrackSelector) else number(right)
    settings = BatchSettings(output_dir=str(out_dir), left=left, right=right, **settings_kw)
    result = run_batch([job], settings)
    return job, result


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    return d


__all__ = ["read_samples", "number", "name", "make_job", "export", "BatchSettings", "OverwritePolicy"]
