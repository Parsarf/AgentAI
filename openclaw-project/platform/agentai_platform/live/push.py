"""Push gateway: a small server, separate from the web app, that tells an open Lumina tab what changed about the customer's tasks as it happens.

  GET /v1/push?t=<ticket>&focus=<task id>&after=<cursor>&rev=<list rev>&frev=<task rev>          text/event-stream

Why it exists: the web app is one synchronous worker, so it can never hold a connection open, and a tab that asks it "anything new?" every second competes
with every other request on the site. This server holds the connection instead (one thread per open tab, a few small reads a second) and the web app only
mints a ticket for it once a minute.

What it sends is STATE, computed by the same code the web app's fallback route uses (work.WorkReader), so a tab that streams and a tab that polls can never
disagree:

  event: list    the account's tasks and what needs the customer (sent when its rev differs from the one the tab has)
  event: task    the focused task's view plus the timeline rows touched since the tab's cursor
  event: draft   the reply being written right now, as text is produced (never stored; replaced by the saved message when it lands)
  event: reopen  the window is over: connect again with a fresh ticket and the cursors you hold
  event: bye     the account can no longer be read (suspended, removed): stop

Recovery is by cursor, not by replay: every connection states what the tab already has (`rev`, `frev`, `after`), and the first thing it gets is whatever
differs. A dropped connection therefore loses nothing; at worst the tab is a moment late. The window is short (45 s) on purpose: a ticket is only minted for a
signed-in session, so signing out or revoking sessions ends the stream within one window plus one ticket lifetime, with no session lookups here.

Privacy: a ticket names one account and one member; every read authorises that member against the database again. The server reads the task tables and
nothing else, never writes, and keeps nothing between connections. The draft is the visible reply text only, of the focused task's own run.
"""
from __future__ import annotations
import json
import os
import re
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..security import Forbidden, NotFound, Principal
from ..work import WorkReader
from .ticket import TicketError, verify_work

PATH = re.compile(r'^(?:/v1)?/push$')
TASK_ID = re.compile(r'^[a-f0-9]{32}$')
WINDOW_SECONDS = 45
TICK_SECONDS = 0.25
RECHECK_SECONDS = 5              # things that change with time alone (a permission prompt expiring) are picked up at least this often
HEARTBEAT_SECONDS = 10
MAX_PER_ACCOUNT = 6              # open tabs of one customer
MAX_STREAMS = 96                 # a single small server: beyond this, tabs are told to poll instead
DRAFT_PHASES = ('working', 'starting', 'needs_you')


def sse(event: str, data: dict) -> bytes:
    return f'event: {event}\ndata: {json.dumps(data, separators=(",", ":"))}\n\n'.encode()


class PushGateway:
    def __init__(self, store, secret: bytes, *, draft=None, clock=time.time, monotonic=time.monotonic, sleep=time.sleep, window=WINDOW_SECONDS, tick=TICK_SECONDS):
        self.store, self.secret, self.reader = store, secret, WorkReader(store, clock=clock)
        self.draft = draft                       # callable(account_id, after_seq, wait_ms) -> {'seq', 'runId', 'itemId', 'text', 'done'} | {'seq'} | None; None = no draft streaming
        self.clock, self.monotonic, self.sleep, self.window, self.tick = clock, monotonic, sleep, window, tick
        self._open, self._guard = {}, threading.Lock()

    # -- admission ------------------------------------------------------------------------------------------------------------------------------
    def admit(self, ticket: str):
        """-> Principal, or None when the ticket is not good. Counts the stream; `release` gives the place back."""
        try:
            account, actor = verify_work(self.secret, ticket, now=self.clock)
        except TicketError:
            return None
        with self._guard:
            if self._open.get(account, 0) >= MAX_PER_ACCOUNT or sum(self._open.values()) >= MAX_STREAMS:
                return False
            self._open[account] = self._open.get(account, 0) + 1
        return Principal(account, actor, 'customer')

    def release(self, principal):
        with self._guard:
            left = self._open.get(principal.account_id, 1) - 1
            if left > 0:
                self._open[principal.account_id] = left
            else:
                self._open.pop(principal.account_id, None)

    # -- one stream -----------------------------------------------------------------------------------------------------------------------------
    def _version(self, con):
        """SQLite's own "another connection committed something" counter: one cheap read that says whether anything at all may have changed."""
        try:
            return con.execute('PRAGMA data_version').fetchone()[0]
        except sqlite3.Error:
            return None

    def stream(self, principal, *, focus='', after=0, rev='', frev=''):
        """Yields SSE frames until the window ends. The caller has admitted `principal` and releases it afterwards."""
        focus = focus if TASK_ID.fullmatch(focus or '') else ''
        deadline = self.monotonic() + self.window
        watch = sqlite3.connect(Path(self.store.path).absolute().as_uri() + '?mode=ro', uri=True, timeout=2, isolation_level=None, check_same_thread=False)
        seen, checked, beat = object(), 0.0, self.monotonic()
        draft_seq, sent = 0, {'item': None, 'len': 0, 'done': True}
        focus_phase = None
        try:
            yield sse('hello', {'window': self.window, 'draft': self.draft is not None})
            if self.draft is not None and focus:
                try:
                    draft_seq = int((self.draft(principal.account_id, 0, 0) or {}).get('seq') or 0)      # start from now: a reply written before this tab opened is already a saved message
                except Exception:
                    draft_seq = 0
            while self.monotonic() < deadline:
                version = self._version(watch)
                if version != seen or self.monotonic() - checked >= RECHECK_SECONDS:
                    seen, checked = version, self.monotonic()
                    try:
                        listing = self.reader.listing(principal)
                        detail = self.reader.detail(principal, focus, after=after) if focus else None
                    except NotFound:
                        if focus:                                  # the focused task is not this account's (or is gone): keep the list, drop the focus
                            focus, detail = '', None
                            try:
                                listing = self.reader.listing(principal)
                            except (NotFound, Forbidden):
                                yield sse('bye', {'reason': 'closed'})
                                return
                        else:
                            yield sse('bye', {'reason': 'closed'})
                            return
                    except Forbidden:
                        yield sse('bye', {'reason': 'closed'})
                        return
                    except sqlite3.Error:
                        listing = detail = None                    # the database was busy for a moment: try again next tick
                    if listing is not None and listing['rev'] != rev:
                        rev = listing['rev']
                        yield sse('list', listing)
                        beat = self.monotonic()
                    if detail is not None:
                        focus_phase = detail['task']['phase']
                        if detail['task']['rev'] != frev or detail['rows']:
                            frev, after = detail['task']['rev'], detail['cursor']
                            yield sse('task', detail)
                            beat = self.monotonic()
                if self.monotonic() - beat >= HEARTBEAT_SECONDS:
                    beat = self.monotonic()
                    yield b': hb\n\n'
                if self.draft is not None and focus and focus_phase in DRAFT_PHASES:
                    frame = self._draft(principal.account_id, focus, draft_seq, sent)
                    if frame is not None:
                        draft_seq = frame.pop('_seq')
                        if frame:
                            yield sse('draft', frame)
                            beat = self.monotonic()
                        continue                                   # the wait for new text was the tick
                self.sleep(self.tick)
            yield sse('reopen', {'rev': rev, 'frev': frev, 'after': after})
        finally:
            watch.close()

    def _draft(self, account, focus, after_seq, sent):
        """Ask the cell's relay for reply text newer than `after_seq`, holding the question for one tick. -> {'_seq', ...frame} ({'_seq'} alone: nothing to send), or None when
        the cell could not be asked (the caller sleeps the tick itself)."""
        try:
            got = self.draft(account, after_seq, int(self.tick * 1000))
        except Exception:
            return None
        if not isinstance(got, dict) or not isinstance(got.get('seq'), int):
            return None
        out = {'_seq': got['seq']}
        text, run, item = got.get('text'), got.get('runId'), got.get('itemId')
        if got['seq'] <= after_seq or not isinstance(text, str) or not isinstance(run, str) or not isinstance(item, str):
            return out
        if not re.fullmatch(re.escape(focus) + r'-a\d{1,4}', run):      # only the focused task's own run (its id is derived from the task's): never another task's words
            return out
        same = sent['item'] == item and sent['len'] <= len(text)
        start = sent['len'] if same else 0
        sent.update(item=item, len=len(text), done=bool(got.get('done')))
        if same and start == len(text) and not got.get('done'):
            return out
        out.update(task=focus, item=item, at=start, add=text[start:], done=bool(got.get('done')))
        return out


def make_server(gateway: PushGateway, host: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'push'
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):                                  # no request lines in logs: the query holds a ticket
            pass

        def _plain(self, status, headers=None):
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()

        def do_GET(self):
            if len(self.path) > 900:
                return self._plain(414)
            url = urlsplit(self.path)
            if not PATH.fullmatch(url.path):
                return self._plain(404)
            q = parse_qs(url.query)
            one = lambda name: q.get(name, [''])[0][:600]
            principal = gateway.admit(one('t'))
            if principal is None:
                return self._plain(403)
            if principal is False:
                return self._plain(429, {'Retry-After': '20'})
            try:
                after = one('after')
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Accel-Buffering', 'no')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                for frame in gateway.stream(principal, focus=one('focus'), after=int(after) if after.isdigit() and len(after) < 10 else 0, rev=one('rev')[:32], frev=one('frev')[:32]):
                    self.wfile.write(frame)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                pass                                                   # the tab went away
            finally:
                gateway.release(principal)

        do_HEAD = do_POST = do_PUT = do_DELETE = lambda self: self._plain(405, {'Allow': 'GET'})

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 64

    return Server((host, port), Handler)


def main():
    """`python -m agentai_platform.live.push`: PUSH_DB (the platform database), a secret (PUSH_SECRET_FILE or AGENTAI_LIVE_SECRET, the one the web app mints with),
    and optionally the cell bridge socket for reply drafts."""
    from ..store import Store
    database = os.environ.get('PUSH_DB')
    secret_file = os.environ.get('PUSH_SECRET_FILE') or os.environ.get('LIVE_SECRET_FILE')
    secret = (Path(secret_file).read_bytes().strip() if secret_file else os.environ.get('AGENTAI_LIVE_SECRET', '').encode())
    if not database or len(secret) < 32:
        sys.exit('PUSH_DB and a secret of at least 32 bytes (PUSH_SECRET_FILE, LIVE_SECRET_FILE or AGENTAI_LIVE_SECRET) are required')
    draft = None
    bridge = os.environ.get('AGENTAI_CELL_BRIDGE_SOCKET')
    if bridge and os.environ.get('PUSH_DRAFTS', '1') != '0':
        from ..bridge_client import BridgeRpc
        from ..lifecycle.cell_bridge import BRIDGE_ERROR

        def draft(account, after, wait_ms):
            got = BridgeRpc(account, bridge, timeout=10)('chat.draft', {'after': after, 'waitMs': wait_ms})
            return None if BRIDGE_ERROR in got else got
    server = make_server(PushGateway(Store(database), secret, draft=draft), os.environ.get('PUSH_HOST', '127.0.0.1'), int(os.environ.get('PUSH_PORT', '18803')))
    print(f'push gateway on {server.server_address}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
