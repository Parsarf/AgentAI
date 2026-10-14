"""Local visual regression fixture using the actual production bundle.
Run npm run build, then python3 tests/preview_chat.py. Open
http://127.0.0.1:5178/app/chat/working (also completed, long, multiple).
Orb fixtures also include breathing, searching, solving, listening, connecting,
weaving, composing, shaping, queued, starting, and transitions (cycles test events).
All API responses are synthetic; this server accepts no writes.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json
import time
from urllib.parse import urlparse, parse_qs
ROOT = Path(__file__).resolve().parents[1] / 'dist'
class Preview(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        scenario = path.split('/')[3] if path.startswith('/v1/conversations/') else 'working'
        now = int(time.time())
        chat = {'id': scenario, 'title': 'hey', 'project_id': 'fixture', 'created_at': '2026-10-13T00:00:00Z', 'last_activity': '2026-10-13T00:00:00Z', 'active': 1}
        orb_states = ['breathing', 'searching', 'solving', 'listening', 'connecting', 'weaving', 'composing', 'shaping', 'working']
        pending = scenario in orb_states or scenario in ['queued', 'starting', 'transitions']
        task = {'id': f'fixture-{scenario}', 'state': 'waiting' if scenario == 'queued' else 'starting' if scenario == 'starting' else 'running' if pending else 'completed', 'created_epoch': now - 82, 'message': 'hey', 'cancel_requested': 0, 'result': None}
        if path.startswith('/v1/') or path == '/readyz':
            data = {}
            if path == '/v1/app':
                data = {'api_version': '1', 'user': {'email': 'preview@example.com', 'role': 'owner'}, 'assistant': {'state': 'running'}, 'features': {'execution': True, 'chat': True, 'billing_mode': 'open', 'files': False}, 'limits': {'max_message_chars': 16000}}
            elif path == '/v1/requests': data = {'requests': []}
            elif path == '/v1/conversations': data = {'conversations': [dict(chat, id=x) for x in ['working', 'completed', 'long', 'multiple']]}
            elif path.endswith('/messages'):
                messages = [{'id': 1, 'provenance': 'customer', 'request_id': task['id'], 'content': 'hey', 'created_at': ''}]
                if not pending: messages.append({'id': 2, 'provenance': 'agent', 'request_id': task['id'], 'content': "Hey! What's up?", 'created_at': ''})
                if scenario in ['long', 'multiple']: messages.append({'id': 3, 'provenance': 'customer', 'request_id': None, 'content': 'A longer message that should wrap naturally. ' * 30, 'created_at': ''})
                if scenario == 'multiple':
                    for i in range(4, 12): messages.append({'id': i, 'provenance': 'agent' if i % 2 == 0 else 'customer', 'request_id': None, 'content': f'Message {i}', 'created_at': ''})
                if scenario == 'overflow':
                    pie = {'schemaVersion': '1.0', 'type': 'pie', 'title': "What's Working Today 🎯", 'labels': ['Tables', 'Charts', 'Comparisons', 'Emojis', 'Details blocks'], 'series': [{'name': 'Ready', 'values': [20, 20, 20, 20, 20]}]}
                    code = 'const value = "' + 'long-preserved-code-line-' * 80 + '";'
                    prose = 'Normal text should wrap at word boundaries and grow vertically. ' * 25
                    url = 'https://example.com/' + 'long-url-segment-' * 80
                    table = '| ' + ' | '.join('Column ' + str(i) for i in range(12)) + ' |\n| ' + ' | '.join('---' for _ in range(12)) + ' |\n| ' + ' | '.join('Value' for _ in range(12)) + ' |'
                    messages[1]['content'] = 'Data visualizations ✨\n\n```json\n' + json.dumps(pie, ensure_ascii=False) + '\n```\n\n' + prose + '\n\n```js\n' + code + '\n```\n\n' + url + '\n\n' + table
                after = int(parse_qs(parsed.query).get('after', ['0'])[0])
                data = {'messages': [m for m in messages if m['id'] > after], 'tasks': [task], 'has_more': False}
            elif path.endswith('/blocks'): data = {'blocks': []}
            elif path.endswith('/events'):
                orb = path.split('/')[3].removeprefix('fixture-')
                after = int(parse_qs(parsed.query).get('after', ['0'])[0])
                data = {'events': [{'sequence': after + 1, 'kind': 'activity', 'payload': {'ref': 'fixture-call', 'category': orb_states[after % len(orb_states)], 'status': 'running'}, 'created_at': ''}]} if orb == 'transitions' else {'events': [] if after else [{'sequence': 1, 'kind': 'activity', 'payload': {'ref': 'fixture-call', 'category': orb, 'status': 'running'}, 'created_at': ''}]}
            elif path.startswith('/v1/conversations/'): data = {'conversation': chat}
            payload = json.dumps(data).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(payload); return
        if path == '/layout-check.js':
            self.send_response(200); self.send_header('Content-Type', 'text/javascript'); self.end_headers()
            self.wfile.write((Path(__file__).parent / 'browser-layout.js').read_bytes()); return
        relative = path.removeprefix('/app/').lstrip('/')
        file = ROOT / relative
        if not file.is_file(): file = ROOT / 'index.html'
        self.send_response(200)
        self.send_header('Content-Type', self.guess_type(str(file)))
        content = file.read_bytes()
        if file.name == 'index.html':
            content = content.replace(b'</body>', b'<script type="module" src="/layout-check.js"></script></body>')
        self.end_headers(); self.wfile.write(content)
if __name__ == '__main__':
    print('Preview: http://127.0.0.1:5178/app/chat/working', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 5178), Preview).serve_forever()
