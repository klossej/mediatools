"""Main window."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..aaf.model import RecordTimecode
from ..appinfo import diagnostic_report
from ..batch.models import (BatchSettings, ChannelRef, Job, JobState, MatchMethod, OverwritePolicy,
                            TrackSelector)
from ..batch.discover import find_aaf_files
from ..batch.naming import DEFAULT_SUFFIX, output_name
from ..batch.preflight import PreflightIssue, match_track, preflight
from ..batch.runner import RESULT_COMPLETED, BatchResult
from ..media.resolver import MediaError, MediaIndex, resolve
from ..timecode import TimecodeError, TimecodeRate, format_duration, label_to_frames
from . import style
from .workers import ExportWorker, InspectWorker

log = logging.getLogger(__name__)

FILE_COLUMNS = ["File", "Sequence", "Record TC", "Duration", "Left", "Right", "Status"]
TRACK_COLUMNS = ["Track", "Name", "Format", "Duration", "Media"]

TC_RATES = [
    ("23.976 NDF", TimecodeRate.from_nominal(24, False, pulldown=True)),
    ("24", TimecodeRate.from_nominal(24)),
    ("25", TimecodeRate.from_nominal(25)),
    ("29.97 DF", TimecodeRate.from_nominal(30, True)),
    ("29.97 NDF", TimecodeRate.from_nominal(30, False, pulldown=True)),
    ("30", TimecodeRate.from_nominal(30)),
    ("50", TimecodeRate.from_nominal(50)),
    ("59.94 DF", TimecodeRate.from_nominal(60, True)),
    ("59.94 NDF", TimecodeRate.from_nominal(60, False, pulldown=True)),
    ("60", TimecodeRate.from_nominal(60)),
]


def _panel() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Panel")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    return frame, lay


def _title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("SectionTitle")
    return lab


def _secondary(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("secondary", True)
    return lab


def _item(text: str, tooltip: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    if tooltip:
        it.setToolTip(tooltip)
    return it


def _table(columns: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(26)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.horizontalHeader().setHighlightSections(False)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return t


class TimecodeDialog(QDialog):
    def __init__(self, parent, current: RecordTimecode | None):
        super().__init__(parent)
        self.setWindowTitle("Set Record Timecode")
        lay = QVBoxLayout(self)
        lay.addWidget(_secondary("Enter the sequence record start. It will be written as the BWF\n"
                                 "TimeReference and noted as a manual override in the report."))
        form = QFormLayout()
        self.tc = QLineEdit(current.label if current else "10:00:00:00")
        self.rate = QComboBox()
        for label, rate in TC_RATES:
            self.rate.addItem(label, rate)
        if current:
            for i, (_l, r) in enumerate(TC_RATES):
                if r == current.rate:
                    self.rate.setCurrentIndex(i)
        else:
            self.rate.setCurrentIndex(2)
        form.addRow("Start timecode", self.tc)
        form.addRow("Rate", self.rate)
        lay.addLayout(form)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {style.ERROR}")
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.value: RecordTimecode | None = None

    def _accept(self):
        rate = self.rate.currentData()
        try:
            frames = label_to_frames(self.tc.text(), rate)
        except TimecodeError as exc:
            self.error.setText(str(exc))
            return
        self.value = RecordTimecode(frames, rate, "manual override", manual=True)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1280, 820)
        self.jobs: list[Job] = []
        self.settings = BatchSettings()
        self.qsettings = QSettings("AAF Audio Extractor", "AAF Audio Extractor")
        self._threads: list[QThread] = []
        self._inspect_worker: InspectWorker | None = None
        self._export_worker: ExportWorker | None = None
        self._pending_inspect: list[Job] = []
        self._media_index: MediaIndex | None = None
        self._export_count = 0
        self._loading_settings = True
        self._build_ui()
        self._load_settings()
        self._loading_settings = False
        self._refresh_all()

    # --- UI construction ----------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        header.addWidget(title)
        version = QLabel(f"v{__version__}")
        version.setObjectName("Version")
        header.addWidget(version)
        header.addStretch(1)
        self.btn_diag = QPushButton("Save Diagnostic Report…")
        self.btn_diag.clicked.connect(self._save_diagnostics)
        header.addWidget(self.btn_diag)
        root.addLayout(header)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_input_panel())
        lower = QSplitter(Qt.Horizontal)
        lower.setChildrenCollapsible(False)
        lower.addWidget(self._build_track_panel())
        lower.addWidget(self._build_export_panel())
        lower.setSizes([700, 520])
        splitter.addWidget(lower)
        splitter.setSizes([380, 420])
        root.addWidget(splitter, 1)

        self.status = _secondary("Add AAF files to begin. You can also drop files or folders onto this window.")
        root.addWidget(self.status)
        self.setCentralWidget(central)

        QShortcut(QKeySequence.Delete, self.file_table, activated=self._remove_selected)

    def _build_input_panel(self) -> QWidget:
        frame, lay = _panel()
        top = QHBoxLayout()
        top.addWidget(_title("Input files"))
        top.addStretch(1)
        self.btn_add = QPushButton("Add AAF Files…")
        self.btn_add_folder = QPushButton("Add Folder…")
        self.btn_add_folder.setToolTip("Adds every .aaf file in the folder and all its subfolders.")
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_clear = QPushButton("Clear List")
        for b in (self.btn_add, self.btn_add_folder, self.btn_remove, self.btn_clear):
            top.addWidget(b)
        self.btn_add.clicked.connect(self._add_files)
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear)
        lay.addLayout(top)

        self.file_table = _table(FILE_COLUMNS)
        hh = self.file_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, width in enumerate([150, 220, 105, 115, 130, 130]):
            self.file_table.setColumnWidth(col, width)
        self.file_table.itemSelectionChanged.connect(self._on_file_selection)
        lay.addWidget(self.file_table, 1)
        self.queue_summary = _secondary("")
        lay.addWidget(self.queue_summary)
        return frame

    def _build_track_panel(self) -> QWidget:
        frame, lay = _panel()
        self.track_title = _title("Tracks")
        lay.addWidget(self.track_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.addWidget(_secondary("Sequence"), 0, 0)
        self.seq_combo = QComboBox()
        self.seq_combo.currentIndexChanged.connect(self._on_sequence_changed)
        grid.addWidget(self.seq_combo, 0, 1, 1, 2)
        grid.addWidget(_secondary("Record start"), 1, 0)
        self.tc_label = QLabel("—")
        grid.addWidget(self.tc_label, 1, 1)
        tc_buttons = QHBoxLayout()
        self.btn_tc = QPushButton("Set Timecode…")
        self.btn_tc.clicked.connect(self._set_timecode)
        self.btn_tc_clear = QPushButton("Use AAF Timecode")
        self.btn_tc_clear.clicked.connect(self._clear_timecode)
        tc_buttons.addWidget(self.btn_tc)
        tc_buttons.addWidget(self.btn_tc_clear)
        grid.addLayout(tc_buttons, 1, 2, Qt.AlignRight)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        self.track_table = _table(TRACK_COLUMNS)
        th = self.track_table.horizontalHeader()
        th.setStretchLastSection(True)
        for col, width in enumerate([60, 140, 180, 110]):
            self.track_table.setColumnWidth(col, width)
        self.track_table.setSelectionMode(QAbstractItemView.NoSelection)
        lay.addWidget(self.track_table, 1)

        self.auto_mix_check = QCheckBox("Auto-detect stereo mix track in every file")
        self.auto_mix_check.setToolTip(
            "Per file, use the stereo track whose audio spans at least 90% of the sequence\n"
            "(channel 1 \u2192 Left, channel 2 \u2192 Right). If several qualify, the one named MIX wins;\n"
            "otherwise the file is marked Needs attention. Per-file overrides still apply.")
        self.auto_mix_check.toggled.connect(self._on_auto_mix_toggled)
        lay.addWidget(self.auto_mix_check)

        assign = QGridLayout()
        assign.setHorizontalSpacing(8)
        assign.addWidget(_secondary("Left channel"), 0, 0)
        self.left_combo = QComboBox()
        assign.addWidget(self.left_combo, 0, 1)
        assign.addWidget(_secondary("Right channel"), 0, 2)
        self.right_combo = QComboBox()
        assign.addWidget(self.right_combo, 0, 3)
        self.left_combo.activated.connect(self._on_left_chosen)
        assign.setColumnStretch(1, 1)
        assign.setColumnStretch(3, 1)
        lay.addLayout(assign)

        buttons = QHBoxLayout()
        self.btn_apply_all = QPushButton("Apply to All Files")
        self.btn_apply_all.setObjectName("Primary")
        self.btn_apply_all.setToolTip("Use these tracks for every file in the list, matched by the chosen method.\n"
                                      "Clears any per-file overrides.")
        self.btn_override = QPushButton("This File Only")
        self.btn_override.setToolTip("Override the left/right tracks for the selected file only.")
        self.btn_revert = QPushButton("Revert to Batch Mapping")
        self.btn_apply_all.clicked.connect(self._apply_to_all)
        self.btn_override.clicked.connect(self._override_file)
        self.btn_revert.clicked.connect(self._revert_override)
        buttons.addWidget(self.btn_override)
        buttons.addWidget(self.btn_revert)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_apply_all)
        lay.addLayout(buttons)

        match = QHBoxLayout()
        match.addWidget(_secondary("Match tracks across files by"))
        self.match_combo = QComboBox()
        self.match_combo.addItem("Track number (A1, A2…)", MatchMethod.NUMBER.value)
        self.match_combo.addItem("Track name", MatchMethod.NAME.value)
        self.match_combo.currentIndexChanged.connect(self._on_match_method_changed)
        match.addWidget(self.match_combo)
        match.addStretch(1)
        lay.addLayout(match)
        self.mapping_label = _secondary("Batch mapping: not set")
        lay.addWidget(self.mapping_label)
        return frame

    def _build_export_panel(self) -> QWidget:
        frame, lay = _panel()
        lay.addWidget(_title("Export"))
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        form.addWidget(_secondary("Output folder"), 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Choose where the WAV files are written")
        self.out_edit.editingFinished.connect(self._on_settings_changed)
        form.addWidget(self.out_edit, 0, 1)
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(self._browse_output)
        form.addWidget(btn_out, 0, 2)

        form.addWidget(_secondary("Filename suffix"), 1, 0)
        self.suffix_edit = QLineEdit(DEFAULT_SUFFIX)
        self.suffix_edit.textChanged.connect(self._update_preview)
        self.suffix_edit.editingFinished.connect(self._on_settings_changed)
        form.addWidget(self.suffix_edit, 1, 1, 1, 2)

        form.addWidget(_secondary("Filename"), 2, 0)
        self.preview = QLabel("—")
        self.preview.setObjectName("Preview")
        form.addWidget(self.preview, 2, 1, 1, 2)

        form.addWidget(_secondary("If file exists"), 3, 0)
        self.overwrite_combo = QComboBox()
        self.overwrite_combo.addItem("Skip (keep existing file)", OverwritePolicy.SKIP.value)
        self.overwrite_combo.addItem("Add a number (501_MIX_1.wav)", OverwritePolicy.RENAME.value)
        self.overwrite_combo.addItem("Overwrite", OverwritePolicy.OVERWRITE.value)
        self.overwrite_combo.currentIndexChanged.connect(self._on_settings_changed)
        form.addWidget(self.overwrite_combo, 3, 1, 1, 2)

        form.addWidget(_secondary("Media folder"), 4, 0)
        self.media_edit = QLineEdit()
        self.media_edit.setPlaceholderText("Optional: where linked (non-embedded) media lives")
        self.media_edit.editingFinished.connect(self._on_media_folder_changed)
        form.addWidget(self.media_edit, 4, 1)
        btn_media = QPushButton("Browse…")
        btn_media.clicked.connect(self._browse_media)
        form.addWidget(btn_media, 4, 2)

        form.addWidget(_secondary("Format"), 5, 0)
        form.addWidget(QLabel("Broadcast WAV · 48 kHz · 24-bit PCM · Stereo"), 5, 1, 1, 2)
        form.setColumnStretch(1, 1)
        lay.addLayout(form)
        lay.addStretch(1)

        buttons = QHBoxLayout()
        self.btn_export_sel = QPushButton("Export Selected")
        self.btn_export_all = QPushButton("Export All")
        self.btn_export_all.setObjectName("Primary")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_export_sel.clicked.connect(lambda: self._start_export(selected_only=True))
        self.btn_export_all.clicked.connect(lambda: self._start_export(selected_only=False))
        self.btn_cancel.clicked.connect(self._cancel_export)
        buttons.addWidget(self.btn_cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_export_sel)
        buttons.addWidget(self.btn_export_all)
        lay.addLayout(buttons)

        self.overall_label = _secondary("Overall")
        lay.addWidget(self.overall_label)
        self.overall_bar = QProgressBar()
        self.overall_bar.setMaximum(1000)
        self.overall_bar.setTextVisible(False)
        lay.addWidget(self.overall_bar)
        self.file_label = _secondary("Current file")
        lay.addWidget(self.file_label)
        self.file_bar = QProgressBar()
        self.file_bar.setMaximum(1000)
        self.file_bar.setTextVisible(False)
        lay.addWidget(self.file_bar)
        return frame

    # --- settings -----------------------------------------------------------

    def _load_settings(self):
        q = self.qsettings
        self.out_edit.setText(q.value("output_dir", "", str))
        self.suffix_edit.setText(q.value("suffix", DEFAULT_SUFFIX, str))
        self.media_edit.setText(q.value("media_folder", "", str))
        method = q.value("match_method", MatchMethod.NUMBER.value, str)
        self.match_combo.setCurrentIndex(1 if method == MatchMethod.NAME.value else 0)
        self.auto_mix_check.setChecked(q.value("auto_mix", False, bool))
        policy = q.value("overwrite", OverwritePolicy.SKIP.value, str)
        for i in range(self.overwrite_combo.count()):
            if self.overwrite_combo.itemData(i) == policy:
                self.overwrite_combo.setCurrentIndex(i)
        self._sync_settings()

    def _save_settings(self):
        q = self.qsettings
        q.setValue("output_dir", self.settings.output_dir)
        q.setValue("suffix", self.settings.suffix)
        q.setValue("media_folder", self.media_edit.text().strip())
        q.setValue("match_method", self.match_combo.currentData())
        q.setValue("overwrite", self.settings.overwrite.value)
        q.setValue("auto_mix", self.settings.auto_mix)

    def _sync_settings(self):
        s = self.settings
        s.output_dir = self.out_edit.text().strip()
        s.suffix = self.suffix_edit.text()
        s.overwrite = OverwritePolicy(self.overwrite_combo.currentData())
        media = self.media_edit.text().strip()
        s.media_folders = [media] if media else []
        s.auto_mix = self.auto_mix_check.isChecked()

    def _on_settings_changed(self, *_):
        if self._loading_settings:
            return
        self._sync_settings()
        self._save_settings()
        self._run_preflight()

    def _on_auto_mix_toggled(self, checked: bool):
        if self._loading_settings:
            return
        self.status.setText("Auto-detect on: each file's stereo mix track is found automatically." if checked
                            else "Auto-detect off: the batch mapping (Left/Right) is used.")
        self._on_settings_changed()

    def _on_media_folder_changed(self):
        self._media_index = None
        self._on_settings_changed()

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Output Folder", self.out_edit.text() or str(Path.home()))
        if path:
            self.out_edit.setText(path)
            self._on_settings_changed()

    def _browse_media(self):
        path = QFileDialog.getExistingDirectory(self, "Media Search Folder", self.media_edit.text() or str(Path.home()))
        if path:
            self.media_edit.setText(path)
            self._on_media_folder_changed()

    # --- queue management -----------------------------------------------------

    def _busy(self) -> bool:
        return self._export_worker is not None

    def _add_files(self):
        start = self.qsettings.value("last_input_dir", str(Path.home()), str)
        paths, _ = QFileDialog.getOpenFileNames(self, "Add AAF Files", start, "AAF files (*.aaf);;All files (*)")
        if paths:
            self.qsettings.setValue("last_input_dir", str(Path(paths[0]).parent))
            self.add_paths(paths)

    def _add_folder(self):
        start = self.qsettings.value("last_input_dir", str(Path.home()), str)
        folder = QFileDialog.getExistingDirectory(
            self, "Add Folder of AAF Files (subfolders included)", start)
        if folder:
            self.qsettings.setValue("last_input_dir", folder)
            self.add_paths([folder])

    def add_paths(self, paths):
        if self._busy():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = find_aaf_files(paths)
        finally:
            QApplication.restoreOverrideCursor()
        known = {os.path.normcase(os.path.abspath(j.path)) for j in self.jobs}
        new_jobs = []
        for p in found:
            key = os.path.normcase(os.path.abspath(p))
            if key in known:
                continue
            known.add(key)
            new_jobs.append(Job(str(Path(p).resolve())))
        if not new_jobs:
            self.status.setText("No new .aaf files found." if not found else
                                f"All {len(found)} .aaf file(s) found are already in the list.")
            return
        folders = len({os.path.dirname(j.path) for j in new_jobs})
        skipped = len(found) - len(new_jobs)
        self._added_note = (f"Added {len(new_jobs)} AAF file(s) from {folders} folder(s)"
                            + (f"; {skipped} already in the list" if skipped else ""))
        self.status.setText(self._added_note + ".")
        self.jobs.extend(new_jobs)
        self._pending_inspect.extend(new_jobs)
        self._refresh_files()
        if self.file_table.currentRow() < 0 and self.jobs:
            self.file_table.selectRow(0)
        self._start_inspection()

    def _start_inspection(self):
        if self._inspect_worker is not None or not self._pending_inspect:
            return
        batch, self._pending_inspect = self._pending_inspect, []
        note, self._added_note = getattr(self, "_added_note", ""), ""
        self.status.setText((note + " — " if note else "") + f"inspecting {len(batch)} file(s)…")
        worker = InspectWorker(batch)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.inspected.connect(self._on_inspected)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._on_inspection_finished)
        self._inspect_worker = worker
        self._inspect_thread = thread
        self._update_buttons()
        thread.start()

    def _on_inspected(self, job: Job, inspection):
        if job not in self.jobs:
            return
        job.inspection = inspection
        job.sequence_index = 0 if len(inspection.sequences) == 1 else None
        job.state = JobState.READY
        log.info("inspected %s: %s", job.filename,
                 inspection.error or f"{len(inspection.sequences)} sequence(s)")
        self._preset_mapping_from(job)
        self._run_preflight(refresh_tracks=False)
        if self._selected_job() is job:
            self._show_tracks()

    def _on_inspection_finished(self):
        # Wait for the thread to stop before releasing the worker: deleting a
        # QObject whose thread is still running corrupts the heap.
        self._inspect_thread.wait()
        self._inspect_worker = None
        self._inspect_thread = None
        if self._pending_inspect:
            self._start_inspection()
        else:
            self._run_preflight()
            self._update_buttons()

    def _preset_mapping_from(self, job: Job):
        """If no batch mapping exists yet, default to the first two tracks of the first file."""
        if self.settings.left or self.settings.right:
            return
        seq = job.sequence
        if seq is None:
            return
        sources = [(t, ch) for t in seq.tracks for ch in range(t.channels)]
        if len(sources) < 2:
            return
        method = MatchMethod(self.match_combo.currentData())
        try:
            self.settings.left = self._selector_for(*sources[0], method)
            self.settings.right = self._selector_for(*sources[1], method)
        except ValueError:
            self.settings.left = self.settings.right = None

    def _remove_selected(self):
        if self._busy():
            return
        rows = sorted({i.row() for i in self.file_table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.jobs):
                job = self.jobs.pop(r)
                if job in self._pending_inspect:
                    self._pending_inspect.remove(job)
        self._run_preflight()

    def _clear(self):
        if self._busy() or not self.jobs:
            return
        self.jobs.clear()
        self._pending_inspect.clear()
        if self._inspect_worker:
            self._inspect_worker.cancel.set()
        self._run_preflight()

    # --- selection & tracks -------------------------------------------------

    def _selected_job(self) -> Job | None:
        row = self.file_table.currentRow()
        if 0 <= row < len(self.jobs):
            return self.jobs[row]
        return None

    def _on_file_selection(self):
        self._show_tracks()
        self._update_preview()
        self._update_buttons()

    def _show_tracks(self):
        job = self._selected_job()
        self.track_table.setRowCount(0)
        self.left_combo.clear()
        self.right_combo.clear()
        self.seq_combo.blockSignals(True)
        self.seq_combo.clear()
        self.seq_combo.blockSignals(False)
        if job is None:
            self.track_title.setText("Tracks")
            self.tc_label.setText("—")
            return
        self.track_title.setText(f"Tracks — {job.filename}")
        insp = job.inspection
        if insp is None:
            self.tc_label.setText("inspecting…")
            return
        if insp.error:
            self.tc_label.setText(insp.error)
            return
        self.seq_combo.blockSignals(True)
        if job.sequence_index is None:
            self.seq_combo.addItem("Choose a sequence…", None)
        for i, seq in enumerate(insp.sequences):
            self.seq_combo.addItem(f"{seq.name}  ({seq.duration_label})", i)
        if job.sequence_index is not None:
            self.seq_combo.setCurrentIndex(job.sequence_index)
        self.seq_combo.setEnabled(len(insp.sequences) > 1 and not self._busy())
        self.seq_combo.blockSignals(False)

        seq = job.sequence
        tc = job.timecode
        if tc:
            self.tc_label.setText(f"{tc.display}" + ("  (manual)" if tc.manual else ""))
        elif seq is not None:
            self.tc_label.setText(f"missing — {seq.timecode_problem}")
        else:
            self.tc_label.setText("—")
        if seq is None:
            return

        index = self._media_index or MediaIndex(self.settings.media_folders)
        for t in seq.tracks:
            r = self.track_table.rowCount()
            self.track_table.insertRow(r)
            label = f"A{t.track_number}" if t.track_number is not None else f"slot {t.slot_id}"
            self.track_table.setItem(r, 0, _item(label))
            self.track_table.setItem(r, 1, _item(t.name or "—"))
            self.track_table.setItem(r, 2, _item(t.format_summary()))
            self.track_table.setItem(r, 3, _item(format_duration(t.duration)))
            if t.errors:
                media_text, color, tip = "Unsupported", style.ERROR, "\n".join(t.errors)
            elif not t.media_refs():
                media_text, color, tip = "Empty track", style.TEXT_SECONDARY, None
            else:
                problems = []
                embedded = all(ref.embedded for ref in t.media_refs())
                if not embedded:
                    for ref in t.media_refs():
                        try:
                            resolve(ref, job.path, index)
                        except MediaError as exc:
                            problems.append(str(exc))
                if problems:
                    media_text, color, tip = "Missing", style.WARNING, "\n".join(problems)
                else:
                    media_text = "Embedded" if embedded else "Linked — found"
                    color, tip = style.ACCENT, None
            it = _item(media_text, tip)
            it.setForeground(QColor(color))
            self.track_table.setItem(r, 4, it)
            if t.warnings:
                self.track_table.item(r, 1).setToolTip("\n".join(t.warnings))
            for ch in range(t.channels):
                text = t.channel_label(ch) + (f" \u2014 {t.name}" if t.name else "")
                if t.channels == 2:
                    text += "  (stereo L)" if ch == 0 else "  (stereo R)"
                self.left_combo.addItem(text, f"{t.slot_id}:{ch}")
                self.right_combo.addItem(text, f"{t.slot_id}:{ch}")
        for combo, track, ch in ((self.left_combo, job.left_track, job.left_channel),
                                 (self.right_combo, job.right_track, job.right_channel)):
            combo.setCurrentIndex(combo.findData(f"{track.slot_id}:{ch}") if track is not None else -1)

    def _on_sequence_changed(self, _index):
        job = self._selected_job()
        if job is None or self._busy():
            return
        value = self.seq_combo.currentData()
        if value is None:
            return
        job.sequence_index = int(value)
        job.override_left = job.override_right = None
        job.state = JobState.READY
        self._run_preflight()

    def _set_timecode(self):
        job = self._selected_job()
        if job is None or job.sequence is None:
            return
        dlg = TimecodeDialog(self, job.timecode)
        if dlg.exec() == QDialog.Accepted and dlg.value:
            job.timecode_override = dlg.value
            if job.state == JobState.COMPLETED:
                job.state = JobState.READY
            log.info("manual timecode for %s: %s", job.filename, dlg.value.display)
            self._run_preflight()

    def _clear_timecode(self):
        job = self._selected_job()
        if job is None:
            return
        job.timecode_override = None
        self._run_preflight()

    def _selector_for(self, track, channel: int, method: MatchMethod) -> TrackSelector:
        ch = channel if track.channels > 1 else None
        if method == MatchMethod.NUMBER:
            if track.track_number is None:
                raise ValueError(f"{track.label} has no track number; match by name instead")
            return TrackSelector(method, track.track_number, ch)
        if not track.name:
            raise ValueError(f"{track.label} has no name in the AAF; match by track number instead")
        return TrackSelector(method, track.name, ch)

    @staticmethod
    def _combo_source(combo, seq):
        """(track, channel) chosen in a left/right combo, or None."""
        data = combo.currentData() if combo.currentIndex() >= 0 else None
        if not data:
            return None
        slot, ch = (int(x) for x in str(data).split(":"))
        track = seq.track_by_slot(slot)
        return (track, ch) if track is not None else None

    def _chosen_tracks(self):
        job = self._selected_job()
        if job is None or job.sequence is None:
            return None, None, None
        seq = job.sequence
        return job, self._combo_source(self.left_combo, seq), self._combo_source(self.right_combo, seq)

    def _on_left_chosen(self, _index):
        """Picking channel 1 of a stereo track as Left proposes channel 2 as Right."""
        job = self._selected_job()
        if job is None or job.sequence is None:
            return
        src = self._combo_source(self.left_combo, job.sequence)
        if src and src[0].channels == 2 and src[1] == 0:
            idx = self.right_combo.findData(f"{src[0].slot_id}:1")
            if idx >= 0:
                self.right_combo.setCurrentIndex(idx)

    def _apply_to_all(self):
        job, left, right = self._chosen_tracks()
        if job is None or left is None or right is None:
            self.status.setText("Select a file and choose a left and a right track first.")
            return
        method = MatchMethod(self.match_combo.currentData())
        try:
            self.settings.left = self._selector_for(*left, method)
            self.settings.right = self._selector_for(*right, method)
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        cleared = sum(1 for j in self.jobs if j.has_override)
        for j in self.jobs:
            j.override_left = j.override_right = None
        msg = f"Batch mapping: Left {self.settings.left.label}, Right {self.settings.right.label} applied to all files."
        if cleared:
            msg += f" {cleared} per-file override(s) cleared."
        self.status.setText(msg)
        log.info(msg)
        self._run_preflight()

    def _override_file(self):
        job, left, right = self._chosen_tracks()
        if job is None or left is None or right is None:
            self.status.setText("Choose a left and a right track for this file first.")
            return
        job.override_left = ChannelRef(left[0].slot_id, left[1])
        job.override_right = ChannelRef(right[0].slot_id, right[1])
        if job.state == JobState.COMPLETED:
            job.state = JobState.READY
        left_label, right_label = left[0].channel_label(left[1]), right[0].channel_label(right[1])
        self.status.setText(f"{job.filename}: override Left {left_label}, Right {right_label}.")
        log.info("override %s: left %s right %s", job.filename, job.override_left, job.override_right)
        self._run_preflight()

    def _revert_override(self):
        job = self._selected_job()
        if job is None:
            return
        job.override_left = job.override_right = None
        self._run_preflight()

    def _on_match_method_changed(self, _i):
        if self._loading_settings:
            return
        # Re-express the current batch mapping with the new method using the selected file's tracks.
        job = self._selected_job()
        method = MatchMethod(self.match_combo.currentData())
        if job and job.sequence and self.settings.left and self.settings.right:
            try:
                left = match_track(job.sequence, self.settings.left)
                right = match_track(job.sequence, self.settings.right)
                self.settings.left = self._selector_for(*left, method)
                self.settings.right = self._selector_for(*right, method)
            except (PreflightIssue, ValueError) as exc:
                self.status.setText(f"Could not convert the batch mapping: {exc}")
        self._save_settings()
        self._run_preflight()

    # --- preflight & display ---------------------------------------------------

    def _run_preflight(self, refresh_tracks: bool = True):
        if self._busy():
            return
        self._sync_settings()
        if self._media_index is None:
            self._media_index = MediaIndex(self.settings.media_folders)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            preflight(self.jobs, self.settings, self._media_index)
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_files()
        if refresh_tracks:
            self._show_tracks()
        self._update_mapping_label()
        self._update_preview()
        self._update_buttons()

    def _refresh_all(self):
        self._refresh_files()
        self._show_tracks()
        self._update_mapping_label()
        self._update_preview()
        self._update_buttons()

    def _refresh_files(self):
        current = self.file_table.currentRow()
        selected_rows = {i.row() for i in self.file_table.selectedIndexes()}
        self.file_table.blockSignals(True)
        self.file_table.setRowCount(len(self.jobs))
        for r, job in enumerate(self.jobs):
            self._fill_row(r, job)
        if self.jobs:
            row = min(max(current, 0), len(self.jobs) - 1)
            self.file_table.setCurrentCell(row, 0)
            for r in selected_rows:
                if r < len(self.jobs) and r != row:
                    self.file_table.selectRow(r)
        self.file_table.blockSignals(False)
        counts = {}
        for j in self.jobs:
            counts[j.state.value] = counts.get(j.state.value, 0) + 1
        parts = [f"{n} {k.lower()}" for k, n in counts.items()]
        self.queue_summary.setText(f"{len(self.jobs)} file(s)" + (": " + ", ".join(parts) if parts else ""))

    def _fill_row(self, r: int, job: Job):
        seq = job.sequence
        tc = job.timecode
        insp = job.inspection
        seq_text = seq.name if seq else ("choose…" if insp and len(insp.sequences) > 1 else "—")
        left = job.left_label or "—"
        right = job.right_label or "—"
        if job.has_override:
            left += " *"
            right += " *"
        elif job.selection == "auto-detected":
            left += " (auto)"
            right += " (auto)"
        cells = [
            job.filename,
            seq_text,
            (tc.label + (" (manual)" if tc.manual else "")) if tc else "—",
            seq.duration_label if seq else "—",
            left,
            right,
            job.status_text,
        ]
        tip = "\n".join([job.path] + job.messages + [f"warning: {w}" for w in job.warnings])
        for c, text in enumerate(cells):
            it = _item(text, tip)
            if c == 6:
                it.setForeground(QColor(style.STATE_COLORS.get(job.state.value, style.TEXT)))
            self.file_table.setItem(r, c, it)

    def _update_mapping_label(self):
        s = self.settings
        overrides = sum(1 for j in self.jobs if j.has_override)
        if s.auto_mix:
            text = "Track selection: auto-detect the stereo mix track in each file"
            if overrides:
                text += f" \u00b7 {overrides} file(s) overridden (marked *)"
            self.mapping_label.setText(text)
        elif s.left and s.right:
            how = "track number" if s.left.method == MatchMethod.NUMBER else "track name"
            text = f"Batch mapping: Left {s.left.label} · Right {s.right.label}  (matched by {how})"
            if overrides:
                text += f" · {overrides} file(s) overridden (marked *)"
            self.mapping_label.setText(text)
        else:
            self.mapping_label.setText("Batch mapping: not set — choose tracks and click Apply to All Files")

    def _update_preview(self, *_):
        job = self._selected_job()
        suffix = self.suffix_edit.text()
        sample = job.path if job else "501.aaf"
        name = output_name(sample, suffix)
        self.preview.setText(f"{Path(sample).name}  →  {name}")

    def _update_buttons(self):
        busy = self._busy()
        inspecting = self._inspect_worker is not None
        has_jobs = bool(self.jobs)
        job = self._selected_job()
        for w in (self.btn_add, self.btn_add_folder):
            w.setEnabled(not busy)
        self.btn_remove.setEnabled(not busy and has_jobs)
        self.btn_clear.setEnabled(not busy and has_jobs)
        editable = not busy and job is not None and job.sequence is not None
        for w in (self.btn_apply_all, self.btn_override, self.left_combo, self.right_combo, self.btn_tc,
                  self.match_combo):
            w.setEnabled(editable)
        auto = self.auto_mix_check.isChecked()
        self.btn_apply_all.setEnabled(editable and not auto)
        self.match_combo.setEnabled(editable and not auto)
        self.btn_revert.setText("Revert to Auto-detect" if auto else "Revert to Batch Mapping")
        self.auto_mix_check.setEnabled(not busy)
        self.btn_revert.setEnabled(editable and job.has_override)
        self.btn_tc_clear.setEnabled(editable and job.timecode_override is not None)
        ready = any(j.state == JobState.READY for j in self.jobs)
        self.btn_export_all.setEnabled(not busy and not inspecting and ready)
        self.btn_export_sel.setEnabled(not busy and not inspecting and job is not None)
        self.btn_cancel.setEnabled(busy)
        for w in (self.out_edit, self.suffix_edit, self.overwrite_combo, self.media_edit):
            w.setEnabled(not busy)

    # --- export -------------------------------------------------------------

    def _start_export(self, selected_only: bool):
        if self._busy() or self._inspect_worker is not None:
            return
        self._run_preflight()
        if not self.settings.output_dir:
            QMessageBox.information(self, APP_NAME, "Choose an output folder first.")
            return
        if selected_only:
            rows = sorted({i.row() for i in self.file_table.selectedIndexes()})
            jobs = [self.jobs[r] for r in rows if r < len(self.jobs)]
        else:
            jobs = list(self.jobs)
        ready = [j for j in jobs if j.state == JobState.READY]
        if not ready:
            QMessageBox.information(self, APP_NAME, "None of the chosen files is Ready. "
                                    "Check the Status column for what needs attention.")
            return
        not_ready = [j for j in jobs if j.state not in (JobState.READY, JobState.COMPLETED)]
        if not_ready:
            answer = QMessageBox.question(
                self, APP_NAME,
                f"{len(ready)} file(s) are ready. {len(not_ready)} file(s) need attention or are unsupported "
                "and will be skipped.\n\nExport the ready files now?")
            if answer != QMessageBox.Yes:
                return
        try:
            Path(self.settings.output_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Cannot create the output folder:\n{exc}")
            return

        self._export_count = len(ready)
        self._export_done = 0
        worker = ExportWorker(jobs, list(self.jobs), self.settings)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.job_started.connect(self._on_job_started)
        worker.job_progress.connect(self._on_job_progress)
        worker.job_done.connect(self._on_job_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._on_export_finished)
        self._export_worker = worker
        self._export_thread = thread
        self.overall_bar.setValue(0)
        self.file_bar.setValue(0)
        self.status.setText(f"Exporting {len(ready)} file(s)…")
        self._update_buttons()
        thread.start()

    def _cancel_export(self):
        if self._export_worker:
            self._export_worker.cancel.set()
            self.status.setText("Cancelling… the current file will be removed; completed files are kept.")
            self.btn_cancel.setEnabled(False)

    def _on_job_started(self, job: Job, index: int, count: int):
        self.file_label.setText(f"Current file: {job.filename} ({index + 1} of {count})")
        self.file_bar.setValue(0)
        self._refresh_files()

    def _on_job_progress(self, job: Job, done: int, total: int):
        frac = done / total if total else 1.0
        self.file_bar.setValue(int(frac * 1000))
        if self._export_count:
            self.overall_bar.setValue(int((self._export_done + frac) / self._export_count * 1000))

    def _on_job_done(self, result):
        self._export_done += 1
        if self._export_count:
            self.overall_bar.setValue(int(self._export_done / self._export_count * 1000))
        self._refresh_files()

    def _on_export_finished(self, result: BatchResult):
        self._export_thread.wait()
        self._export_worker = None
        self._export_thread = None
        self.file_label.setText("Current file")
        self.file_bar.setValue(0)
        self._run_preflight()
        if not result.results:
            self.status.setText("Export stopped unexpectedly; see the log / diagnostic report.")
            return
        summary = result.summary()
        self.status.setText(summary + (" (cancelled)" if result.cancelled else ""))
        self._show_report(result)

    def _show_report(self, result: BatchResult):
        failed = [r for r in result.results if r.result == "Failed"]
        lines = [
            f"Total AAF files: {len(result.results)}",
            f"Exported: {result.count(RESULT_COMPLETED)}",
            f"Failed: {result.count('Failed')}",
            f"Skipped: {result.count('Skipped')}",
        ]
        if result.count("Cancelled"):
            lines.append(f"Cancelled / not started: {result.count('Cancelled')}")
        lines += [f"Elapsed: {format_duration(result.elapsed)}", f"Output folder: {result.output_dir}"]
        if result.report_path:
            lines.append(f"Report: {Path(result.report_path).name}")
        if failed:
            lines.append("")
            lines.append("Failed files:")
            lines.extend(f"  {r.job.filename}: {r.message}" for r in failed[:10])
            if len(failed) > 10:
                lines.append(f"  …and {len(failed) - 10} more (see report)")
        box = QMessageBox(self)
        box.setWindowTitle("Export Cancelled" if result.cancelled else "Export Complete")
        box.setText("\n".join(lines))
        open_btn = box.addButton("Open Output Folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is open_btn and result.output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(result.output_dir))

    # --- diagnostics ---------------------------------------------------------

    def _save_diagnostics(self):
        start = self.settings.output_dir or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(self, "Save Diagnostic Report",
                                              str(Path(start) / "AAF_Extractor_Diagnostics.txt"),
                                              "Text files (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(diagnostic_report(self.jobs, self.settings), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not save the report:\n{exc}")
            return
        self.status.setText(f"Diagnostic report saved: {path}")

    # --- drag & drop / close ------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self._busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self.add_paths(paths)

    def stop_workers(self):
        """Cancel background work and wait for the threads to finish.

        A QThread destroyed while running aborts the process, so this must run
        before the window goes away. Waiting is bounded: inspection stops after
        the file being read, export within one render block (and removes its
        incomplete output file).
        """
        for worker, thread in ((self._export_worker, getattr(self, "_export_thread", None)),
                               (self._inspect_worker, getattr(self, "_inspect_thread", None))):
            if worker is not None:
                worker.cancel.set()
            if thread is not None:
                thread.quit()
                thread.wait()

    def closeEvent(self, event):
        if self._busy():
            answer = QMessageBox.question(self, APP_NAME, "An export is running. Cancel it and quit?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.hide()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.stop_workers()
        finally:
            QApplication.restoreOverrideCursor()
        self._save_settings()
        event.accept()
