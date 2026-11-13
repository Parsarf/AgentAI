"""Local preview of the task experience on the REAL state code, for looking at it in a browser. Test fixture only: never deployed, accepts no real account.

    cd lumina && npm run build && ../platform/.venv/bin/python tests/preview_work.py            -> http://127.0.0.1:5181/app/tasks
    PREVIEW_PUSH=0 ...                                                                          the same without the push gateway (the app falls back to polling)

What is real: the database schema and every row in it, ChatService (send, messages, cancel), WorkReader (the one derivation of task state), the work tickets, and
PushGateway (the stream the page listens to). What is scripted, HERE ONLY: there is no assistant. A "director" thread plays the part of the request worker and writes
the same rows and events the worker writes (states, tool activity, a permission prompt, a browser hand-over, a verdict), slowly enough to watch. Reply text being written
comes from the director through the same draft hook the gateway uses for a cell.

Chats: live (send a message: the director runs it; "approve" in the message makes it ask for permission, "fail" makes it fail, "browser" makes it hand the browser over),
plus a finished one of every kind. Nothing here is a claim about the real runtime: that is checked by platform/tests/e2e.
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'platform'))
from agentai_platform.budget import BudgetLedger                      # noqa: E402
from agentai_platform.chat import ChatService, FixedRoute             # noqa: E402
from agentai_platform.events import EventService                      # noqa: E402
from agentai_platform.live import ticket as live_ticket               # noqa: E402
from agentai_platform.live.push import PushGateway                    # noqa: E402
from agentai_platform.request_queue import RequestQueue               # noqa: E402
from agentai_platform.security import NotFound, Principal             # noqa: E402
from agentai_platform.store import Store                              # noqa: E402
from agentai_platform.work import WorkReader                          # noqa: E402

DIST = ROOT / 'dist'
SECRET = b'preview-secret-preview-secret-preview-secret'
PUSH = os.environ.get('PREVIEW_PUSH', '1') != '0'
ME = Principal('a', 'actor-a', 'customer')
LIMITS = {'period_start_epoch': int(time.time()) - 1000, 'period_microusd': 10 ** 9, 'daily_microusd': 10 ** 9, 'task_microusd': 5 * 10 ** 6, 'max_queued_tasks': 20}
MIME = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png', '.mp4': 'video/mp4'}


class World:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='lumina-preview-')
        self.store = Store(Path(self.dir) / 's' / 'db.sqlite3')
        self.store.initialize()
        self.events = EventService(self.store)
        self.queue = RequestQueue(self.store)
        self.chat = ChatService(self.store, queue=self.queue, ledger=BudgetLedger(self.store, service_limit_microusd=10 ** 12), pricer=FixedRoute(1_000_000), execution=True, browse=True, events=self.events)
        self.reader = WorkReader(self.store)
        self.draft = {'seq': 0, 'runId': '', 'itemId': '', 'text': '', 'done': True}
        self.draft_changed = threading.Condition()
        self.push = PushGateway(self.store, SECRET, draft=self.read_draft)
        with self.store.connect() as con:
            con.execute("INSERT INTO accounts(id,status) VALUES ('a','active')")
            con.execute("INSERT INTO memberships VALUES ('a','actor-a','customer','active')")
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','d-a',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p-a','P')")
            con.execute("INSERT INTO entitlements VALUES ('a','e-a','preview','trial',?,datetime(?,'unixepoch'))", (json.dumps(LIMITS), int(time.time()) + 10 ** 6))
            con.execute("INSERT INTO mcp_connections(account_id,id,name,url,auth_method,state,created_epoch) VALUES ('a','conn1','Linear','https://mcp.linear.app/mcp','none','connected',?)", (int(time.time()),))
        self.seed()

    # -- small writers (what the request worker and the tools write) ---------------------------------------------------------------------------
    def sql(self, statement, args=()):
        with self.store.connect() as con:
            con.execute(statement, args)

    def conversation(self, cid, title):
        self.sql("INSERT INTO conversations(account_id,project_id,id,deployment_id,title) VALUES ('a','p-a',?,'d-a',?)", (cid, title))

    def say(self, cid, text, provenance='agent', request_id=None):
        self.sql('INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,?,?,?)', ('a', cid, request_id, provenance, text))

    def act(self, rid, ref, status, category, label, detail='', output='', tool='tool'):
        self.events.append('a', rid, 'activity', {'ref': ref, 'status': status, 'category': category, 'label': label, 'detail': detail, 'output': output, 'tool': tool}, 'gateway')

    def state(self, rid, state, **cols):
        sets = ','.join(f'{k}=?' for k in ['state', *cols])
        self.sql(f'UPDATE customer_requests SET {sets} WHERE account_id=? AND id=?', (state, *cols.values(), 'a', rid))

    def finish(self, rid, outcome='completed', verification='not_applicable', note='', state='completed', result=None):
        self.events.append('a', rid, 'result', {'summary': note or 'done', 'outcome': outcome, 'verify_level': verification}, 'worker')
        self.state(rid, state, outcome=outcome, verification=verification, outcome_note=note or None, result=result, closing=1, parked_reason=None)

    def write_draft(self, rid, item, text, done=False):
        with self.draft_changed:
            self.draft = {'seq': self.draft['seq'] + 1, 'runId': f'{rid}-a1', 'itemId': item, 'text': text, 'done': done}
            self.draft_changed.notify_all()

    def read_draft(self, account, after, wait_ms):
        with self.draft_changed:
            if self.draft['seq'] <= after and wait_ms:
                self.draft_changed.wait(wait_ms / 1000)
            return dict(self.draft) if self.draft['seq'] > after else {'seq': self.draft['seq']}

    def new(self, cid, message, key=None):
        return self.chat.send(ME, conversation_id=cid, message=message, key=key or uuid.uuid4().hex)['id']

    # -- finished examples of every kind -------------------------------------------------------------------------------------------------------
    def seed(self):
        for cid, title in [('live', 'Try it: send a message'), ('unconfirmed', 'Add wings to the cart'), ('verified', 'Quarterly numbers'), ('failed', 'Daily stock report'),
                           ('plain', 'A quick question'), ('permission', 'File the bug in Linear'), ('handoff', 'Book the dentist'), ('stopped', 'Compare three laptops')]:
            self.conversation(cid, title)
        rid = self.new('unconfirmed', 'Add the spiciest chicken wings to my Uber Eats cart')
        self.state(rid, 'running')
        self.events.append('a', rid, 'task_steps', {'revision': 1, 'update_id': 'u1', 'mode': 'plan', 'steps': [
            {'id': 'open', 'title': 'Open Uber Eats', 'status': 'done', 'checkpoint': 'The restaurant list is showing', 'result': 'Opened the Wing Shack menu'},
            {'id': 'pick', 'title': 'Find the spiciest wings', 'status': 'done', 'checkpoint': 'One item chosen', 'result': 'Reaper wings, 12 pieces'},
            {'id': 'cart', 'title': 'Add them to the cart', 'status': 'running', 'checkpoint': 'The cart shows the wings'}]}, 'agent')
        self.act(rid, 's1', 'done', 'search', 'Searched the web', 'spiciest wings near me uber eats')
        self.act(rid, 'b1', 'running', 'browse', 'Used the browser', 'ubereats.com')
        self.act(rid, 'r1', 'running', 'read', 'Opened a page', 'wingshack.example/menu')
        self.act(rid, 'r1', 'done', 'read', 'Opened a page', 'wingshack.example/menu')
        self.act(rid, 'b1', 'done', 'browse', 'Used the browser', 'ubereats.com')
        self.say('unconfirmed', 'I’ll look for the spiciest option on the menu first.', request_id=rid)
        self.say('unconfirmed', 'The spiciest are the **Reaper wings** (12 pieces). I added them to your cart; checkout is yours to do.', request_id=rid)
        self.sql("INSERT INTO browse_runs(account_id,request_id,goal,status,url,created_epoch,updated_epoch) VALUES ('a',?,'Add wings','done','https://www.ubereats.com/store/wing-shack',?,?)", (rid, int(time.time()), int(time.time())))
        self.finish(rid, verification='unverified', note="Done, but I couldn't confirm it from the page.")

        rid = self.new('verified', 'Turn the Q3 spreadsheet into a one-page summary')
        self.state(rid, 'running')
        self.act(rid, 'f1', 'done', 'file', 'Read a file', 'q3-numbers.xlsx', tool='read')
        self.act(rid, 'c1', 'done', 'command', 'Ran a command', 'python3 summarise.py q3-numbers.xlsx', 'revenue up 12%\nchurn down 0.4 pts\nwrote summary.md', tool='exec')
        self.act(rid, 'f2', 'done', 'file', 'Wrote a file', 'summary.md', tool='write')
        self.events.append('a', rid, 'artifact', {'artifact_id': 'art1', 'version': 1, 'name': 'summary.md', 'sha256': 'a' * 64}, 'gateway')
        self.say('verified', 'Here is the one-page summary. Revenue is up 12% and churn is down 0.4 points.', request_id=rid)
        self.finish(rid, verification='verified', note='Done.')

        rid = self.new('failed', 'Set up a daily stock market report')
        self.state(rid, 'running')
        self.act(rid, 'c1', 'failed', 'command', 'Ran a command', 'curl https://quotes.example/api', 'curl: (28) Operation timed out', tool='exec')
        self.events.append('a', rid, 'error', {'summary': 'The assistant took too long and was stopped.', 'category': 'runtime'}, 'gateway')
        self.finish(rid, outcome='failed', verification='unverified', note='The assistant took too long and was stopped.', state='failed', result='The assistant took too long and was stopped.')

        rid = self.new('plain', 'What is the capital of Portugal?')
        self.state(rid, 'running')
        self.say('plain', 'Lisbon.', request_id=rid)
        self.finish(rid)

        rid = self.new('permission', 'File the login bug in Linear')
        self.state(rid, 'running')
        self.act(rid, 's1', 'done', 'search', 'Searched the web', 'linear issue template bug')
        self.ask_permission(rid)
        self.say('permission', 'I need your permission to create the issue in Linear. The request is shown above.', request_id=rid)
        self.finish(rid)

        rid = self.new('handoff', 'Book a dentist appointment for next Tuesday')
        self.state(rid, 'running', parked_reason='browser')
        self.act(rid, 'b1', 'running', 'browse', 'Used the browser', 'smileclinic.example/book')
        self.sql("INSERT INTO browse_runs(account_id,request_id,goal,status,url,pending_json,created_epoch,updated_epoch) VALUES ('a',?,'Book','handoff','https://smileclinic.example/book',?,?,?)",
                 (rid, json.dumps({'label': 'Sign in to Smile Clinic'}), int(time.time()), int(time.time())))

        rid = self.new('stopped', 'Compare three laptops under $1,000')
        self.state(rid, 'running')
        self.act(rid, 's1', 'done', 'search', 'Searched the web', 'best laptops under 1000')
        self.finish(rid, outcome='cancelled', note='Stopped at your request.', state='cancelled')
        held = self.new('stopped', 'Then write up the winner')
        self.queue.pause(ME, held)

    def ask_permission(self, rid):
        call = uuid.uuid4().hex
        arguments = {'title': 'Login button does nothing on Safari', 'team': 'Web', 'priority': 2, 'labels': ['bug', 'safari']}
        self.sql("INSERT INTO mcp_calls(account_id,id,connection_id,tool_name,payload_hash,schema_hash,request_id,arguments_json,state,expires_epoch,created_epoch) VALUES ('a',?,'conn1','create_issue','h','s',?,?,'pending',?,?)",
                 (call, rid, json.dumps(arguments), int(time.time()) + 600, int(time.time())))
        self.events.append('a', rid, 'approval_request', {'request_id': call, 'summary': 'Asked for your permission to use create issue on Linear', 'expires_epoch': int(time.time()) + 600}, 'approval')
        return call

    # -- the director: plays the request worker for messages sent in the "live" chat -----------------------------------------------------------
    def direct(self):
        while True:
            time.sleep(0.4)
            with self.store.connect() as con:
                row = con.execute("SELECT id,message,conversation_id,paused FROM customer_requests WHERE account_id='a' AND state='waiting' AND paused=0 ORDER BY sequence LIMIT 1").fetchone()
            if row:
                try:
                    self.play(row['id'], row['message'], row['conversation_id'])
                except Exception as error:                               # a fixture must not die on one odd message
                    print('director:', error, flush=True)

    def stopped(self, rid):
        with self.store.connect() as con:
            if con.execute('SELECT cancel_requested FROM customer_requests WHERE id=?', (rid,)).fetchone()[0]:
                self.finish(rid, outcome='cancelled', note='Stopped at your request.', state='cancelled')
                return True
        return False

    def wait(self, rid, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stopped(rid):
                return False
            time.sleep(0.15)
        return True

    def write(self, rid, cid, item, text):
        words, shown = text.split(' '), ''
        for w in words:
            shown = (shown + ' ' + w).strip()
            self.write_draft(rid, item, shown)
            time.sleep(0.07)
        self.write_draft(rid, item, shown, done=True)
        self.say(cid, text, request_id=rid)

    def play(self, rid, message, cid):
        low = message.lower()
        time.sleep(1.2)
        self.state(rid, 'starting')
        if not self.wait(rid, 1.5): return
        self.state(rid, 'running')
        if not self.wait(rid, 1.2): return
        self.act(rid, 's1', 'running', 'search', 'Searched the web', 'flights lisbon direct october')
        if not self.wait(rid, 2.2): return
        self.act(rid, 's1', 'done', 'search', 'Searched the web', 'flights lisbon direct october')
        self.write(rid, cid, 'm:1', 'I found three airlines that fly direct. Checking their fares now.')
        self.act(rid, 'r1', 'running', 'read', 'Opened a page', 'flytap.example/fares')
        self.act(rid, 'r2', 'running', 'read', 'Opened a page', 'iberia.example/deals')
        self.act(rid, 'c1', 'running', 'command', 'Ran a command', 'python3 compare_fares.py', tool='exec')
        if not self.wait(rid, 2.5): return
        self.act(rid, 'r1', 'done', 'read', 'Opened a page', 'flytap.example/fares')
        if not self.wait(rid, 1.5): return
        self.act(rid, 'r2', 'failed', 'read', 'Opened a page', 'iberia.example/deals', 'HTTP 503')
        self.act(rid, 'c1', 'done', 'command', 'Ran a command', 'python3 compare_fares.py', 'TAP   EUR 142  09:10\nRyan  EUR  96  06:25\nwrote fares.csv', tool='exec')
        if 'fail' in low:
            self.events.append('a', rid, 'error', {'summary': 'The run ended with an error before it finished.', 'category': 'runtime'}, 'gateway')
            return self.finish(rid, outcome='failed', verification='unverified', note='The run ended with an error before it finished.', state='failed', result='The run ended with an error before it finished.')
        if 'approve' in low or 'permission' in low:
            call = self.ask_permission(rid)
            while True:                                              # the run waits on the customer (the real tool call returns "approval required" and the run ends or is steered)
                if self.stopped(rid): return
                with self.store.connect() as con:
                    decided = con.execute('SELECT state FROM mcp_calls WHERE id=?', (call,)).fetchone()[0]
                if decided != 'pending': break
                time.sleep(0.3)
            if decided == 'approved':
                self.act(rid, 'm1', 'running', 'other', 'Used create issue')
                if not self.wait(rid, 1.5): return
                self.act(rid, 'm1', 'done', 'other', 'Used create issue')
        if 'browser' in low:
            self.act(rid, 'b1', 'running', 'browse', 'Used the browser', 'flytap.example/checkout')
            self.sql("INSERT OR REPLACE INTO browse_runs(account_id,request_id,goal,status,url,pending_json,created_epoch,updated_epoch) VALUES ('a',?,'Book','handoff','https://flytap.example/checkout',?,?,?)",
                     (rid, json.dumps({'label': 'Pay for the ticket'}), int(time.time()), int(time.time())))
            self.state(rid, 'running', parked_reason='browser')
            if not self.wait(rid, 20): return
            self.sql("UPDATE browse_runs SET status='done' WHERE request_id=?", (rid,))
            self.state(rid, 'running', parked_reason=None)
            self.act(rid, 'b1', 'done', 'browse', 'Used the browser', 'flytap.example/checkout')
        self.act(rid, 'f1', 'running', 'file', 'Wrote a file', 'fares.md', tool='write')
        if not self.wait(rid, 1.2): return
        self.act(rid, 'f1', 'done', 'file', 'Wrote a file', 'fares.md', tool='write')
        self.events.append('a', rid, 'artifact', {'artifact_id': uuid.uuid4().hex, 'version': 1, 'name': 'fares.md', 'sha256': 'b' * 64}, 'gateway')
        self.write(rid, cid, 'm:2', 'The cheapest direct flight is **Ryanair at EUR 96**, leaving 06:25. TAP is EUR 142 at 09:10, a kinder hour. Iberia’s page would not load, so it is not in the comparison. I saved the table as fares.md.')
        self.finish(rid, verification='verified', note='Done.')


W = World()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def send(self, status, body=None, kind='application/json'):
        data = b'' if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        path, q = url.path, parse_qs(url.query)
        one = lambda name, default='': q.get(name, [default])[0]
        try:
            if path == '/v1/push':
                return self.stream(one)
            if path == '/readyz':
                return self.send(200, {'ok': True})
            if path == '/v1/csrf':
                return self.send(200, {'csrf_token': 'preview'})
            if path == '/v1/app':
                return self.send(200, {'api_version': '1', 'user': {'email': 'parsa@example.com', 'role': 'customer'}, 'assistant': {'state': 'running'},
                                       'features': {'execution': True, 'chat': True, 'billing_mode': 'open', 'files': False, 'browse': True, 'mcp': True, 'requests': True, 'usage': False, 'connectors': False, 'telegram': False, 'uploads': False},
                                       'limits': {'max_message_chars': 16000, 'max_projects': 5, 'max_conversations_per_project': 100}})
            if path == '/v1/work':
                out = W.reader.listing(ME)
                return self.send(200, {'rev': out['rev'], 'unchanged': True} if one('rev') == out['rev'] else out)
            if path.startswith('/v1/work/'):
                out = W.reader.detail(ME, path.rsplit('/', 1)[1], after=int(one('after', '0') or 0))
                return self.send(200, {'rev': out['task']['rev'], 'cursor': out['cursor'], 'unchanged': True} if one('rev') == out['task']['rev'] and not out['rows'] else out)
            if path == '/v1/conversations':
                rows = W.chat.conversations(ME, 'p-a')
                return self.send(200, {'conversations': rows, 'has_more': False, 'next_offset': len(rows)})
            if path.startswith('/v1/conversations/'):
                parts = path.split('/')
                if len(parts) == 4:
                    return self.send(200, {'conversation': W.chat.conversation(ME, parts[3])})
                if parts[4] == 'messages':
                    return self.send(200, W.chat.messages(ME, parts[3], after=int(one('after', '0') or 0)))
                if parts[4] == 'blocks':
                    return self.send(200, {'blocks': []})
            if path.startswith('/v1/browse/') and path.count('/') == 3:
                rid = path.rsplit('/', 1)[1]
                with W.store.connect() as con:
                    row = con.execute("SELECT * FROM browse_runs WHERE account_id='a' AND request_id=?", (rid,)).fetchone()
                if not row:
                    return self.send(404, {'error': 'not_found'})
                pending = json.loads(row['pending_json']) if row['pending_json'] else None
                return self.send(200, {'request_id': rid, 'goal': row['goal'], 'status': row['status'], 'url': row['url'], 'created_epoch': row['created_epoch'], 'answer': None, 'reason': None,
                                       'takeover': row['status'] in ('handoff', 'paused'), 'needs_you': None, 'pending_action': pending, 'events': []})
            if path.startswith('/v1/'):
                return self.send(200, {} if not path.startswith('/v1/location') else {'request': None})
            if path == '/layout-check.js':
                return self.send(200, (ROOT / 'tests' / 'browser-layout.js').read_bytes(), 'text/javascript')
            return self.static(path)
        except NotFound:
            self.send(404, {'error': 'not_found'})
        except (ValueError, KeyError, IndexError):
            self.send(400, {'error': 'invalid_request'})

    def static(self, path):
        rel = path.removeprefix('/app').lstrip('/')
        file = (DIST / rel).resolve()
        if not rel or not str(file).startswith(str(DIST)) or not file.is_file():
            file = DIST / 'index.html'
        body = file.read_bytes()
        if file.name == 'index.html':                          # the chat layout assertions (tests/browser-layout.js) run on every page of this preview too
            body = body.replace(b'</body>', b'<script type="module" src="/layout-check.js"></script></body>')
        self.send(200, body, MIME.get(file.suffix, 'application/octet-stream'))

    def stream(self, one):
        principal = W.push.admit(one('t'))
        if not principal:
            return self.send(403 if principal is None else 429)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            after = one('after', '0')
            for frame in W.push.stream(principal, focus=one('focus'), after=int(after) if after.isdigit() else 0, rev=one('rev'), frev=one('frev')):
                self.wfile.write(frame)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            W.push.release(principal)

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            return self.send(400, {'error': 'invalid_request'})
        try:
            if path == '/v1/work/ticket':
                return self.send(200, {'ticket': live_ticket.mint_work(SECRET, 'a', 'actor-a'), 'path': '/v1/push', 'expires_in': live_ticket.WORK_TTL_SECONDS}) if PUSH else self.send(404, {'error': 'not_found'})
            if path == '/v1/conversations':
                cid = uuid.uuid4().hex
                W.conversation(cid, None)
                return self.send(201, {'conversation': W.chat.conversation(ME, cid)})
            parts = path.split('/')
            if path.startswith('/v1/conversations/') and parts[-1] == 'send':
                out = W.chat.send(ME, conversation_id=parts[3], message=str(body.get('message', '')), key=str(body.get('key') or uuid.uuid4().hex))
                return self.send(202, {'request': out, **out})
            if path.startswith('/v1/requests/') and parts[-1] == 'cancel':
                return self.send(202, {'request': W.chat.cancel(ME, parts[3])})
            if path.startswith('/v1/requests/') and parts[-1] in ('pause', 'resume'):
                return self.send(200, {'request': getattr(W.queue, parts[-1])(ME, parts[3])})
            if path.startswith('/v1/account/mcp-approvals/'):
                call, approved = parts[-1], body.get('approved') is True
                with W.store.connect() as con:
                    row = con.execute("SELECT request_id,state FROM mcp_calls WHERE account_id='a' AND id=?", (call,)).fetchone()
                if not row or row['state'] != 'pending':
                    return self.send(409, {'error': 'approval_expired'})
                W.sql("UPDATE mcp_calls SET state=? WHERE id=?", ('approved' if approved else 'rejected', call))
                W.events.append('a', row['request_id'], 'approval_decision', {'request_id': call, 'decision': 'approved' if approved else 'declined'}, 'approval')
                with W.store.connect() as con:
                    req = con.execute('SELECT conversation_id,state FROM customer_requests WHERE id=?', (row['request_id'],)).fetchone()
                W.say(req['conversation_id'], f"You {'allowed' if approved else 'declined'} create issue on Linear." + ('' if approved else ' Nothing was run.'), 'system', row['request_id'])
                return self.send(200, {'decided': True, 'continued': req['state'] == 'running'})
            return self.send(200, {})
        except NotFound:
            self.send(404, {'error': 'not_found'})
        except Exception as error:
            self.send(409, {'error': type(error).__name__})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


if __name__ == '__main__':
    threading.Thread(target=W.direct, daemon=True).start()
    port = int(os.environ.get('PREVIEW_PORT', '5181'))
    print(f'http://127.0.0.1:{port}/app/tasks   push={"on" if PUSH else "off (polling)"}', flush=True)
    Server(('127.0.0.1', port), Handler).serve_forever()
