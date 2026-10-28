"""Offscreen smoke test of the main window: load, map, export without blocking."""

import time

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QCoreApplication, QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from aafgen import Clip, Media, Track, build_aaf, ramp  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # Keep the test away from the operator's real saved settings.
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("qsettings")))
    app = QApplication.instance() or QApplication([])
    yield app
    app.shutdown()   # deterministic teardown, as in main()


def _wait(app, predicate, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_main_window_batch_export(app, tmp_path, monkeypatch):
    from aaf_extractor.gui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    shown = []
    monkeypatch.setattr(MainWindow, "_show_report", lambda self, result: shown.append(result))

    for ep in (1, 2, 3):   # one subfolder per episode, as on the server
        (tmp_path / f"50{ep}").mkdir()
        build_aaf(tmp_path / f"50{ep}" / f"{ep}.aaf",
                  [Track(1, "", [Clip("x", 0, 25)]), Track(2, "", [Clip("y", 0, 25)]), Track(3, "", [Clip("z", 0, 25)])],
                  {k: Media(ramp(48000, i)) for i, k in enumerate("xyz")}, tc_start=900000 + ep)
    out = tmp_path / "out"
    w = MainWindow()
    w.out_edit.setText(str(out))
    w._on_settings_changed()
    w.add_paths([str(tmp_path)])
    assert [j.filename for j in w.jobs] == ["1.aaf", "2.aaf", "3.aaf"]
    assert "from 3 folder(s)" in w.status.text()
    assert _wait(app, lambda: w._inspect_worker is None and all(j.inspection for j in w.jobs))

    w.file_table.selectRow(0)
    w.left_combo.setCurrentIndex(1)     # A2
    w.right_combo.setCurrentIndex(2)    # A3
    w._apply_to_all()
    assert w.settings.left.value == 2 and w.settings.right.value == 3
    assert all(j.state.value == "Ready" for j in w.jobs)

    w._start_export(selected_only=False)
    assert w._busy()
    assert not w.btn_export_all.isEnabled() and w.btn_cancel.isEnabled()
    assert _wait(app, lambda: shown)
    assert shown[0].count("Completed") == 3
    assert sorted(p.name for p in out.glob("*.wav")) == ["1_MIX.wav", "2_MIX.wav", "3_MIX.wav"]
    w.close()
    # Destroy the window (and its finished worker threads) while QApplication is alive.
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_auto_detect_checkbox_exports_mix_from_any_track(app, tmp_path, monkeypatch):
    import numpy as np
    from aafgen import Combine
    from aaf_extractor.gui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    shown = []
    monkeypatch.setattr(MainWindow, "_show_report", lambda self, result: shown.append(result))

    for ep, mix_track in ((1, 31), (2, 27)):
        mix = np.stack([ramp(48000, ep), ramp(48000, -ep)], axis=1)
        build_aaf(tmp_path / f"{ep}.aaf",
                  [Track(1, "", [Clip("dx", 0, 25)]), Track(mix_track, "", [Combine("mix", 0, 25)])],
                  {"dx": Media(ramp(48000)), "mix": Media(mix, split=True, mob_edit_rate=25)}, tc_start=0)
    out = tmp_path / "out"
    w = MainWindow()
    w.out_edit.setText(str(out))
    w._on_settings_changed()
    w.add_paths([str(tmp_path)])
    assert _wait(app, lambda: w._inspect_worker is None and all(j.inspection for j in w.jobs))
    w.auto_mix_check.setChecked(True)
    assert w.settings.auto_mix
    assert not w.btn_apply_all.isEnabled()
    assert [j.left_label for j in w.jobs] == ["A31 ch1", "A27 ch1"]
    assert "(auto)" in w.file_table.item(0, 4).text()
    w._start_export(selected_only=False)
    assert _wait(app, lambda: shown)
    assert shown[0].count("Completed") == 2
    w.auto_mix_check.setChecked(False)   # do not leak the saved setting into other tests
    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
