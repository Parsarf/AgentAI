#!/usr/bin/env python3
"""Serve only the verified Phase 4 application assets on local loopback."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

project = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=18795)
args = parser.parse_args()
root = project / "evidence/phase-4/20260926T225237Z/board-snapshot"
for line in (root / ".phase4/dirty-snapshot.sha256").read_text().splitlines():
    expected, name = line.split("  ", 1)
    if name.startswith(".phase4/"):
        continue
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"Preview source differs from native tested snapshot: {name}")

assets = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/src/app.mjs": ("src/app.mjs", "text/javascript; charset=utf-8"),
    "/src/board.mjs": ("src/board.mjs", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(True)

    def do_HEAD(self):
        self.respond(False)

    def respond(self, include_body):
        asset = assets.get(urlsplit(self.path).path)
        if asset is None:
            self.send_error(404)
            return
        name, content_type = asset
        body = (root / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def log_message(self, *_):
        pass


with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
    print(f"Private Phase 4 preview: http://127.0.0.1:{args.port}", flush=True)
    print("Stop with Ctrl+C after completing the Chrome checks.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
