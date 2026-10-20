"""Frame gateway: a small server, separate from the web app, that serves the newest frame of a running browser task.

  GET /v1/live/<task>/frame?t=<ticket>&after=<seq>&now=<seq>        (also /live/<task>/frame)

Returns the newest frame (200, image/jpeg, X-Seq) as soon as it differs from `after`, or 204 after a short hold when nothing changed.
A client loops on this, so it always shows the latest picture and a slow client simply skips frames; no video connection is held open,
which also makes it work through any HTTP proxy. It never reads the database and never writes anything but the tiny `watching` marker
that tells the browser stage someone is looking (no marker, no screencast, no cost).
Who is deciding (JEV or Claude, from the page's controls or from a picture) rides along as four small headers whenever it changed since the `now` the client last saw:
a change with no new picture is answered at once (204 with the headers) instead of waiting for the hold to end, so the label moves with the picture.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import now as live_now
from .ticket import REQUEST_ID, TicketError, verify

PATH = re.compile(r'^(?:/v1)?/live/([a-f0-9]{32})/frame$')      # /v1/... travels the same proxy route as the rest of the API
HOLD_SECONDS = 2.5
STEP_SECONDS = 0.04
MAX_WAITERS = 12                  # a single small server: more viewers than this get "try again" instead of slowing everyone
MAX_FRAME_BYTES = 3_000_000       # a busy 1280x800 page can pass 1 MB; above this the file is not a screenshot (and a frozen picture is worse than a big one)
MARK_EVERY = 1.0


class FrameGateway:
    def __init__(self, root, secret: bytes, *, clock=time.time, sleep=time.sleep, hold=HOLD_SECONDS, max_waiters=MAX_WAITERS):
        self.root, self.secret, self.clock, self.sleep, self.hold = Path(root), secret, clock, sleep, hold
        self._slots, self._marked, self._lock = threading.BoundedSemaphore(max_waiters), {}, threading.Lock()

    def _mark(self, out_dir: Path, request_id: str):
        now = self.clock()
        with self._lock:
            if now - self._marked.get(request_id, 0) < MARK_EVERY:
                return
            self._marked[request_id] = now
            if len(self._marked) > 256:
                self._marked = {k: v for k, v in self._marked.items() if now - v < 60}
        try:
            (out_dir / 'watching').touch(exist_ok=True)
            os.utime(out_dir / 'watching', None)
        except OSError:
            pass

    @staticmethod
    def _now_headers(out_dir: Path, seen: int):
        """-> headers for a who-is-deciding change the client has not seen, else {}. Only whitelisted codes ever reach a header."""
        info = live_now.read(out_dir)
        if info is None or info['seq'] == seen:
            return {}
        return {'X-Now-Seq': str(info['seq']), 'X-By': info['by'], 'X-Mode': info['mode'], 'X-Note': info['note']}

    def frame(self, request_id: str, ticket: str, after: int, now: int = 0):
        """-> (status, headers, body)"""
        try:
            verify(self.secret, ticket or '', request_id, now=self.clock)
        except TicketError:
            return 403, {}, b''
        out_dir = self.root / request_id / 'out'
        if not out_dir.is_dir():
            return 404, {}, b''
        if not self._slots.acquire(blocking=False):
            return 429, {'Retry-After': '1'}, b''
        try:
            deadline = self.clock() + self.hold
            nowh, now_mtime = {}, None
            while True:
                self._mark(out_dir, request_id)
                try:                                              # now.json is read only when it changed: this loop runs every 40 ms
                    stamp = (out_dir / live_now.FILE).stat().st_mtime_ns
                except OSError:
                    stamp = None
                if stamp != now_mtime:
                    now_mtime, nowh = stamp, self._now_headers(out_dir, now)
                try:
                    stat = (out_dir / 'live.jpg').stat()
                    seq = stat.st_mtime_ns
                except OSError:
                    stat, seq = None, 0
                if stat is not None and seq != after and 0 < stat.st_size <= MAX_FRAME_BYTES:
                    try:
                        body = (out_dir / 'live.jpg').read_bytes()
                    except OSError:
                        body = b''
                    if body:
                        return 200, {'Content-Type': 'image/jpeg', 'X-Seq': str(seq), **nowh}, body
                if nowh:
                    return 204, {'X-Seq': str(after), **nowh}, b''
                if self.clock() >= deadline:
                    return 204, {'X-Seq': str(after)}, b''
                self.sleep(STEP_SECONDS)
        finally:
            self._slots.release()


def make_server(gateway: FrameGateway, host='127.0.0.1', port=18801):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        timeout = 30

        def log_message(self, *args):
            pass

        def _send(self, status, headers, body=b''):
            self.send_response(status)
            for k, v in {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin',
                         'Content-Length': str(len(body)), **headers}.items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            if len(self.path) > 600:
                return self._send(414, {})
            url = urlsplit(self.path)
            m = PATH.fullmatch(url.path)
            if not m:
                return self._send(404, {})
            q = parse_qs(url.query)
            after = q.get('after', ['0'])[0]
            seen = q.get('now', ['0'])[0]
            status, headers, body = gateway.frame(m.group(1), q.get('t', [''])[0], int(after) if after.isdigit() else 0, int(seen) if seen.isdigit() else 0)
            self._send(status, headers, body)

        do_HEAD = do_POST = do_PUT = do_DELETE = lambda self: self._send(405, {'Allow': 'GET'})

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 32

    return Server((host, port), Handler)


def main():
    root = os.environ.get('LIVE_FRAMES_ROOT')
    secret_file = os.environ.get('LIVE_SECRET_FILE')
    secret = (Path(secret_file).read_bytes().strip() if secret_file else os.environ.get('AGENTAI_LIVE_SECRET', '').encode())
    if not root or len(secret) < 32:
        sys.exit('LIVE_FRAMES_ROOT and a secret of at least 32 bytes (AGENTAI_LIVE_SECRET or LIVE_SECRET_FILE) are required')
    server = make_server(FrameGateway(root, secret), os.environ.get('LIVE_HOST', '127.0.0.1'), int(os.environ.get('LIVE_PORT', '18801')))
    print(f'live gateway on {server.server_address}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
