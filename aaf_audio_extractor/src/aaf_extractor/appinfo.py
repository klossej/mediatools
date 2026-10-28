"""Resource locations, log setup and diagnostic reports.

Works both from source and from a PyInstaller bundle (``sys._MEIPASS``).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__

LOG_FILE_NAME = "aaf_audio_extractor.log"


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "resources"
    return Path(__file__).resolve().parents[2] / "resources"


def user_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / APP_NAME


def log_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging(level: int = logging.INFO) -> Path | None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if sys.stderr is not None:  # windowed PyInstaller builds have no console
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(fmt)
        root.addHandler(console)
    try:
        path = log_dir() / LOG_FILE_NAME
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    except OSError:
        return None
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(fmt)
    root.addHandler(handler)
    logging.getLogger(__name__).info("%s %s starting (Python %s, %s)", APP_NAME, __version__,
                                     platform.python_version(), platform.platform())
    return path


def diagnostic_report(jobs, settings, log_tail_lines: int = 400) -> str:
    """Plain-text report describing every queued file, for support investigations."""
    lines = [
        f"{APP_NAME} {__version__} diagnostic report",
        f"Created: {datetime.now().isoformat(timespec='seconds')}",
        f"System: {platform.platform()} / Python {platform.python_version()}",
        "",
        "Settings",
        f"  Output folder: {settings.output_dir or '(not set)'}",
        f"  Suffix: {settings.suffix}",
        f"  Left: {settings.left.label + ' (by ' + settings.left.method.value + ')' if settings.left else '(not set)'}",
        f"  Right: {settings.right.label + ' (by ' + settings.right.method.value + ')' if settings.right else '(not set)'}",
        f"  Auto-detect stereo mix track: {'on' if settings.auto_mix else 'off'}",
        f"  Existing files: {settings.overwrite.value}",
        f"  Media search folders: {', '.join(settings.media_folders) or '(none)'}",
        "",
    ]
    for job in jobs:
        lines.append("=" * 78)
        lines.append(f"{job.filename}   [{job.state.value}]")
        lines.append(f"  Path: {job.path}")
        for m in job.messages:
            lines.append(f"  Message: {m}")
        for w in job.warnings:
            lines.append(f"  Warning: {w}")
        insp = job.inspection
        if insp is None:
            lines.append("  (not inspected)")
            continue
        if insp.error:
            lines.append(f"  Inspection error: {insp.error}")
        for w in insp.warnings:
            lines.append(f"  Inspection warning: {w}")
        for n, seq in enumerate(insp.sequences):
            chosen = " (selected)" if seq is job.sequence else ""
            lines.append(f"  Sequence {n + 1}{chosen}: '{seq.name}' [{seq.mob_id}] top-level={seq.toplevel}")
            lines.append(f"    Edit rate {seq.edit_rate}, duration {seq.duration_label}")
            tc = seq.timecode
            lines.append(f"    Record timecode: {tc.display + ' (frame ' + str(tc.start_frames) + ', ' + tc.source + ')' if tc else 'none - ' + str(seq.timecode_problem)}")
            for w in seq.warnings:
                lines.append(f"    Warning: {w}")
            for t in seq.tracks:
                lines.append(f"    Track {t.label}: slot {t.slot_id}, {t.channels} ch, edit rate {t.edit_rate}, length {t.length}, "
                             f"{len(t.segments)} components, format {t.format_summary()}")
                for e in t.errors:
                    lines.append(f"      ERROR: {e}")
                for w in t.warnings:
                    lines.append(f"      warning: {w}")
                for ref in t.media_refs():
                    where = "embedded" if ref.embedded else ("locators: " + ", ".join(ref.locators) if ref.locators else "no location")
                    lines.append(f"      media '{ref.mob_name}' {ref.mob_id} {ref.descriptor} ch{ref.channel_index + 1} {where}"
                                 + (f" PROBLEM: {ref.problem}" if ref.problem else ""))
        if job.timecode_override:
            lines.append(f"  Manual timecode override: {job.timecode_override.display}")
        if job.has_override:
            lines.append(f"  Per-file track override: left slot {job.override_left}, right slot {job.override_right}")
        if job.diagnostics:
            lines.append("  Export plan:")
            lines.extend("    " + d for d in job.diagnostics)
        if job.exported_path:
            lines.append(f"  Exported: {job.exported_path} ({job.exported_frames} samples, TimeReference {job.time_reference})")
    lines.append("")
    lines.append("=" * 78)
    lines.append("Recent log")
    try:
        log_path = log_dir() / LOG_FILE_NAME
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            tail = fh.readlines()[-log_tail_lines:]
        lines.extend(l.rstrip("\n") for l in tail)
    except OSError:
        lines.append("(log file unavailable)")
    return "\n".join(lines) + "\n"
