from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable


BASE_DIR = Path(__file__).parent


class StudyServer:
    def __init__(self, on_start: Callable[[int, str], None]):
        self.on_start = on_start

        handler = self._make_handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 8000), handler)

        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    def _make_handler(self):
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:
                # Keep the terminal output clean.
                return

            def send_json(self, status: int, data: dict) -> None:
                body = json.dumps(data).encode("utf-8")

                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/" or self.path == "/start_page.html":
                    self.serve_file(
                        BASE_DIR / "start_page.html",
                        "text/html; charset=utf-8",
                    )
                    return

                if self.path == "/static/style.css":
                    self.serve_file(BASE_DIR / "static/style.css", "text/css")
                    return

                if self.path == "/static/script.js":
                    self.serve_file(
                        BASE_DIR / "static/script.js",
                        "application/javascript",
                    )
                    return

                self.send_error(404)

            def serve_file(self, path: Path, content_type: str) -> None:
                try:
                    body = path.read_bytes()
                except FileNotFoundError:
                    self.send_error(404)
                    return

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                if self.path != "/start-study":
                    self.send_json(404, {"error": "Not found"})
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(length)
                    data = json.loads(body)

                    participant_id = int(data["participant_id"])
                    mode = str(data["mode"])

                    if participant_id < 1:
                        raise ValueError("Participant ID must be positive.")

                    if mode not in {"A", "B", "C1", "C2"}:
                        mode = ""

                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    self.send_json(
                        400,
                        {"error": "Ungültige Teilnehmer-ID oder Agent-Modus."},
                    )
                    return

                parent.on_start(participant_id, mode)
                self.send_json(200, {"ok": True})

        return Handler

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
