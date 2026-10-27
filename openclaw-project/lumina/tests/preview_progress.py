"""Production widget with real progress-tool events; disposable synthetic request, no live model.
Run ../platform/.venv/bin/python tests/preview_progress.py; open http://127.0.0.1:5180/app/home.
Use the local-only fixture setup API POST /__fixture with {"mode":"direct"|"plan","stage":1|2|3}
to verify polling transitions. This setup API exists only in this standalone developer process.
"""
import json
import sys
import time
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'platform'))
from tests.test_native_run import Base, OK
from agentai_platform.task_progress import TaskProgressTool
from preview_chat import Preview

fixture = Base(); fixture.setUp()
request = fixture.chat.send(fixture.a, conversation_id='c-a', message='Review the source, make the change and verify it (developer fixture)', key='progress-fixture')
fixture.queue.claim(owner='preview', capacity=OK)
tool = TaskProgressTool(fixture.store)
revision = 0; mode = None

def setup(wanted, stage):
    global revision, mode
    if mode != wanted or stage == 1:
        with fixture.store.connect() as con:
            con.execute("DELETE FROM events WHERE account_id='a' AND task_id=? AND kind='task_steps'", (request['id'],))
        revision = 0; mode = wanted
    steps = [dict(id='inspect', title='Review the source', status='running', checkpoint='Identify the cause')]
    if wanted == 'plan': steps += [dict(id='change', title='Make the change', status='pending', checkpoint='Implement the requested behavior'), dict(id='verify', title='Verify the result', status='pending', checkpoint='Required checks pass')]
    if stage >= 2:
        steps[0].update(status='done', result='Cause identified in the source')
        if wanted == 'direct': steps.append(dict(id='change', title='Make the change', status='running'))
        else: steps[1]['status'] = 'running'
    if stage >= 3:
        steps[1].update(status='done', result='Change implemented')
        if wanted == 'direct': steps.append(dict(id='verify', title='Verify the result', status='running'))
        else: steps[2]['status'] = 'running'
    if revision == 0 and stage > 1:
        setup(wanted, 1)
        if stage > 2: setup(wanted, 2)
    text, error = tool.call('a', dict(task_id=request['id'], update_id=f'{wanted}-{stage}', revision=revision, mode=wanted, steps=steps))
    if error: raise ValueError(text)
    revision += 1

setup('direct', 1)
class ProgressPreview(Preview):
    def respond(self, value, status=200):
        body = json.dumps(value).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path != '/__fixture': return self.respond({}, 404)
        args = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        try: setup(args['mode'], args['stage']); return self.respond({'revision':revision})
        except Exception as e: return self.respond({'error':str(e)},400)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/v1/requests':
            return self.respond({'requests':[dict(request, message='Review source and implement the change (developer fixture)', state='running', created_epoch=int(time.time())-90, cancel_requested=0, result=None)]})
        if path == f'/v1/tasks/{request["id"]}/events':
            after = int(parse_qs(urlparse(self.path).query).get('after',['0'])[0])
            return self.respond(tool.events.events(fixture.a, request['id'], after=after, limit=200))
        if path == '/v1/projects': return self.respond({'projects':[]})
        return super().do_GET()
if __name__ == '__main__':
    print('Widget fixture: http://127.0.0.1:5180/app/home',flush=True)
    try: ThreadingHTTPServer(('127.0.0.1',5180),ProgressPreview).serve_forever()
    finally: fixture.doCleanups()
