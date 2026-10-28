"""Background workers so parsing and rendering never block the window."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..aaf.inspector import inspect_aaf
from ..batch.models import BatchSettings, Job
from ..batch.runner import BatchResult, JobResult, run_batch

log = logging.getLogger(__name__)


class InspectWorker(QObject):
    inspected = Signal(object, object)   # Job, AAFInspection
    finished = Signal()

    def __init__(self, jobs: list[Job]):
        super().__init__()
        self.jobs = jobs
        self.cancel = threading.Event()

    @Slot()
    def run(self):
        try:
            for job in self.jobs:
                if self.cancel.is_set():
                    break
                self.inspected.emit(job, inspect_aaf(job.path))
        finally:
            self.finished.emit()


class ExportWorker(QObject):
    job_started = Signal(object, int, int)   # Job, index, count
    job_progress = Signal(object, int, int)  # Job, done frames, total frames
    job_done = Signal(object)                # JobResult
    finished = Signal(object)                # BatchResult

    def __init__(self, jobs: list[Job], all_jobs: list[Job], settings: BatchSettings):
        super().__init__()
        self.jobs = jobs
        self.all_jobs = all_jobs
        self.settings = settings
        self.cancel = threading.Event()
        self._last_pct: dict[int, int] = {}

    def _progress(self, job: Job, done: int, total: int):
        pct = int(done * 1000 / total) if total else 1000
        if self._last_pct.get(id(job)) != pct:
            self._last_pct[id(job)] = pct
            self.job_progress.emit(job, done, total)

    @Slot()
    def run(self):
        result = BatchResult()
        try:
            result = run_batch(self.jobs, self.settings, self.cancel,
                               on_job_start=lambda j, i, n: self.job_started.emit(j, i, n),
                               on_progress=self._progress,
                               on_job_done=lambda r: self.job_done.emit(r),
                               all_jobs=self.all_jobs)
        except Exception:
            log.exception("batch export crashed")
        finally:
            self.finished.emit(result)
