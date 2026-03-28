"""Stdlib HTTP server for the trace explorer."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from openflux.serve._api import handle_request
from openflux.sinks.sqlite import SQLiteSink

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class _Handler(BaseHTTPRequestHandler):
    """Routes requests to API handlers or serves static files."""

    sink: SQLiteSink

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._handle_api()
        else:
            self._handle_static()

    def _handle_api(self) -> None:
        status, body = handle_request(self.path, self.sink)
        payload = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _handle_static(self) -> None:
        # Strip query string, normalize path
        path = self.path.split("?")[0].lstrip("/")

        # Try exact file match first
        file_path = _STATIC_DIR / path if path else None
        if file_path and file_path.is_file() and _is_safe_path(file_path):
            self._serve_file(file_path)
            return

        # SPA fallback: serve index.html for all non-file routes
        index = _STATIC_DIR / "index.html"
        if index.is_file():
            self._serve_file(index)
            return

        self._send_404()

    def _serve_file(self, file_path: Path) -> None:
        content = file_path.read_bytes()
        mime = mimetypes.guess_type(str(file_path))[0]
        content_type = mime or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_404(self) -> None:
        body = b"Not found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence default stderr logging for clean terminal output."""
        return


def _is_safe_path(resolved: Path) -> bool:
    """Prevent directory traversal outside the static root."""
    try:
        resolved.resolve().relative_to(_STATIC_DIR.resolve())
        return True
    except ValueError:
        return False


def create_server(port: int, sink: SQLiteSink) -> HTTPServer:
    """Build an HTTPServer bound to localhost with the given sink."""
    handler = type("Handler", (_Handler,), {"sink": sink})
    return HTTPServer(("127.0.0.1", port), handler)


def run_server(port: int, sink: SQLiteSink) -> None:
    """Start the server and block until Ctrl+C."""
    server = create_server(port, sink)
    print(f"OpenFlux running at http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        sink.close()
