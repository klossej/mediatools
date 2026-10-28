"""Recursive discovery of AAF files in added/dropped folders."""

import os

from aaf_extractor.batch.discover import find_aaf_files, natural_key


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_episode_subfolders_are_found_in_natural_order(tmp_path):
    for ep in (532, 501, 510, 502):
        _touch(tmp_path / str(ep) / f"LI_{ep}.aaf")
    _touch(tmp_path / "510" / "notes.txt")
    _touch(tmp_path / "510" / "MIX.wav")
    found = [os.path.relpath(p, tmp_path) for p in find_aaf_files([tmp_path])]
    assert found == [os.path.join(str(ep), f"LI_{ep}.aaf") for ep in (501, 502, 510, 532)]


def test_deeply_nested_and_mixed_case_extension(tmp_path):
    _touch(tmp_path / "a" / "b" / "c" / "deep.AAF")
    _touch(tmp_path / "top.aaf")
    found = [os.path.relpath(p, tmp_path) for p in find_aaf_files([tmp_path])]
    assert sorted(found) == sorted([os.path.join("a", "b", "c", "deep.AAF"), "top.aaf"])


def test_hidden_and_system_folders_are_skipped(tmp_path):
    _touch(tmp_path / ".hidden" / "x.aaf")
    _touch(tmp_path / "$RECYCLE.BIN" / "y.aaf")
    _touch(tmp_path / "ok" / "z.aaf")
    assert [os.path.basename(p) for p in find_aaf_files([tmp_path])] == ["z.aaf"]


def test_files_and_folders_mixed(tmp_path):
    single = _touch(tmp_path / "single" / "one.aaf")
    _touch(tmp_path / "root" / "502" / "LI_502.aaf")
    _touch(tmp_path / "root" / "501" / "LI_501.aaf")
    _touch(tmp_path / "not_aaf.txt")
    found = find_aaf_files([single, tmp_path / "root", tmp_path / "not_aaf.txt", tmp_path / "missing.aaf"])
    assert [os.path.basename(p) for p in found] == ["one.aaf", "LI_501.aaf", "LI_502.aaf"]


def test_symlinked_folder_loop_does_not_hang(tmp_path):
    _touch(tmp_path / "eps" / "501" / "LI_501.aaf")
    try:
        os.symlink(tmp_path / "eps", tmp_path / "eps" / "501" / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):
        return   # symlinks unavailable (e.g. Windows without privilege)
    assert [os.path.basename(p) for p in find_aaf_files([tmp_path / "eps"])] == ["LI_501.aaf"]


def test_natural_key():
    names = ["LI_10.aaf", "LI_9.aaf", "li_100.aaf", "LI_1.aaf"]
    assert sorted(names, key=natural_key) == ["LI_1.aaf", "LI_9.aaf", "LI_10.aaf", "li_100.aaf"]
