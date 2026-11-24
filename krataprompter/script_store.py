"""Keep current and historical UTF-8 Markdown scripts and remember the last one used."""

from hashlib import sha256
import logging
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile
from threading import Lock


MAX_SCRIPT_BYTES = 2 * 1024 * 1024


class ScriptError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def script_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value.endswith(".md")
        or value.startswith(".")
        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f\ud800-\udfff]', value)
        or len(value.encode("utf-8")) > 240
    ):
        raise ScriptError(400, "Choose a Markdown filename without path separators or special characters.")
    return value


def atomic_write(path: Path, data: bytes) -> None:
    # Use the same filesystem so readers always see a complete script.
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sync_directory(path: Path) -> None:
    if hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class ScriptStore:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory = directory
        self.previous_path = directory / ".previous"
        self.lock = Lock()

    def _read(self, name: str) -> dict:
        path = self.directory / name
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise FileNotFoundError
            with path.open("rb") as source:
                data = source.read(MAX_SCRIPT_BYTES + 1)
        except FileNotFoundError as exc:
            raise ScriptError(404, "That script is no longer on the server.") from exc
        if len(data) > MAX_SCRIPT_BYTES:
            raise ScriptError(413, "The server script exceeds 2 MiB.")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScriptError(422, "The server script is invalid UTF-8.") from exc
        return {"name": name, "content": content, "revision": sha256(data).hexdigest()}

    def _remember(self, name: str) -> bool:
        try:
            atomic_write(self.previous_path, name.encode("utf-8"))
        except OSError:
            logging.exception("Could not record the previous KråtaPrompter script")
            return False
        return True

    def _archive(self, name: str, revision: str, data: bytes) -> None:
        revisions = self.directory / ".revisions"
        history = revisions / name
        archived = history / f"{revision}.md"
        try:
            for directory in (revisions, history):
                directory.mkdir(mode=0o700, exist_ok=True)
                if not stat.S_ISDIR(directory.lstat().st_mode):
                    raise OSError("Revision path is not a directory")

            if archived.exists() or archived.is_symlink():
                if not stat.S_ISREG(archived.lstat().st_mode):
                    raise OSError("Archived revision is not a regular file")
                with archived.open("rb") as existing:
                    if existing.read(len(data) + 1) != data:
                        raise OSError("Archived revision contents do not match")
            else:
                atomic_write(archived, data)
            # Persist the archive and its directory entries before replacing the active script.
            for directory in (history, revisions, self.directory):
                sync_directory(directory)
        except OSError as exc:
            raise ScriptError(500, "Could not archive the previous revision. The current script is intact.") from exc

    def list(self) -> list[str]:
        with self.lock:
            names = []
            for path in self.directory.glob("*.md"):
                try:
                    script_name(path.name)
                    if stat.S_ISREG(path.lstat().st_mode):
                        names.append(path.name)
                except (ScriptError, FileNotFoundError):
                    continue
            return sorted(names, key=str.casefold)

    def previous(self) -> dict | None:
        with self.lock:
            try:
                if not stat.S_ISREG(self.previous_path.lstat().st_mode):
                    return None
                with self.previous_path.open("rb") as pointer:
                    name = script_name(pointer.read(241).decode("utf-8"))
            except (FileNotFoundError, UnicodeDecodeError, ScriptError):
                return None
            try:
                return self._read(name)
            except ScriptError as exc:
                if exc.status == 404:
                    return None
                raise

    def open(self, name: object) -> dict:
        name = script_name(name)
        with self.lock:
            script = self._read(name)
            return {**script, "remembered": self._remember(name)}

    def save(self, name: object, content: object, revision: object) -> dict:
        name = script_name(name)
        if not isinstance(content, str):
            raise ScriptError(400, "A Markdown manuscript is required.")
        try:
            data = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ScriptError(400, "The manuscript is invalid UTF-8.") from exc
        if len(data) > MAX_SCRIPT_BYTES:
            raise ScriptError(413, "The server script exceeds 2 MiB.")
        if revision is not None and (
            not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision)
        ):
            raise ScriptError(400, "The script revision is invalid.")

        path = self.directory / name
        new_revision = sha256(data).hexdigest()
        with self.lock:
            if revision is None:
                if path.exists() or path.is_symlink():
                    raise ScriptError(409, "That name already exists. Use Save As with a different name.")
            else:
                try:
                    current = self._read(name)
                except ScriptError as exc:
                    if exc.status != 404:
                        raise
                    current = None
                if current is None or current["revision"] != revision:
                    raise ScriptError(409, "The server copy changed. Use Save As or reopen it.")
                if revision != new_revision:
                    self._archive(name, revision, current["content"].encode("utf-8"))
            if revision != new_revision:
                atomic_write(path, data)
            return {"name": name, "revision": new_revision, "remembered": self._remember(name)}
