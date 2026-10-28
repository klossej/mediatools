"""Entry script for PyInstaller and run.bat."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from aaf_extractor.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
