"""Long programmes must stream with bounded memory."""

import tracemalloc

import numpy as np
import pytest

from aafgen import Clip, Media, Track, build_aaf
from aaf_extractor.aaf.model import EssenceFormat, MediaRef
from aaf_extractor.audio.render import ChannelPlan, PlacedSegment, render
from aaf_extractor.media.resolver import ResolvedMedia
from conftest import export

SR = 48000


class _SyntheticReader:
    """Generates samples on demand: value = (frame index mod 2^23)."""

    def __init__(self, frames):
        self.frames = frames

    def read(self, start, count):
        return (np.arange(start, start + count, dtype=np.int64) % (1 << 23)).astype(np.int32)

    def close(self):
        pass


def test_ninety_minute_render_memory_is_bounded():
    frames = SR * 60 * 90
    fmt = EssenceFormat(SR, 1, 24, False, 0, frames * 3)
    media = ResolvedMedia(MediaRef("urn:m", "m", "PCMDescriptor", 0, fmt, frames, True, fmt), "embedded", fmt)
    plans = [ChannelPlan("L", [PlacedSegment(SR, frames - SR, media, 0)]),
             ChannelPlan("R", [PlacedSegment(0, frames, media, 0)])]
    state = {"bytes": 0, "last": None}

    def sink(data):
        state["bytes"] += len(data)
        state["last"] = data[-6:]

    tracemalloc.start()
    written = render(plans, frames, sink, lambda m: _SyntheticReader(frames))
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert written == frames
    assert state["bytes"] == frames * 6
    assert peak < 48 * 1024 * 1024, f"peak traced memory {peak / 1e6:.1f} MB"
    # last frame: L = frames-SR-1, R = frames-1 (mod 2^23)
    last_l = int.from_bytes(state["last"][:3], "little")
    last_r = int.from_bytes(state["last"][3:], "little")
    assert last_l == (frames - SR - 1) % (1 << 23) and last_r == (frames - 1) % (1 << 23)


@pytest.mark.slow
def test_ten_minute_embedded_export_end_to_end(tmp_path, out_dir):
    n = SR * 600
    a = (np.arange(n, dtype=np.int64) % (1 << 23)).astype(np.int32)
    build_aaf(tmp_path / "long.aaf", [Track(1, "", [Clip("a", 0, 600 * 25)]), Track(2, "", [Clip("a", 0, 600 * 25)])],
              {"a": Media(a)})
    del a
    tracemalloc.start()
    job, result = export(tmp_path / "long.aaf", out_dir)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.count("Completed") == 1, job.messages
    assert job.exported_frames == n
    assert peak < 64 * 1024 * 1024, f"peak traced memory {peak / 1e6:.1f} MB"
