"""Serve KråtaPrompter and its local Markdown library with the Python standard library."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path

from script_store import MAX_SCRIPT_BYTES, ScriptError, ScriptStore


APP_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_DATA_DIRECTORY = APP_DIRECTORY.parent / ".krataprompter-data"
DEVELOPMENT_DATA_DIRECTORY = APP_DIRECTORY.parent / ".krataprompter-dev-data"
MAX_REQUEST_BYTES = MAX_SCRIPT_BYTES * 6 + 4096
PUBLIC_FILES = frozenset({
    "/", "/index.html", "/presenter.html", "/style.css", "/app.mjs", "/presenter.mjs",
    "/editor.mjs", "/script.mjs", "/script-file.mjs", "/presentation.mjs", "/transport.mjs",
    "/view.mjs", "/editor-follow.mjs", "/editor-search.mjs",
    "/fonts/inter-latin-variable.woff2", "/fonts/Inter-LICENSE.txt",
})


class AppHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "text/javascript",
        ".woff2": "font/woff2",
    }

    def __init__(self, *args, store: ScriptStore, **kwargs) -> None:
        self.store = store
        super().__init__(*args, directory=APP_DIRECTORY, **kwargs)

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def send_head(self):
        if self.path.partition("?")[0] not in PUBLIC_FILES:
            self.send_error(404)
            return None
        return super().send_head()

    def send_json(self, status: int, value: object) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def run_api(self, operation) -> None:
        try:
            result = operation()
        except ScriptError as exc:
            self.send_json(exc.status, {"error": str(exc)})
        except OSError:
            logging.exception("KråtaPrompter storage operation failed")
            self.send_json(500, {"error": "The server could not access its script folder."})
        else:
            self.send_json(200, result)

    def do_GET(self) -> None:
        if self.path == "/api/scripts":
            self.run_api(lambda: {"scripts": self.store.list()})
        elif self.path == "/api/scripts/previous":
            self.run_api(lambda: {"script": self.store.previous()})
        else:
            super().do_GET()

    def read_json(self) -> dict:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if (
            self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}
            or origin is not None and origin not in {f"http://{host}", f"https://{host}"}
        ):
            raise ScriptError(403, "Open KråtaPrompter from its own server address.")
        if self.headers.get_content_type() != "application/json":
            raise ScriptError(415, "Send an application/json request.")
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise ScriptError(400, "A Content-Length header is required.")
        try:
            length = int(self.headers["Content-Length"])
        except ValueError as exc:
            raise ScriptError(400, "Invalid request length.") from exc
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ScriptError(413, "The request is empty or too large.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise ScriptError(400, "The request must contain a UTF-8 JSON object.") from exc
        if not isinstance(payload, dict):
            raise ScriptError(400, "The request must contain a JSON object.")
        return payload

    def do_POST(self) -> None:
        def open_script():
            payload = self.read_json()
            return self.store.open(payload.get("name"))

        def save_script():
            payload = self.read_json()
            return self.store.save(payload.get("name"), payload.get("content"), payload.get("revision"))

        if self.path == "/api/scripts/open":
            self.run_api(open_script)
        elif self.path == "/api/scripts/save":
            self.run_api(save_script)
        else:
            self.send_error(404)


def resolve_data_directory(override: Path | None, development: bool) -> Path:
    if development:
        directory = DEVELOPMENT_DATA_DIRECTORY.resolve()
        if directory != DEVELOPMENT_DATA_DIRECTORY:
            raise ValueError("The development script folder must not be a symlink.")
        other = DEFAULT_DATA_DIRECTORY.resolve()
    else:
        directory = (override or DEFAULT_DATA_DIRECTORY).resolve()
        other = DEVELOPMENT_DATA_DIRECTORY
    if directory.is_relative_to(other) or other.is_relative_to(directory):
        raise ValueError("The development and server script folders must be separate.")
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, help="HTTP port (default: 25252, or 25253 with --dev)")
    parser.add_argument("--bind", default="127.0.0.1", help="IPv4 address (default: 127.0.0.1)")
    data_options = parser.add_mutually_exclusive_group()
    data_options.add_argument("--data-dir", type=Path,
                              help=f"Script folder (default: {DEFAULT_DATA_DIRECTORY})")
    data_options.add_argument("--dev", action="store_true",
                              help=f"Use the separate development script folder {DEVELOPMENT_DATA_DIRECTORY}")
    args = parser.parse_args()

    try:
        store = ScriptStore(resolve_data_directory(args.data_dir, args.dev))
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot create or open the script folder: {exc}")
    handler = partial(AppHandler, store=store)
    port = args.port if args.port is not None else (25253 if args.dev else 25252)
    with ThreadingHTTPServer((args.bind, port), handler) as server:
        host, port = server.server_address
        print(f"KråtaPrompter listening on http://{host}:{port}/ (port {port})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
