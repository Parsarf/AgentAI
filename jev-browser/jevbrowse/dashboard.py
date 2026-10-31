"""A local dashboard for the bare loop: start a run, watch it happen, read what JEV was sent and answered, look at a picture of every page, and open earlier runs.
It only reads the run logs (logs/) that the loop writes anyway, so what it shows is exactly what the log holds.

    .venv/bin/python -m jevbrowse.dashboard          (opens http://127.0.0.1:8766/)
"""
import argparse
import json
import os
import re
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .browser import Browser
from .goal import HERE, load_env, search_words, start_url
from .jev import Jev
from .log import LOGS, RunLog, read
from .loop import run

WEB = HERE / 'web'
RUN_ID = re.compile(r'^\d{8}-\d{6}(-\d+)?$')
SHOT = re.compile(r'^step-\d{3}\.jpg$')
WAITING = ('needs_user', 'password', 'sensitive')           # the run stopped for the user: Chrome stays open for them
HOLD_SECONDS = 600
MAX_BODY = 64_000


class Run:
    def __init__(self, folder, goal, url, texts, steps, visible, jev_factory):
        self.log = RunLog(folder)
        self.id = self.log.path.stem
        self.goal, self.url, self.texts, self.steps, self.visible, self.jev_factory = goal, url, texts, steps, visible, jev_factory
        self.state = 'running'                               # running | waiting | finished
        self.stop_ev, self.close_ev = threading.Event(), threading.Event()

    def execute(self):
        browser = None
        try:
            browser = Browser(headless=not self.visible, log=self.log, shots_dir=self.log.shots_dir)
            status, detail = run(self.goal, self.url, browser, self.jev_factory(self.log), self.texts, steps=self.steps, say=lambda *_: None, log=self.log,
                                 should_stop=self.stop_ev.is_set)
            if status in WAITING and self.visible and not self.stop_ev.is_set():
                self.state = 'waiting'                       # the Chrome window is the user's until they press "Close browser"
                self.close_ev.wait(HOLD_SECONDS)
        except BaseException as exc:                         # the log gets the full story, the dashboard shows it
            self.log.emit('crash', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
            self.log.emit('end', status='error', detail=f'{type(exc).__name__}: {exc}')
        finally:
            if browser is not None:
                browser.close()
            self.state = 'finished'

    def stop(self):
        self.stop_ev.set()
        self.close_ev.set()

    def close_browser(self):
        self.close_ev.set()


class App:
    def __init__(self, folder=LOGS, jev_factory=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.jev_factory = jev_factory
        self.runs = {}
        self.guard = threading.Lock()

    def key(self):
        return os.environ.get('TYPESAFE_API_KEY', '').strip()

    def factory(self):
        if self.jev_factory:
            return self.jev_factory
        key = self.key()
        return lambda log: Jev(key, log=log)

    def active(self):
        return next((r for r in self.runs.values() if r.state != 'finished'), None)

    def start(self, body):
        goal = str(body.get('goal') or '').strip()
        if not 3 <= len(goal) <= 4000:
            raise ValueError('Write what you want done (3 to 4,000 characters).')
        if not (self.key() or self.jev_factory):
            raise ValueError('Put TYPESAFE_API_KEY=... in jev-browser/.env and restart the dashboard.')
        url = str(body.get('url') or '').strip() or start_url(goal)
        if not re.match(r'^https?://', url):
            raise ValueError('Name the site in your request (youngla.com) or fill in the start page.')
        try:
            steps = max(1, min(int(body.get('steps') or 25), 60))
        except (TypeError, ValueError):
            raise ValueError('Steps must be a number.')
        with self.guard:
            if self.active():
                raise RuntimeError('A run is already in progress.')
            run_ = Run(self.folder, goal, url, search_words(goal), steps, body.get('visible', True) is not False, self.factory())
            self.runs[run_.id] = run_
        threading.Thread(target=run_.execute, daemon=True).start()
        return run_

    # ------------------------------------------------------------------ reading logs
    def path(self, run_id):
        return self.folder / f'{run_id}.jsonl'

    def status(self):
        live = self.active()
        return {'key': bool(self.key() or self.jev_factory), 'active': live.id if live else None, 'past': self.past()}

    def past(self):
        out = []
        for p in sorted((p for p in self.folder.glob('*.jsonl') if RUN_ID.match(p.stem)), reverse=True)[:40]:
            rows = read(p)
            start = next((r for r in rows if r['kind'] == 'run_start'), {})
            end = next((r for r in reversed(rows) if r['kind'] == 'end'), None)
            live = self.runs.get(p.stem)
            out.append({'id': p.stem, 'goal': start.get('goal', ''), 'status': 'running' if live and live.state != 'finished' else (end or {}).get('status', 'unfinished'),
                        'steps': sum(r['kind'] == 'act' for r in rows), 'at': p.stat().st_mtime})
        return out

    def snapshot(self, run_id, since):
        path = self.path(run_id)
        if not path.exists():
            return None
        rows = [dict(r, n=i + 1) for i, r in enumerate(read(path))]
        end = next((r for r in reversed(rows) if r['kind'] == 'end'), None)
        live = self.runs.get(run_id)
        state = live.state if live else 'finished'
        return {'id': run_id, 'state': state, 'active': state != 'finished', 'status': (end or {}).get('status') if state != 'running' else None, 'detail': (end or {}).get('detail', ''),
                'rows': rows[since:], 'can_close': state == 'waiting'}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def reply(self, code, body=b'', ctype='application/json'):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            port = self.server.server_address[1]
            if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):        # blocks DNS-rebinding pages from reaching this computer-only server
                self.reply(403, {'error': 'forbidden'}); return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            url = urlsplit(self.path); q = parse_qs(url.query)
            if url.path in ('/', '/index.html'):
                return self.reply(200, (WEB / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/status':
                return self.reply(200, app.status())
            m = re.fullmatch(r'/api/run/(\d{8}-\d{6}(?:-\d+)?)', url.path)
            if m:
                data = app.snapshot(m.group(1), int((q.get('since') or ['0'])[0] or 0))
                return self.reply(200 if data else 404, data or {'error': 'not found'})
            m = re.fullmatch(r'/api/shot/(\d{8}-\d{6}(?:-\d+)?)/(step-\d{3}\.jpg)', url.path)
            if m:
                f = app.folder / m.group(1) / m.group(2)
                return self.reply(200, f.read_bytes(), 'image/jpeg') if f.is_file() else self.reply(404, {'error': 'no picture'})
            self.reply(404, {'error': 'not found'})

        def do_POST(self):
            if not self.allowed():
                return
            if 'application/json' not in (self.headers.get('Content-Type') or ''):
                return self.reply(415, {'error': 'json only'})           # a form post from another website cannot start a run
            n = int(self.headers.get('Content-Length') or 0)
            if n > MAX_BODY:
                return self.reply(413, {'error': 'too large'})
            try:
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self.reply(400, {'error': 'bad json'})
            path = urlsplit(self.path).path
            if path == '/api/run':
                try:
                    return self.reply(200, {'id': app.start(body).id})
                except (ValueError, RuntimeError) as exc:
                    return self.reply(409 if isinstance(exc, RuntimeError) else 400, {'error': str(exc)})
            m = re.fullmatch(r'/api/run/(\d{8}-\d{6}(?:-\d+)?)/(stop|close)', path)
            run_ = app.runs.get(m.group(1)) if m else None
            if run_ is None:
                return self.reply(404, {'error': 'not found'})
            (run_.stop if m.group(2) == 'stop' else run_.close_browser)()
            self.reply(200, {'ok': True})

    return Handler


def serve(app, port):
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    server.daemon_threads = True
    return server


def main():
    ap = argparse.ArgumentParser(prog='jevbrowse.dashboard', description='A local dashboard for the bare loop.')
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--no-open', action='store_true')
    args = ap.parse_args()
    load_env(HERE / '.env')
    app = App()
    server = serve(app, args.port)
    url = f'http://127.0.0.1:{args.port}/'
    print(f'dashboard on {url}  (JEV key {"set" if app.key() else "MISSING: put TYPESAFE_API_KEY in .env"}); Ctrl+C to stop', flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
