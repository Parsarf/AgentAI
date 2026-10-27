"""A scripted OpenAI-compatible model for end-to-end runs against a real OpenClaw gateway.

It is the only fake in the model path: the gateway, its tool loop, tool search, MCP client, steering and goals are the real thing. What the model "decides" comes from a
marker in the customer's message (SCENARIO:...), so each scenario is deterministic. Spend is counted per API key (one key per cell), like the provider key the
real cells hold.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INTERNAL = '<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>'
PLAN = {'schemaVersion': '1.0', 'type': 'task_plan', 'title': 'Launch the shop', 'summary': 'Two phases',
        'phases': [{'id': 'analyze', 'title': 'Analyze', 'description': 'Look at the requirements', 'enabled': True, 'optional': False, 'requiresApproval': False, 'dependsOn': []},
                   {'id': 'build', 'title': 'Build', 'description': 'Build it', 'enabled': True, 'optional': False, 'requiresApproval': False, 'dependsOn': ['analyze']}]}


def text_of(message):
    content = message.get('content')
    if isinstance(content, str):
        return content
    return ' '.join(b.get('text', '') for b in content or [] if isinstance(b, dict))


def decide(messages, tools):
    """-> {'text'} | {'tool': name, 'args': {...}} | with optional 'delay' seconds before answering."""
    live = [m for m in messages if not (m['role'] == 'user' and text_of(m).startswith(INTERNAL))]
    last = live[-1]
    if last['role'] == 'tool':
        if 'needs your next step' in text_of(last):                       # the browser handed the page over: the assistant answers it with a step (here: it reads the answer off the page)
            return {'tool': 'tool_call', 'args': {'id': 'mcp:lumina:lumina__lumina_browser_step', 'args': {'action': 'done', 'answer': 'The wings are in the cart.'}}}
        return {'text': 'TOOL-RESULT ' + text_of(last)[-400:]}
    user = text_of(last)
    everything = ' '.join(text_of(m) for m in messages if m['role'] in ('user', 'system'))        # the goal's objective is shown to the model as internal context on every turn, not in the last message
    answered = sum(1 for m in live if m['role'] == 'assistant' and text_of(m).strip())
    if 'SCENARIO:browse' in user:
        return {'tool': 'tool_call', 'args': {'id': 'mcp:lumina:lumina__lumina_browser', 'args': {
            'task': 'Add the spiciest chicken wings to the cart on Uber Eats', 'site': 'ubereats.com', 'steps': ['Open the site', 'Add the spiciest wings to the cart']}}}
    if 'SCENARIO:file' in user:
        return {'tool': 'write', 'args': {'path': 'notes/report.txt', 'content': 'The report body\n'}}
    if 'SCENARIO:slow' in user:
        return {'text': 'slow finished', 'delay': 6}
    if 'SCENARIO:goal' in user or ('Active goal:' in everything and 'SCENARIO:goal' in everything):
        if answered >= 1:
            return {'tool': 'tool_call', 'args': {'id': 'openclaw:core:update_goal', 'args': {'status': 'complete', 'note': 'report is finished'}}}
        return {'text': 'I started on the report; more to do.'}
    if 'Reply with ONLY one JSON object' in user:
        return {'text': json.dumps(PLAN)}
    if 'carrying out the approved plan' in user:
        return {'text': 'Phase result: done.'}
    if 'SCENARIO:nativebrowser' in user:
        return {'tool': 'tool_call', 'args': {'id': 'openclaw:browser:browser', 'args': {'action': 'status'}}}
    if 'SCENARIO:ask' in user:
        return {'tool': 'tool_call', 'args': {'id': 'openclaw:core:ask_user', 'args': {'questions': [{'id': 'q', 'question': 'Which size?', 'header': 'Size', 'options': [{'label': 'S'}, {'label': 'L'}]}]}}}
    if 'LIST_TOOLS' in user:
        return {'text': 'TOOLS: ' + ','.join(sorted(t['function']['name'] for t in tools or []))}
    return {'text': 'Plain answer to: ' + user.split('Customer message:')[-1].strip()[:60]}


class Handler(BaseHTTPRequestHandler):
    server_version = 'stub'

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({'data': [{'id': 'claude-sonnet-5-5', 'object': 'model'}]}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        request = json.loads(self.rfile.read(length) or b'{}')
        key = (self.headers.get('Authorization') or '').removeprefix('Bearer ').strip()
        stub = self.server.stub
        with stub.lock:
            stub.requests.append({'key': key, 'request': request})
            stub.spend[key] = stub.spend.get(key, 0) + 1
        out = decide(request.get('messages') or [], request.get('tools'))
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()

        def send(delta, finish=None, usage=None):
            chunk = {'id': 'c1', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': request.get('model', 'm'),
                     'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
            if usage:
                chunk['usage'] = usage
            self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode()); self.wfile.flush()
        try:
            time.sleep(out.get('delay', 0))
            send({'role': 'assistant'})
            usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
            if 'tool' in out:
                send({'tool_calls': [{'index': 0, 'id': 'call_%d' % len(stub.requests), 'type': 'function', 'function': {'name': out['tool'], 'arguments': json.dumps(out['args'])}}]})
                send({}, 'tool_calls', usage)
            else:
                send({'content': out['text']})
                send({}, 'stop', usage)
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class StubModel:
    def __init__(self):
        self.requests, self.spend, self.lock = [], {}, threading.Lock()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.stub = self
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def calls(self, key):
        with self.lock:
            return self.spend.get(key, 0)

    def stop(self):
        self.server.shutdown(); self.server.server_close()
