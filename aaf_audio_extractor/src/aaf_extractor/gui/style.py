"""Palette, fonts and Qt style sheet."""

from __future__ import annotations

import logging

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

from ..appinfo import resource_dir

BACKGROUND = "#1B1B1E"
SURFACE = "#242427"
SURFACE_RAISED = "#2D2D31"
BORDER = "#36363B"
ACCENT = "#9DFF24"
TEXT = "#F2F1EC"
TEXT_SECONDARY = "#AAAAB0"
WARNING = "#FFB547"
ERROR = "#FF6B5E"

STATE_COLORS = {
    "Ready": ACCENT,
    "Completed": ACCENT,
    "Needs attention": WARNING,
    "Unsupported": ERROR,
    "Failed": ERROR,
    "Skipped": TEXT_SECONDARY,
    "Inspecting": TEXT_SECONDARY,
    "Exporting": TEXT,
}

log = logging.getLogger(__name__)


def load_fonts() -> str:
    """Register bundled Inter (SIL OFL) and return the family to use."""
    family = None
    fonts = resource_dir() / "fonts"
    for path in sorted(fonts.glob("Inter-*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0 and family is None:
            fams = QFontDatabase.applicationFontFamilies(fid)
            family = fams[0] if fams else None
    if family is None:
        log.info("Inter not available; falling back to the system UI font")
        family = "Segoe UI"
    return family


def apply_palette(app):
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BACKGROUND))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor("#28282B"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE_RAISED))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor("#3A4A26"))
    pal.setColor(QPalette.HighlightedText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_SECONDARY))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE_RAISED))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#6C6C72"))
    app.setPalette(pal)


def style_sheet(family: str) -> str:
    return f"""
* {{ font-family: "{family}", "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QWidget {{ color: {TEXT}; }}
QLabel#Title {{ font-size: 13pt; font-weight: 600; }}
QLabel#Version, QLabel.secondary, QLabel[secondary="true"] {{ color: {TEXT_SECONDARY}; }}
QLabel#SectionTitle {{ font-weight: 600; font-size: 10pt; color: {TEXT}; padding: 0 0 2px 0; }}
QLabel#Preview {{ color: {ACCENT}; }}
QFrame#Panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}
QPushButton {{
    background: {SURFACE_RAISED}; border: 1px solid {BORDER}; border-radius: 4px;
    padding: 5px 12px; min-height: 18px;
}}
QPushButton:hover {{ border-color: #4A4A50; background: #333338; }}
QPushButton:pressed {{ background: #28282C; }}
QPushButton:disabled {{ color: #6C6C72; background: {SURFACE}; border-color: #2E2E33; }}
QPushButton#Primary {{ background: {ACCENT}; color: #111113; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #B2FF55; }}
QPushButton#Primary:disabled {{ background: #3B4A2A; color: #7D8A6E; border-color: #3B4A2A; }}
QLineEdit, QComboBox {{
    background: {BACKGROUND}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 6px;
    selection-background-color: #3A4A26;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE_RAISED}; border: 1px solid {BORDER}; }}
QTableWidget {{
    background: {SURFACE}; alternate-background-color: #28282B; border: 1px solid {BORDER};
    border-radius: 4px; gridline-color: transparent;
}}
QTableWidget::item {{ padding: 2px 6px; }}
QTableWidget::item:selected {{ background: #34402A; color: {TEXT}; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_SECONDARY}; border: none; border-bottom: 1px solid {BORDER};
    padding: 4px 6px; font-weight: 500;
}}
QProgressBar {{
    background: {BACKGROUND}; border: 1px solid {BORDER}; border-radius: 3px; height: 8px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QSplitter::handle {{ background: {BACKGROUND}; }}
QScrollBar:vertical {{ background: {SURFACE}; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3E3E44; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 2px solid {SURFACE}; border-radius: 6px; }}
QToolTip {{ background: {SURFACE_RAISED}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


def make_font(family: str, point_size: float = 10, weight=QFont.Normal) -> QFont:
    f = QFont(family)
    f.setPointSizeF(point_size)
    f.setWeight(weight)
    return f
