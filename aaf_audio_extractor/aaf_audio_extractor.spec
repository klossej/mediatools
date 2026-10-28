# PyInstaller spec for AAF Audio Extractor (one-folder, windowed build).
# Build with:  .venv\Scripts\pyinstaller --noconfirm --clean aaf_audio_extractor.spec

from pathlib import Path

ROOT = Path(SPECPATH)
APP_NAME = "AAF Audio Extractor"
icon = ROOT / "resources" / "app.ico"

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "resources"), "resources")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtPdf",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=str(icon) if icon.exists() else None,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
