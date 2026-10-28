"""Application entry point."""

from __future__ import annotations

import logging
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .appinfo import resource_dir, setup_logging
    from .gui import style
    from .gui.main_window import MainWindow

    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    style.apply_palette(app)
    family = style.load_fonts()
    app.setFont(style.make_font(family, 10))
    app.setStyleSheet(style.style_sheet(family))
    icon_path = resource_dir() / "app.ico"
    if icon_path.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.add_paths(sys.argv[1:])
    try:
        return app.exec()
    finally:
        # Tear Qt down in a fixed order (window and its finished worker threads,
        # then the application) instead of leaving it to garbage collection at
        # interpreter exit, which can crash.
        from PySide6.QtCore import QCoreApplication, QEvent
        window.stop_workers()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        del window
        app.shutdown()
        logging.shutdown()


if __name__ == "__main__":
    sys.exit(main())
