"""Output file naming."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
DEFAULT_SUFFIX = "_MIX"


def sanitize_filename(name: str) -> str:
    """Make ``name`` (without directory) valid on Windows."""
    cleaned = _INVALID.sub("_", name).rstrip(" .")
    if not cleaned:
        cleaned = "untitled"
    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned[:240]


def output_name(aaf_path: str, suffix: str = DEFAULT_SUFFIX) -> str:
    """``501.aaf`` -> ``501_MIX.wav``."""
    stem = Path(aaf_path).stem
    return sanitize_filename(f"{stem}{suffix}") + ".wav"


def numbered_alternative(path: Path, taken: set[str]) -> Path:
    """First ``name_N.wav`` that neither exists nor is already claimed in ``taken`` (lower-case paths)."""
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists() and str(candidate).lower() not in taken:
            return candidate
        n += 1
