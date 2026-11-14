"""The hands, on the cell's own native browser: the same commands the retired Playwright runner answered (open / snapshot / act / xy / view / probe / screenshot / close), answered
over the cell bridge's `browser.request` instead. The loop, the code rules, takeover, the pictures and the Live view are unchanged; only who moves the mouse changed.

Everything here is deterministic and model-free. The page-side logic (what is on the page, which element, is it covered) is the runner's own, run through the browser's evaluate by
NAME (native_scripts.py): the bridge never accepts a script a caller wrote. Nothing customer-visible is logged here; the trace records commands and outcomes only.
"""
from __future__ import annotations
import base64
import hashlib
import ipaddress
import os
import queue
import re
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

BRIDGE_ERROR = '__error__'
KEYS = ('Enter', 'Tab', 'Escape')
TAKEOVER_KEYS = ('Backspace', 'Delete', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageDown', 'PageUp')    # what the customer's own keyboard may send; no shortcuts
MAX_VALUE = 500
MAX_URL = 2048
MAX_PAGES = 3
WIDTH, HEIGHT = 1280, 800
LIVE = {'watch_seconds': 6, 'wait_ms': 2000}


class NativeError(Exception):
    pass


def private_ip(host: str) -> bool:
    """An address (not a name) in a private, loopback, link-local or otherwise internal range."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved or ip.is_multicast or (ip.version == 4 and ip in ipaddress.ip_network('100.64.0.0/10')))


def url_allowed(raw, allow_loopback=False, allow_private=False) -> bool:
    if not isinstance(raw, str) or not 0 < len(raw) <= MAX_URL or any(ord(c) < 33 for c in raw):
        return False
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or '').lower()
        parts.port
    except ValueError:
        return False
    if parts.scheme not in ('http', 'https') or not host or parts.username or parts.password:
        return False
    if allow_private:
        return True                                              # the account switched `ssrf_guard` off (the cell's network firewall still applies)
    if host in ('localhost', '127.0.0.1', '::1'):
        return allow_loopback                                    # tests only; a real run never sets it
    if host.endswith(('.local', '.internal', '.localhost')):
        return False
    return not private_ip(host)


class NativeRunner:
    def __init__(self, call, out_dir, *, sleep=time.sleep, allow_loopback=False, allow_private=False, tabs=None, clock=time.monotonic):
        """call(method, params) -> dict: the bridge for this account (BridgeRpc). A refusal or a browser error comes back under '__error__'.
        tabs: the account's AccountTabs (tabs.py) when several tasks of the customer share this browser; alone, a runner has one of its own."""
        from .tabs import AccountTabs
        self.call, self.out, self.sleep, self.allow_loopback, self.allow_private = call, Path(out_dir), sleep, allow_loopback, allow_private
        self.tabs_of = tabs or AccountTabs()
        self.shots, self.lock, self.tab, self.clock = 0, self.tabs_of.lock, None, clock       # one lock for the whole account: tasks take their steps in turn
        self.pages = []            # this task's own tabs, oldest first (a click may open a popup); `tab` is the one it is looking at
        self.url, self.resume_url, self.reopened, self.last_used = '', None, False, 0.0
        self.tabs_of.join(self)

    @property
    def started(self):
        return self.tabs_of.started

    @started.setter
    def started(self, value):
        self.tabs_of.started = bool(value)

    @property
    def known(self):
        return set(self.pages)

    # ------------------------------------------------------------------ the browser, by request
    def bridge(self, method, params):
        """One bridge call. A bridge that is down, slow or refuses is a failed command, never a crash of the job."""
        try:
            return self.call(method, params)
        except Exception as exc:
            raise NativeError(type(exc).__name__) from exc

    def req(self, verb, path, body=None):
        params = {'method': verb, 'path': path}
        if path in ('/act', '/navigate') and self.tab:
            body = {**(body or {}), 'targetId': self.tab}          # the command names this task's tab; a bridge that does not pass it on still acts on the right one, because the tab was brought to the front first
        if body is not None:
            params['body'] = body
        reply = self.bridge('browser.request', params)
        if reply.get(BRIDGE_ERROR):
            raise NativeError(str(reply[BRIDGE_ERROR]))
        return reply

    def ev(self, script, args=None):
        return self.req('POST', '/act', {'kind': 'evaluate', 'script': script, 'args': args or {}}).get('result')

    def tabs(self):
        return [t for t in (self.req('GET', '/tabs').get('tabs') or []) if t.get('type', 'page') == 'page']

    def ensure(self):
        """The browser is up with a window of the size every picture and point is judged against."""
        if self.started:
            return
        self.req('POST', '/start')
        for stray in self.tabs():                                 # tabs the profile restored belong to no task: closed, so every tab that exists is somebody's (the sign-ins are in the profile, not in a tab)
            try:
                self.req('POST', '/tabs/close', {'targetId': stray['targetId']})
            except NativeError:
                pass
        self.tabs_of.started, self.tabs_of.front = True, None

    def _open_tab(self, url):
        """A tab of this task's own at `url`, made room for first. The tab that appears is this task's: steps are taken in turn, so nobody else opened it."""
        self.tabs_of.make_room(self)
        before = self.tabs_of.owned()
        self.req('POST', '/tabs/open', {'url': url})
        fresh = [t['targetId'] for t in self.tabs() if t['targetId'] not in before]
        if not fresh:
            raise NativeError('no tab')
        self.pages, self.tab = self.pages + fresh[-1:], fresh[-1]
        self.tabs_of.front = self.tab
        try:
            self.req('POST', '/act', {'kind': 'resize', 'width': WIDTH, 'height': HEIGHT})
        except NativeError:
            pass

    def unload(self):
        """Another task needs the room: this task's tabs are closed and it remembers where it was. Called with the account's lock held, never in the middle of one of its own steps."""
        for page in self.pages:
            try:
                self.req('POST', '/tabs/close', {'targetId': page})
            except NativeError:
                pass
        if self.tabs_of.front in self.pages:
            self.tabs_of.front = None
        self.resume_url = self.url if url_allowed(self.url, self.allow_loopback, self.allow_private) else None
        self.pages, self.tab = [], None

    def _turn(self):
        """This task's step begins: its page is loaded (opened again where it was, if it had been closed to make room) and in front."""
        self.last_used = self.clock()
        if self.tab is None and self.resume_url:
            self._open_tab(self.resume_url)
            self.resume_url, self.reopened = None, True
            self.settle()
        elif self.tab and self.tabs_of.front != self.tab:
            try:
                self.req('POST', '/tabs/focus', {'targetId': self.tab})
            except NativeError:
                pass
            self.tabs_of.front = self.tab

    def sync_tabs(self):
        """A click can open a tab (a login or payment popup) or close its own: the page the loop looks at is the newest one still open, and no more than MAX_PAGES stay."""
        ids = [t['targetId'] for t in self.tabs()]
        others = self.tabs_of.owned() - set(self.pages)
        fresh = [i for i in ids if i not in others and i not in self.pages]     # appeared during this task's step: its own popup
        mine = [p for p in self.pages if p in ids] + fresh
        for extra in mine[MAX_PAGES:]:
            try:
                self.req('POST', '/tabs/close', {'targetId': extra})
            except NativeError:
                pass
        mine = mine[:MAX_PAGES]
        fresh = [i for i in fresh if i in mine]
        newest = fresh[-1] if fresh else (self.tab if self.tab in mine else (mine[-1] if mine else None))
        if newest and newest != self.tab:
            try:
                self.req('POST', '/tabs/focus', {'targetId': newest})
            except NativeError:
                pass
        self.pages, self.tab = mine, newest
        if newest:
            self.tabs_of.front = newest
        return len(mine)

    def settle(self):
        """Wait for the page to finish loading (bounded); a slow page is fine."""
        for _ in range(20):
            try:
                if (self.ev('viewport') or {}).get('ready') == 'complete':
                    break
            except NativeError:
                break
            self.sleep(0.25)
        self.sleep(0.3)

    def fp(self):
        try:
            return hashlib.sha1(str(self.ev('fingerprint', {'sel': _selector()})).encode()).hexdigest()[:12]
        except NativeError:
            return None

    def info(self):
        v = self.ev('viewport') or {}
        return v.get('url', ''), v.get('title', '')

    def done(self, **extra):
        url, _ = self.info()
        return {'ok': True, 'url': url, 'page_fp': self.fp(), **extra}

    # ------------------------------------------------------------------ commands
    def handle(self, msg):
        with self.lock:
            cmd = msg.get('cmd')
            try:
                if cmd == 'close':
                    return self.close()
                if not hasattr(self, 'cmd_' + str(cmd)):
                    return self._unknown(msg)
                self.ensure()
                if cmd != 'open':
                    if self.tab is None and not self.resume_url:
                        return {'ok': False, 'error': 'action_failed', 'detail': 'no page'}
                    self._turn()
                reply = getattr(self, 'cmd_' + str(cmd), self._unknown)(msg)
                if reply.get('url'):
                    self.url = reply['url']
                self.last_used = self.clock()
                if self.tabs_of.shared and reply.get('ok') and cmd in ('snapshot', 'act', 'xy') and self.watched():
                    self._live_frame()                             # sharing the browser: the one stream would show whichever task is stepping, so a watched task gets a picture of its own tab after each of its steps
                return reply
            except NativeError as exc:
                return {'ok': False, 'error': 'action_failed', 'detail': str(exc)[:80]}

    @staticmethod
    def _unknown(msg):
        return {'ok': False, 'error': 'unknown_command'}

    def cmd_open(self, msg):
        if not url_allowed(msg.get('url'), self.allow_loopback, self.allow_private):
            return {'ok': False, 'error': 'url_blocked'}
        self.last_used = self.clock()
        try:
            if self.tab is None:
                self._open_tab(msg['url'])
                self.resume_url = None
            else:
                self._turn()
                self.req('POST', '/navigate', {'url': msg['url']})
        except NativeError as exc:
            return {'ok': False, 'error': 'navigation_failed', 'detail': str(exc)[:80]}
        self.sync_tabs()
        self.settle()
        url, title = self.info()
        return {'ok': True, 'url': url, 'title': title[:120]}

    def cmd_snapshot(self, msg):
        self.sync_tabs()
        self.settle()
        d = self.ev('describe', {'sel': _selector(), 'max': _max_elements()})
        if not isinstance(d, dict):
            return {'ok': False, 'error': 'action_failed'}
        lines = '\n'.join(f'[{e["ref"]}] <{e["tag"]}{" type=" + e["type"] if e["type"] else ""}> "{e["label"]}"' for e in d['elements'])
        return {'ok': True, 'url': d.get('url', ''), 'title': d.get('title', ''), 'snapshot': lines, 'text': d.get('text', ''), 'pages': len(self.known) or 1, 'elements': d['elements'],
                'page_fp': self.fp(), 'scroll': d.get('scroll'), 'height': d.get('height'), 'window': d.get('window'), 'focus': d.get('focus'), **self._reopened()}

    def _reopened(self):
        if not self.reopened:
            return {}
        self.reopened = False
        return {'reopened': True}

    def watched(self):
        try:
            return time.time() - os.stat(self.out / 'watching').st_mtime < LIVE['watch_seconds']
        except OSError:
            return False

    def _live_frame(self):
        try:
            tmp = self.out / 'live.tmp'
            tmp.write_bytes(self._picture())
            os.replace(tmp, self.out / 'live.jpg')
        except (NativeError, OSError):
            pass

    def _point(self, msg):
        x, y = msg.get('x'), msg.get('y')
        if type(x) not in (int, float) or type(y) not in (int, float) or not (0 <= x <= WIDTH and 0 <= y <= HEIGHT):
            return None
        return x, y

    def _finish(self, before_url, before_pages):
        self.sleep(0.4)
        pages = self.sync_tabs()
        self.settle()
        out = self.done()
        out['navigated'] = out['url'] != before_url
        out['new_tab'] = pages > before_pages
        return out

    def cmd_act(self, msg):
        action, ref, value, expect = msg.get('action'), msg.get('ref'), msg.get('value'), msg.get('expect')
        if action == 'back':
            self.ev('history', {'delta': -1})
            self.sleep(0.4)
            self.settle()
            return self.done()
        if action == 'press':
            if value not in KEYS:
                return {'ok': False, 'error': 'key_not_allowed'}
            self.req('POST', '/act', {'kind': 'press', 'key': value})
            self.settle()
            return self.done()
        if action == 'scroll':
            if value not in (None, 'down', 'up'):
                return {'ok': False, 'error': 'bad_value'}
            moved = self.ev('scroll', {'dy': -700 if value == 'up' else 700, 'x': WIDTH / 2, 'y': HEIGHT / 2}) or {}       # what is under the middle of the window: a popup scrolls before the page behind it
            self.sleep(0.15)
            return self.done(**{k: moved[k] for k in ('moved', 'inner', 'at_end') if k in moved})
        if action == 'wait':
            self.sleep(1)
            self.settle()
            return self.done()
        before_url, before_pages = self.info()[0], len(self.known)
        if action in ('clickat', 'typeat'):                       # a point chosen from a picture: the host has already named what is there (probe) and run its rules on it
            point = self._point(msg)
            if point is None:
                return {'ok': False, 'error': 'bad_coordinates'}
            if action == 'typeat' and (not isinstance(value, str) or not value or len(value) > MAX_VALUE):
                return {'ok': False, 'error': 'bad_value'}
            self.req('POST', '/act', {'kind': 'clickCoords', 'x': point[0], 'y': point[1]})
            if action == 'typeat':
                self.sleep(0.2)
                if not self.ev('focus_active'):
                    return {'ok': False, 'error': 'not_a_field'}
                if not (self.ev('insert_text', {'text': value}) or {}).get('ok'):
                    return {'ok': False, 'error': 'action_failed'}
            self.sleep(0.4)
            return self._finish(before_url, before_pages)
        if action not in ('click', 'type', 'select') or type(ref) is not int:
            return {'ok': False, 'error': 'bad_action'}
        if action in ('type', 'select') and (not isinstance(value, str) or len(value) > MAX_VALUE):
            return {'ok': False, 'error': 'bad_value'}
        found = self.ev('locate', {'ref': ref, 'label': (expect or {}).get('label') if expect else None, 'action': action}) or {}
        if found.get('state') != 'ok':
            return {'ok': False, 'error': found.get('state') or 'stale'}
        if action == 'click':
            self.req('POST', '/act', {'kind': 'clickCoords', 'x': found['x'], 'y': found['y']})
        elif action == 'type':
            result = self.ev('type_into', {'ref': ref, 'value': value}) or {}
            if not result.get('ok'):
                return {'ok': False, 'error': result.get('error') or 'action_failed'}
        else:
            result = self.ev('select_option', {'ref': ref, 'value': value}) or {}
            if not result.get('ok'):
                return {'ok': False, 'error': result.get('error') or 'action_failed'}
        return self._finish(before_url, before_pages)

    def cmd_xy(self, msg):
        """Takeover: coordinates come from the user's own click on the picture; the host has already range-checked them. No waiting for the page to settle: the next input must not queue behind a slow load."""
        action, text = msg.get('action'), msg.get('text')
        if action == 'click':
            point = self._point(msg)
            if point is None:
                return {'ok': False, 'error': 'bad_coordinates'}
            self.req('POST', '/act', {'kind': 'clickCoords', 'x': point[0], 'y': point[1]})
        elif action == 'type':
            if not isinstance(text, str) or len(text) > MAX_VALUE:
                return {'ok': False, 'error': 'bad_value'}
            if not (self.ev('insert_text', {'text': text}) or {}).get('ok'):
                return {'ok': False, 'error': 'action_failed'}
        elif action == 'key':
            if text not in KEYS and text not in TAKEOVER_KEYS:
                return {'ok': False, 'error': 'key_not_allowed'}
            self.req('POST', '/act', {'kind': 'press', 'key': text})
        elif action == 'scroll':
            try:
                up = float(text) <= 0
            except (TypeError, ValueError):
                up = text == 'up'                 # the app sends the words 'up' and 'down'
            self.ev('scroll', {'dy': -500 if up else 500})
        elif action == 'goto':
            if not isinstance(text, str) or len(text) > MAX_URL or not url_allowed(text, self.allow_loopback, self.allow_private):      # the same address rules as every request this browser makes (public http/https only)
                return {'ok': False, 'error': 'url_blocked'}
            self.req('POST', '/navigate', {'url': text})
        elif action in ('back', 'forward', 'reload'):
            self.ev('history', {'delta': {'back': -1, 'forward': 1, 'reload': 0}[action]})
        else:
            return {'ok': False, 'error': 'bad_action'}
        return {'ok': True, 'url': self.info()[0]}

    def _picture(self):
        reply = self.bridge('browser.shot', {'targetId': self.tab} if self.tab else {})
        if reply.get(BRIDGE_ERROR) or not reply.get('data_b64'):
            raise NativeError('no picture')
        return base64.b64decode(reply['data_b64'])

    def cmd_view(self, msg):
        """The window as one JPEG for JEV (base64), optionally kept with the run's pictures."""
        data = self._picture()
        out = {'ok': True, 'data': base64.b64encode(data).decode(), 'width': WIDTH, 'height': HEIGHT, 'view': {'w': WIDTH, 'h': HEIGHT}}
        if msg.get('save'):
            out['file'] = self._keep(data)
        return out

    def cmd_screenshot(self, msg):
        return {'ok': True, 'file': self._keep(self._picture())}

    def _keep(self, data):
        self.shots += 1
        name = f'shot-{self.shots:03d}.jpg'
        (self.out / name).write_bytes(data)
        return name

    def cmd_probe(self, msg):
        point = self._point(msg)
        if point is None:
            return {'ok': False, 'error': 'bad_coordinates'}
        return {'ok': True, 'hit': self.ev('hit_at', {'x': point[0], 'y': point[1]})}

    def close(self):
        """The job is over: the stream stops and the browser is shut down so a sleeping cell holds nothing. The profile (and so the customer's own sign-ins in it) stays on its disk."""
        for page in self.pages:                                  # this task's own tabs only: another task of the customer may be working in the same browser
            try:
                self.req('POST', '/tabs/close', {'targetId': page})
            except Exception:
                pass
        if self.tabs_of.front in self.pages:
            self.tabs_of.front = None
        self.pages, self.tab, self.resume_url = [], None, None
        if self.tabs_of.leave(self):                             # the customer's last browser task: now the browser itself stops
            for call in (lambda: self.bridge('browser.live', {'on': False}), lambda: self.req('POST', '/stop')):
                try:
                    call()
                except Exception:
                    pass
            self.tabs_of.started = False
        return {'ok': True}


def _selector():
    from .native_scripts import SELECTOR
    return SELECTOR


def _max_elements():
    from .native_scripts import MAX_ELEMENTS
    return MAX_ELEMENTS


class NativeTransport:
    """The same surface as ProcessTransport (send / recv / close), so Session and the whole loop are unchanged. Commands run one at a time on a worker thread; a command that takes
    longer than the session's deadline times out exactly as a runner that stopped answering would. While someone watches the Live view the newest frame is kept in live.jpg."""

    def __init__(self, call, out_dir, *, runner=None):
        self.runner = runner or NativeRunner(call, out_dir)
        self.call, self.out = call, Path(out_dir)
        self._jobs, self._replies = queue.Queue(), queue.Queue()
        self.stderr_tail = deque(maxlen=20)
        self.closed = threading.Event()
        threading.Thread(target=self._work, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _work(self):
        while True:
            msg = self._jobs.get()
            if msg is None:
                return
            try:
                reply = self.runner.handle(msg)
            except Exception as exc:                                 # a command must always answer; the loop treats it as a failed step
                self.stderr_tail.append(type(exc).__name__)
                reply = {'ok': False, 'error': 'action_failed'}
            self._replies.put({**reply, 'id': msg.get('id')})
            if msg.get('cmd') == 'close':
                return

    def send(self, obj):
        if self.closed.is_set():
            raise BrokenPipeError('browser closed')
        self._jobs.put(obj)

    def recv(self, timeout):
        try:
            return self._replies.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError('runner did not answer in time') from None

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        self._jobs.put({'id': 0, 'cmd': 'close'})
        self._jobs.put(None)

    # ------------------------------------------------------------------ live view
    def _watched(self):
        try:
            return time.time() - os.stat(self.out / 'watching').st_mtime < LIVE['watch_seconds']
        except OSError:
            return False

    def _watch(self):
        """Frames only while the host has recently touched `watching` (no viewer, no stream, no cost)."""
        streaming, after = False, 0
        tmp, dest = self.out / 'live.tmp', self.out / 'live.jpg'
        while not self.closed.is_set():
            try:
                if self.runner.tabs_of.shared:                  # several tasks in this browser: frames come from each task's own steps (NativeRunner._live_frame), not from the one stream
                    if streaming:
                        self.call('browser.live', {'on': False})
                        streaming = False
                    time.sleep(0.5)
                elif self._watched():
                    if not streaming:
                        self.call('browser.live', {'on': True})
                        streaming, after = True, 0
                    reply = self.call('browser.frame', {'after': after, 'waitMs': LIVE['wait_ms']})
                    if reply.get(BRIDGE_ERROR) or reply.get('on') is False:
                        streaming = False
                        time.sleep(0.5)
                        continue
                    after = reply.get('seq', after)
                    if reply.get('data_b64'):
                        tmp.write_bytes(base64.b64decode(reply['data_b64']))
                        os.replace(tmp, dest)
                else:
                    if streaming:
                        self.call('browser.live', {'on': False})
                        streaming = False
                    time.sleep(0.25)
            except Exception:
                streaming = False
                time.sleep(1)
        if streaming:
            try:
                self.call('browser.live', {'on': False})
            except Exception:
                pass
