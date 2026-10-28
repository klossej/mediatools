"""Find AAF files in dropped/added files and folders."""

from __future__ import annotations

import os
import re
from pathlib import Path

_DIGITS = re.compile(r"(\d+)")


def natural_key(path: str) -> list:
    """Sort key that orders "LI_9" before "LI_10" (case-insensitive)."""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGITS.split(path)]


def _skip_dir(name: str) -> bool:
    # Hidden and Windows system folders ($RECYCLE.BIN, System Volume Information).
    return name.startswith((".", "$")) or name.lower() == "system volume information"


def find_aaf_files(paths) -> list[str]:
    """Expand files and folders (recursively) into a naturally sorted list of .aaf files.

    Symbolic links to folders are not followed, so link loops cannot hang the scan.
    Files given explicitly keep their position before folder results.
    """
    out: list[str] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            found = []
            for root, dirs, names in os.walk(p, onerror=lambda e: None):
                dirs[:] = [d for d in dirs if not _skip_dir(d)]
                found.extend(os.path.join(root, n) for n in names if n.lower().endswith(".aaf"))
            out.extend(sorted(found, key=lambda f: natural_key(os.path.relpath(f, p))))
        elif p.suffix.lower() == ".aaf" and p.is_file():
            out.append(str(p))
    return out
