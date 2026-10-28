"""Generate resources/app.ico (and app.png) from simple vector shapes.

Run with the project virtual environment: python tools/make_icon.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

OUT = Path(__file__).resolve().parents[1] / "resources"
BARS = [0.35, 0.7, 1.0, 0.55, 0.85, 0.4]


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#242427"))
    r = size * 0.18
    p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
    p.setBrush(QColor("#9DFF24"))
    margin = size * 0.2
    width = (size - 2 * margin) / (len(BARS) * 1.6)
    gap = width * 0.6
    for i, h in enumerate(BARS):
        bh = (size - 2 * margin) * h
        x = margin + i * (width + gap)
        y = (size - bh) / 2
        p.drawRoundedRect(QRectF(x, y, width, bh), width / 2, width / 2)
    p.end()
    return img


def main():
    QGuiApplication(sys.argv)
    OUT.mkdir(exist_ok=True)
    draw(256).save(str(OUT / "app.png"))
    if not draw(256).save(str(OUT / "app.ico")):
        print("ICO writer unavailable; only app.png written")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
