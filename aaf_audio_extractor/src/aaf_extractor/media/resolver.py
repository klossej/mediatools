"""Locate the samples behind a :class:`MediaRef` and open them for reading.

Embedded essence is read from the AAF itself. External media is found from the
descriptor's locator URL; when that path does not exist, the optional search
folders are consulted. MXF files are matched by their source package UMID (the
same MobID the AAF references), never by file name alone. Plain WAV/AIFF files
carry no MobID, so a search-folder match by name must also agree with the
declared sample format and length, and must be unique.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from ..aaf.model import EssenceFormat, MediaRef
from .containers import ContainerError, parse_aiff, parse_wave, scan_mxf_sound_essence, sniff
from .reader import PCMReader, SegmentedFile

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".bwf", ".aif", ".aiff", ".aifc", ".mxf"}


class MediaError(Exception):
    """Media for a clip cannot be used. ``code`` is a short machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ResolvedMedia:
    ref: MediaRef
    location: str                 # "embedded" or a file path
    fmt: EssenceFormat
    runs: list[tuple[int, int]] | None = None   # MXF essence byte runs

    @property
    def frames(self) -> int:
        if self.runs is not None:
            return sum(n for _, n in self.runs) // self.fmt.block_align
        return self.fmt.frames


def url_to_path(url: str) -> str | None:
    """Convert an AAF locator URL into a local path string."""
    url = url.strip()
    if not url:
        return None
    lower = url.lower()
    if lower.startswith("file:"):
        rest = url[5:]
        if rest.startswith("//"):
            rest = rest[2:]
            # file://?/C:/..., file:///C:/..., file://server/share/...
            if rest.startswith("?/"):
                rest = rest[2:]
            elif rest.startswith("/"):
                rest = rest[1:] if len(rest) > 2 and rest[2] in ":|" else rest
            else:
                rest = "//" + rest   # UNC host
        rest = urllib.parse.unquote(rest)
        if len(rest) > 1 and rest[1] == "|":
            rest = rest[0] + ":" + rest[2:]
        if os.name == "nt":
            return str(PureWindowsPath(rest))
        if len(rest) > 1 and rest[1] == ":":
            return rest   # Windows path seen on another OS; keep for basename matching
        return rest if rest.startswith("/") else "/" + rest
    return urllib.parse.unquote(url)


def _basename(path: str) -> str:
    return PureWindowsPath(path).name if ("\\" in path or ":" in path[:3]) else Path(path).name


class MediaIndex:
    """Lazily built, cached index of media files in the search folders.

    One index is shared across a whole batch so each folder is scanned once.
    """

    def __init__(self, folders: list[str] | None = None):
        self.folders = [str(Path(p)) for p in (folders or []) if p]
        self._files: dict[tuple[str, bool], list[Path]] = {}
        self._umids: dict[tuple[str, bool], dict[str, list[Path]]] = {}

    def _scan(self, folder: str, recursive: bool) -> list[Path]:
        key = (folder, recursive)
        if key not in self._files:
            found: list[Path] = []
            if recursive:
                for root, _dirs, names in os.walk(folder):
                    found.extend(Path(root) / n for n in names if Path(n).suffix.lower() in AUDIO_EXTENSIONS)
            elif os.path.isdir(folder):
                found = [p for p in Path(folder).iterdir()
                         if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
            self._files[key] = found
        return self._files[key]

    def _scopes(self, extra: str | None):
        scopes = [(f, True) for f in self.folders]
        if extra and (extra, True) not in scopes:
            scopes.append((str(Path(extra)), False))
        return scopes

    def by_name(self, name: str) -> list[Path]:
        low = name.lower()
        return [p for f in self.folders for p in self._scan(f, True) if p.name.lower() == low]

    def by_mob_id(self, mob_id: str, extra_folder: str | None = None) -> list[Path]:
        hits: set[Path] = set()
        for key in self._scopes(extra_folder):
            if key not in self._umids:
                table: dict[str, list[Path]] = {}
                for p in self._scan(*key):
                    if p.suffix.lower() == ".mxf":
                        for umid in mxf_package_ids(p):
                            table.setdefault(umid, []).append(p)
                self._umids[key] = table
            hits.update(self._umids[key].get(mob_id, []))
        return sorted(hits)


def mxf_package_ids(path: Path) -> list[str]:
    """Return the source/material package MobIDs declared in an MXF header."""
    try:
        from aaf2.mxf import MXFFile
        mxf = MXFFile(str(path))
        return [str(pkg.mob_id) for pkg in mxf.packages()]
    except Exception as exc:
        log.warning("cannot read MXF header %s: %s", path, exc)
        return []


def _open_file_format(path: Path, ref: MediaRef) -> ResolvedMedia:
    size = path.stat().st_size
    with open(path, "rb") as fh:
        kind = sniff(fh)
        try:
            if kind == "wave":
                return ResolvedMedia(ref, str(path), parse_wave(fh, size))
            if kind == "aiff":
                return ResolvedMedia(ref, str(path), parse_aiff(fh, size))
            if kind == "mxf":
                if ref.declared is None:
                    raise MediaError("unsupported", f"{path.name}: AAF does not declare the MXF audio format")
                runs, _etype = scan_mxf_sound_essence(fh, size)
                d = ref.declared
                fmt = EssenceFormat(d.sample_rate, d.channels, d.bits, False, 0, sum(n for _, n in runs))
                return ResolvedMedia(ref, str(path), fmt, runs)
        except ContainerError as exc:
            raise MediaError("unsupported", f"{path.name}: {exc}") from exc
    raise MediaError("unsupported", f"{path.name}: unrecognised media file format")


def _matches_declared(res: ResolvedMedia) -> bool:
    d = res.ref.declared
    if d and (d.sample_rate, d.channels, d.bits) != (res.fmt.sample_rate, res.fmt.channels, res.fmt.bits):
        return False
    if res.ref.length_samples and res.frames != res.ref.length_samples:
        return False
    return True


def resolve(ref: MediaRef, aaf_path: str, index: MediaIndex | None = None) -> ResolvedMedia:
    """Find the media for ``ref`` or raise :class:`MediaError`."""
    if ref.problem:
        raise MediaError("unsupported", ref.problem)
    if ref.embedded:
        if ref.embedded_format is None:
            raise MediaError("unreadable", "embedded essence could not be parsed")
        return ResolvedMedia(ref, "embedded", ref.embedded_format)

    index = index or MediaIndex()
    tried: list[str] = []

    # 1. The locator path itself, or relative to the AAF.
    for url in ref.locators:
        p = url_to_path(url)
        if not p:
            continue
        candidates = [Path(p)]
        if not Path(p).is_absolute():
            candidates.append(Path(aaf_path).parent / p)
        for c in candidates:
            tried.append(str(c))
            if c.is_file():
                res = _open_file_format(c, ref)
                if not _matches_declared(res):
                    raise MediaError("mismatch", f"{c.name}: format or length differs from the AAF description")
                return res

    # 2. MXF by UMID in the search folders and next to the AAF.
    hits = index.by_mob_id(ref.mob_id, str(Path(aaf_path).parent))
    if len(hits) > 1:
        raise MediaError("ambiguous", "several MXF files carry the same media ID: " + ", ".join(h.name for h in hits))
    if hits:
        res = _open_file_format(hits[0], ref)
        if not _matches_declared(res):
            raise MediaError("mismatch", f"{hits[0].name}: format or length differs from the AAF description")
        return res

    # 3. WAV/AIFF by locator file name in the search folders, verified by format.
    for url in ref.locators:
        p = url_to_path(url)
        if not p:
            continue
        name = _basename(p)
        if Path(name).suffix.lower() == ".mxf":
            continue  # MXF must match by UMID
        found = index.by_name(name)
        verified = []
        for c in found:
            try:
                res = _open_file_format(c, ref)
            except MediaError:
                continue
            if _matches_declared(res):
                verified.append(res)
        if len(verified) > 1:
            raise MediaError("ambiguous", f"{name}: several matching files in the media search folder")
        if verified:
            return verified[0]
        if found:
            raise MediaError("mismatch", f"{name}: found in the search folder but its format or length differs from the AAF")

    if not ref.locators:
        raise MediaError("missing", f"media '{ref.mob_name or ref.short_id}' is not embedded and has no file location")
    raise MediaError("missing", f"media '{ref.mob_name or ref.short_id}' not found (looked for {', '.join(tried) or ref.locators[0]})")


def open_reader(res: ResolvedMedia, aaf_file=None) -> PCMReader:
    """Open a sample reader. ``aaf_file`` is an open pyaaf2 file for embedded media."""
    fmt = res.fmt
    if res.location == "embedded":
        if aaf_file is None:
            raise MediaError("unreadable", "embedded essence requires the open AAF file")
        from aaf2.mobid import MobID
        essence = aaf_file.content.essencedata.get(MobID(res.ref.mob_id), None)
        if essence is None:
            raise MediaError("missing", "embedded essence stream disappeared")
        stream = essence.open("r")
        return PCMReader(stream, fmt, res.ref.channel_index, owns_handle=False)
    fh = open(res.location, "rb")
    if res.runs is not None:
        return PCMReader(SegmentedFile(fh, res.runs), fmt, res.ref.channel_index, owns_handle=True)
    return PCMReader(fh, fmt, res.ref.channel_index, owns_handle=True)
