"""Vercel entry point: every /api/* call arrives here as /api/index?op=<name>."""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _core import dispatch  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _do(self, method: str) -> None:
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except ValueError:
            body = {}
        status, ctype, payload = dispatch(method, q.get("op", ""), q, body)
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._do("GET")

    def do_POST(self) -> None:
        self._do("POST")

    def log_message(self, *args) -> None:
        pass
