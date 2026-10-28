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
    return QApplication.instance() or QApplication([])


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

    for ep in (1, 2, 3):
        build_aaf(tmp_path / f"{ep}.aaf",
                  [Track(1, "", [Clip("x", 0, 25)]), Track(2, "", [Clip("y", 0, 25)]), Track(3, "", [Clip("z", 0, 25)])],
                  {k: Media(ramp(48000, i)) for i, k in enumerate("xyz")}, tc_start=900000 + ep)
    out = tmp_path / "out"
    w = MainWindow()
    w.out_edit.setText(str(out))
    w._on_settings_changed()
    w.add_paths([str(tmp_path)])
    assert len(w.jobs) == 3
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
