"""Production-bundle interaction fixture backed by the real artifact store, request queue and driver.
Run npm run build, then ../platform/.venv/bin/python tests/preview_genui.py.
Open http://127.0.0.1:5179/app/chat/c-a. Disposable synthetic account/model only;
no live provider credentials, external messages or production state. Refresh keeps artifact state.
"""
import json
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'platform'))
from tests.test_native_run import Base
from agentai_platform.genui.artifacts import ArtifactStore
from agentai_platform.genui.schema import SpecError
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound
from agentai_platform.events import EventService
from preview_chat import Preview

fixture = Base(); fixture.setUp()
fixture.chat.events = fixture.driver.events = EventService(fixture.store, clock=lambda: fixture.now)
artifacts = ArtifactStore(fixture.store, clock=lambda: fixture.now)
FORM = {'id': 'choices', 'type': 'form', 'props': {'title': 'Calculate a sample order', 'fields': [{'id': 'quantity', 'type': 'number', 'label': 'Quantity', 'default': 2, 'min': 1, 'max': 20, 'required': True}], 'submit': {'label': 'Calculate total', 'action': {'kind': 'agent.request', 'message': 'Calculate the sample order total'}}}}
BLOCKS = [
 {'id': 'note', 'type': 'callout', 'props': {'tone': 'info', 'content': 'Developer fixture. Synthetic model and illustrative prices; actions use the real artifact, queue and persistence code.'}},
 {'id': 'compare', 'type': 'table', 'props': {'title': 'Compare sample options', 'columns': [{'id': 'name', 'label': 'Option'}, {'id': 'price', 'label': 'Price', 'type': 'number'}], 'rows': [{'name': 'Alpha (sample)', 'price': 10}, {'name': 'Beta (sample)', 'price': 12}], 'searchable': True, 'pageSize': 5}},
 FORM,
 {'id': 'whatif', 'type': 'scenario_simulator', 'props': {'title': 'What if the quantity changes?', 'inputs': [{'id': 'price', 'label': 'Unit price', 'value': 10}, {'id': 'quantity', 'label': 'Scenario quantity', 'value': 2, 'min': 1, 'max': 20}], 'operation': 'multiply', 'unit': 'USD'}},
]
def document(blocks, **extra): return dict(version='1.0', responseId='fixture', blocks=blocks, **extra)
def fenced(value): return 'Here is the sample comparison.\n```lumina-doc\n' + json.dumps(value) + '\n```'
fixture.run_message('Demonstrate a comparison and interactive calculation (developer fixture)', [fenced(document(BLOCKS))], ui='interactive')
artifact_id = fixture.chat.blocks.list(fixture.a, 'c-a')[0]['id']

def model_reply(*_):
    with fixture.store.connect() as con:
        event = con.execute('SELECT payload_json,version FROM gen_artifact_events ORDER BY rowid DESC LIMIT 1').fetchone()
    payload = json.loads(event['payload_json'])
    quantity = payload['values'].get('quantity', 2)
    total = {'id': 'total', 'type': 'metric_card', 'props': {'label': 'Calculated sample total', 'value': quantity * 10, 'format': 'currency', 'currency': 'USD', 'source': 'Quantity × illustrative price of $10'}}
    return {'text': fenced(document([*BLOCKS, total], artifactId=artifact_id, baseVersion=event['version']))}
fixture.gateway.script = model_reply

class InteractivePreview(Preview):
    def respond(self, value, status=200):
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(json.dumps(value).encode())

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/v1/conversations/stress/blocks':
            spec = document([{'id': f'table_{n}', 'type': 'table', 'dataRef': 'large', 'props': {'title': f'Stress table {n + 1}', 'searchable': True, 'sortable': True, 'pageSize': 20}} for n in range(24)], datasets={'large': {'columns': [{'id': 'name', 'label': 'Item'}, {'id': 'value', 'label': 'Value', 'type': 'number'}], 'rows': [{'name': f'Illustrative item {i}', 'value': i} for i in range(500)]}})
            return self.respond({'blocks': [{'id': 'stress-document', 'conversation_id': 'stress', 'anchor_message_id': 2, 'kind': 'document', 'schema_version': '1.0', 'spec': spec, 'state': {}, 'version': 1, 'state_revision': 1, 'status': 'final', 'launched_request_id': None}]})
        if path == '/v1/csrf': return self.respond({'csrf_token': 'disposable-fixture'})
        if path == '/v1/conversations/c-a/messages': return self.respond(fixture.chat.messages(fixture.a, 'c-a', after=int(parse_qs(urlparse(self.path).query).get('after', ['0'])[0])))
        if path == '/v1/conversations/c-a/blocks': return self.respond({'blocks': fixture.chat.blocks.list(fixture.a, 'c-a')})
        if path == '/v1/conversations/c-a': return self.respond({'conversation': fixture.chat.conversation(fixture.a, 'c-a')})
        if path == '/v1/conversations': return self.respond({'conversations': [fixture.chat.conversation(fixture.a, 'c-a')]})
        if path.startswith('/v1/requests/') and path.count('/') == 3:
            return self.respond({'task': fixture.chat.task(fixture.a, path.split('/')[-1])})
        if path.startswith('/v1/tasks/') and path.endswith('/events'):
            task = path.split('/')[3]
            with fixture.store.connect() as con:
                rows = con.execute('SELECT sequence,kind,public_payload,created_at FROM events WHERE account_id=? AND task_id=? AND sequence>? ORDER BY sequence', ('a', task, int(parse_qs(urlparse(self.path).query).get('after', ['0'])[0]))).fetchall()
            return self.respond({'events': [dict(sequence=r['sequence'], kind=r['kind'], payload=json.loads(r['public_payload']), created_at=r['created_at']) for r in rows]})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path; body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        prefix = f'/v1/genui/artifacts/{artifact_id}'
        try:
            if path == prefix + '/state': return self.respond(artifacts.state(fixture.a, artifact_id, body['version'], body['state_revision'], body['state']))
            if path == prefix + '/events':
                result = artifacts.event(fixture.a, artifact_id, body, fixture.chat)
                fixture.worker.tick()
                return self.respond(result, 202)
            return self.respond({'error': 'fixture_route_unavailable'}, 404)
        except Conflict as error: return self.respond({'error': 'version_conflict', 'detail': str(error)}, 409)
        except (SpecError, ValueError, KeyError) as error: return self.respond({'error': 'invalid_ui_document', 'detail': str(error)}, 400)
        except NotFound: return self.respond({'error': 'unavailable'}, 404)

if __name__ == '__main__':
    print('Interactive fixture: http://127.0.0.1:5179/app/chat/c-a', flush=True)
    try: ThreadingHTTPServer(('127.0.0.1', 5179), InteractivePreview).serve_forever()
    finally: fixture.doCleanups()
