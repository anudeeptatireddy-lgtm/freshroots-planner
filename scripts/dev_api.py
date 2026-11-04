"""Run the web API locally on :8787 (files in outputs/ unless DATABASE_URL is set).  Usage: python scripts/dev_api.py"""
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
from index import handler  # noqa: E402

if __name__ == "__main__":
    print("API on http://127.0.0.1:8787")
    ThreadingHTTPServer(("127.0.0.1", 8787), handler).serve_forever()
