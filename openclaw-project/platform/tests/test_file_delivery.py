"""Files in any format: storing, listing, deleting, the bridge's workspace reads, the render service and the assistant's file tool."""
import base64
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.artifacts import ArtifactService, media_for, safe_name
from agentai_platform.events import EventService
from agentai_platform.file_tools import FileTools, NAME
from agentai_platform.gateway import NativeGateway
from agentai_platform.lifecycle.cell_bridge import BridgeError, CellBridge
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.render import service as render_service
from agentai_platform.render.client import RenderRefused, RenderRpc
from agentai_platform.render.service import RenderError, RenderService, job_argv
from agentai_platform.security import NotFound, Principal
from agentai_platform.storage import RootStore
from agentai_platform.store import Store
from agentai_platform.tool_relay import Relay

LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000, 'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}
JPEG = b'\xff\xd8\xff\xe0' + b'j' * 64


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3'); self.store.initialize()
        self.root = RootStore(Path(self.tmp.name) / 'storage')
        self.artifacts = ArtifactService(self.store, storage=self.root, signing_key=b'k' * 32, clock=lambda: 2000000000)
        self.a = Principal('a', 'actor-a', 'customer'); self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (x, 'd-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P'))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))", (x, 'e-' + x, json.dumps(LIMITS), 2000000000 + 1000000))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)', (x, 'p-' + x, 'c-' + x, 'd-' + x))
                con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES (?,?,?,'t-' || ?,'completed',0)", (x, 'p-' + x, 'c-' + x, x))
                con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
                    VALUES (?,'t-' || ?,?,?,?,'k','h','make a file','running',1)''', (x, x, 'actor-' + x, 'p-' + x, 'c-' + x))

    def capture(self, name='result.txt', data=b'body', account='a'):
        return self.artifacts.capture_or_version(account_id=account, project_id='p-' + account, task_id='t-' + account, name=name, media_type=media_for(name), data=data)

    def on_disk(self):
        return sorted(str(p.relative_to(self.root.root)) for p in self.root.root.rglob('*') if p.is_file())


class ArtifactStoreChecks(Base):
    def test_any_format_and_folders_are_kept_with_the_right_type(self):
        self.assertEqual(media_for('Q3 sales.XLSX'), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(media_for('strange.xyz'), 'application/octet-stream')
        for name in ('Q3 sales.xlsx', 'report/2026/summary.pdf', 'deck.pptx', 'clip.mp4', 'noext'):
            self.assertEqual(safe_name(name), name)
            self.capture(name, b'x' + name.encode())
        for bad in ('../up.txt', '/abs.txt', 'a//b.txt', '.hidden', 'dir/.hidden', 'a\\b.txt', 'nul\x00.txt', '', ' ', 'x' * 201, 'dir/../x.txt', 'line\nbreak.txt'):
            with self.assertRaises(ValueError, msg=bad):
                self.capture(bad)
        listed = self.artifacts.list_account(self.a)
        self.assertEqual(sorted(f['display_name'] for f in listed['files']), ['Q3 sales.xlsx', 'clip.mp4', 'deck.pptx', 'noext', 'report/2026/summary.pdf'])
        self.assertEqual(listed['files'][0]['conversation_id'], 'c-a')
        self.assertEqual(listed['quota_bytes'], 2 * 1024 ** 3)
        self.assertEqual(listed['used_bytes'], sum(f['size_bytes'] for f in listed['files']))
        self.assertEqual(self.artifacts.list_account(self.b)['files'], [])              # nothing of another account

    def test_delete_removes_every_version_the_bytes_and_tickets_and_is_scoped(self):
        first = self.capture('plan.md', b'one'); self.capture('plan.md', b'two'); keep = self.capture('keep.txt', b'keep')
        self.artifacts.save_preview('a', first['artifact_id'], 1, JPEG)
        self.artifacts.mint_ticket(self.a, first['artifact_id'], 2)
        with self.assertRaises(NotFound):
            self.artifacts.delete(self.b, first['artifact_id'])                         # another account cannot delete it
        self.assertEqual(len(self.on_disk()), 4)
        self.assertEqual(self.artifacts.delete(self.a, first['artifact_id']), {'artifact_id': first['artifact_id'], 'versions': 2})
        self.assertEqual(self.on_disk(), [f'a/artifacts/{keep["artifact_id"]}/1'])     # bytes and picture gone, the other file untouched
        self.assertFalse((self.root.root / 'a' / 'artifacts' / first['artifact_id']).exists())
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM download_tickets').fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT count(*) FROM audit_events WHERE action='lifecycle.artifact.delete'").fetchone()[0], 1)
        self.assertEqual([f['display_name'] for f in self.artifacts.list_account(self.a)['files']], ['keep.txt'])
        with self.assertRaises(NotFound):
            self.artifacts.delete(self.a, first['artifact_id'])
        self.assertEqual(self.capture('plan.md', b'again')['version'], 1)               # the name is free again

    def test_a_new_version_by_the_customer_follows_the_newest_one(self):
        made = self.capture('a.txt', b'1'); self.capture('a.txt', b'2')
        self.assertEqual(self.artifacts.add_version(self.a, made['artifact_id'], b'3')['version'], 3)

    def test_quota_counts_uploads_and_generated_files_together(self):
        from agentai_platform import artifacts as module
        with self.store.connect() as con:
            con.execute("INSERT INTO project_files(account_id,project_id,id,display_name,media_type,size_bytes,sha256,storage_ref,state) VALUES ('a','p-a','f1','u.txt','text/plain',90,?, 'files/f1','scanned')", ('0' * 64,))
        old = module.ACCOUNT_QUOTA_BYTES
        module.ACCOUNT_QUOTA_BYTES = 100
        self.addCleanup(setattr, module, 'ACCOUNT_QUOTA_BYTES', old)
        self.capture('small.txt', b'12345')
        with self.assertRaises(Conflict):
            self.capture('big.txt', b'x' * 10)
        with self.assertRaises(Conflict):
            self.capture('small.txt', b'y' * 10)                                         # a new version is bound by the same limit

    def test_download_all_covers_the_account_replaces_itself_and_never_packs_an_old_archive(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p-2','Second')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-2','c-2','d-a')")
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p-2','c-2','t-2','completed',0)")
        self.capture('one.txt', b'1'); self.capture('one.txt', b'1b')
        self.artifacts.capture(account_id='a', project_id='p-2', task_id='t-2', name='docs/two.pdf', media_type='application/pdf', data=b'%PDF 2')
        first = self.artifacts.build_bundle(self.a)
        self.assertEqual(first['file_count'], 2)
        second = self.artifacts.build_bundle(self.a)
        self.assertEqual(second['file_count'], 2)                                        # the first archive was not packed into the second
        parts, row = self.artifacts.open_version(self.a, second['artifact_id'], 1)
        with zipfile.ZipFile(io.BytesIO(self.root.read_private(parts))) as archive:
            names = [n for n in archive.namelist() if n != 'manifest.json']
            self.assertEqual(sorted(n.split('/', 3)[3] for n in names), ['docs/two.pdf', 'one.txt'])
            self.assertEqual(sorted(archive.read(n) for n in names), [b'%PDF 2', b'1b'])
        with self.assertRaises(NotFound):
            self.artifacts.open_version(self.a, first['artifact_id'], 1)                 # replaced, not piled up
        self.assertEqual(len(self.artifacts.list_account(self.a)['files']), 3)           # archives are not listed as files
        with self.assertRaises(Conflict):
            self.artifacts.build_bundle(self.b)

    def test_storage_streams_and_delete_tolerates_missing(self):
        self.root.write_private(['a', 'artifacts', 'x1', '1'], b'stream me')
        with self.root.open_private(['a', 'artifacts', 'x1', '1']) as handle:
            self.assertEqual(handle.read(), b'stream me')
        self.root.delete(['a', 'artifacts', 'nope', '1']); self.root.delete(['a', 'artifacts', 'x1', '1']); self.root.delete(['a', 'artifacts', 'x1', '1'])
        self.root.remove_empty_dir(['a', 'artifacts', 'x1'])
        self.assertFalse((self.root.root / 'a' / 'artifacts' / 'x1').exists())
        with self.assertRaises(ValueError):
            self.root.delete(['a', '..'])


class BridgeWorkspaceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        for tenant in ('tnt-a', 'tnt-b'):
            (Path(self.tmp.name) / tenant / 'workspace' / 'out').mkdir(parents=True)
            (Path(self.tmp.name) / tenant / 'workspace' / 'out' / 'data.bin').write_bytes(tenant.encode() * 1000)
        (Path(self.tmp.name) / 'tnt-b' / 'workspace' / 'private.txt').write_text('B ONLY')
        self.bridge = CellBridge(lambda a: None, None, None, binding=lambda a: {'acct': 'tnt-a'}.get(a), workspace_root=self.tmp.name)

    def test_scan_stat_and_read_stay_inside_the_accounts_own_workspace(self):
        found = self.bridge.call('acct', 'workspace.scan', {'since': 0})
        self.assertEqual(found, {'files': [{'path': 'out/data.bin', 'size': 5000, 'mtime': found['files'][0]['mtime']}], 'skipped': []})
        self.assertEqual(self.bridge.call('acct', 'workspace.stat', {'path': 'out/data.bin'})['size'], 5000)
        self.assertEqual(self.bridge.call('acct', 'workspace.stat', {'path': 'private.txt'}), {'reason': 'not found'})      # the other tenant's file does not exist here
        part = self.bridge.call('acct', 'workspace.read', {'path': 'out/data.bin', 'offset': 4990, 'length': 100})
        self.assertEqual((base64.b64decode(part['data_b64']), part['eof']), (b'tnt-atnt-a', True))
        for params in ({'path': '../tnt-b/workspace/private.txt'}, {'path': '/etc/passwd'}, {'path': 'out/data.bin', 'offset': -1}, {'path': 'out/data.bin', 'length': 10 ** 9},
                       {'path': 'out/data.bin', 'offset': '0'}, {'path': 7}, {}):
            with self.assertRaises(BridgeError, msg=params):
                self.bridge.call('acct', 'workspace.read', params)
        with self.assertRaises(BridgeError):
            self.bridge.call('acct', 'workspace.read', {'path': 'missing.txt'})
        for method in ('workspace.scan', 'workspace.stat', 'workspace.read'):
            with self.assertRaises(BridgeError):
                self.bridge.call('nobody', method, {'since': 0, 'path': 'out/data.bin'})

    def test_the_gateway_reads_a_large_file_in_slices_and_notices_a_change(self):
        from agentai_platform.lifecycle import workspace as ws
        old = ws.MAX_CHUNK
        ws.MAX_CHUNK = 1024
        self.addCleanup(setattr, ws, 'MAX_CHUNK', old)
        calls = []
        def rpc(method, params):
            calls.append(method)
            return self.bridge.call('acct', method, params)
        gateway = NativeGateway(rpc)
        self.assertEqual(gateway.workspace_stat('out/data.bin'), {'size': 5000})
        self.assertEqual(gateway.workspace_read('out/data.bin', 5000), b'tnt-a' * 1000)
        self.assertEqual(calls.count('workspace.read'), 5)
        self.assertEqual(gateway.workspace_files(0), [('out/data.bin', b'tnt-a' * 1000)])
        with self.assertRaises(CapabilityUnavailable):
            gateway.workspace_read('out/data.bin', 6000)                                 # shorter than it said: not delivered half-read
        self.assertEqual(gateway.workspace_stat('nope.txt'), {'reason': 'not found'})


class FakeDocker:
    """Stands in for `docker run`: plays the engine's part by writing into the job's out folder."""
    def __init__(self, result=None, files=None, error=None):
        self.result, self.files, self.error, self.calls, self.seen = result, files or {}, error, [], {}

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1] == 'kill':
            return subprocess.CompletedProcess(argv, 0)
        if self.error:
            raise self.error
        folder = Path(next(a for a in argv if a.endswith(':/job/out:rw')).split(':')[0])
        job = folder.parent
        self.seen = {'request': json.loads((job / 'request.json').read_text()), 'in': {str(p.relative_to(job / 'in')): p.read_bytes() for p in (job / 'in').rglob('*') if p.is_file()}}
        for name, data in self.files.items():
            if data == 'symlink':
                os.symlink('/etc/passwd', folder / name)
            else:
                (folder / name).write_bytes(data)
        if self.result is not None:
            (folder / 'result.json').write_text(json.dumps(self.result))
        return subprocess.CompletedProcess(argv, 0)


class RenderServiceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.jobs = Path(self.tmp.name) / 'jobs'

    def service(self, docker):
        return RenderService(self.jobs, image='lumina-renderer:1', run=docker, own=lambda path, uid, gid: None)

    def test_the_container_command_is_locked_down_and_takes_nothing_from_the_customer(self):
        argv = job_argv('ab' * 16, Path('/var/lib/agentai-render/jobs/' + 'ab' * 16), 'lumina-renderer:1')
        for flag in (('--network', 'none'), ('--cap-drop', 'ALL'), ('--security-opt', 'no-new-privileges'), ('--user', '10001:10001'), ('--memory', '1536m'), ('--pids-limit', '256')):
            self.assertEqual(argv[argv.index(flag[0]) + 1], flag[1])
        self.assertIn('--read-only', argv); self.assertIn('--rm', argv)
        self.assertEqual(argv[-1], 'lumina-renderer:1')
        self.assertEqual([a for a in argv if ':/job/' in a and a.endswith(':rw')], ['/var/lib/agentai-render/jobs/' + 'ab' * 16 + '/out:/job/out:rw'])      # only the result folder is writable
        with self.assertRaises(ValueError):
            job_argv('../etc', Path('/x'), 'lumina-renderer:1')

    def test_a_conversion_hands_over_the_files_and_returns_the_result_then_keeps_nothing(self):
        docker = FakeDocker({'ok': True, 'file': 'result.pdf', 'pages': 3, 'preview': 'preview.jpg'}, {'result.pdf': b'%PDF-1.7 made', 'preview.jpg': JPEG})
        out = self.service(docker).convert('report.md', 'pdf', {'report.md': b'# Hi', 'img/logo.png': b'\x89PNG'})
        self.assertEqual(out, {'data': b'%PDF-1.7 made', 'preview': JPEG, 'pages': 3})
        self.assertEqual(docker.seen, {'request': {'source': 'report.md', 'target': 'pdf', 'preview': True}, 'in': {'report.md': b'# Hi', 'img/logo.png': b'\x89PNG'}})
        self.assertEqual(list(self.jobs.iterdir()), [])                                  # the job folder is gone

    def test_failures_are_short_reasons_and_nothing_the_container_wrote_is_trusted(self):
        cases = [
            (FakeDocker({'ok': False, 'error': 'The office converter could not read this file'}), 'The office converter could not read this file'),
            (FakeDocker(None), 'The conversion failed'),                                                           # the container wrote nothing
            (FakeDocker({'ok': True, 'file': 'result.pdf'}, {'result.pdf': 'symlink'}), 'The conversion failed'),   # a link instead of a file is never followed
            (FakeDocker({'ok': True, 'file': 'result.pdf'}, {}), 'The conversion failed'),
            (FakeDocker({'ok': False, 'error': 'bad\x1b[31mtext'}), 'The conversion failed'),
            (FakeDocker(error=subprocess.TimeoutExpired('docker', 1)), 'The conversion took too long'),
            (FakeDocker(error=FileNotFoundError()), 'The converter is not available'),
        ]
        for docker, reason in cases:
            with self.assertRaises(RenderError) as caught:
                self.service(docker).convert('a.md', 'pdf', {'a.md': b'x'})
            self.assertEqual(str(caught.exception), reason)
            self.assertEqual(list(self.jobs.iterdir()), [])
        self.assertEqual(cases[5][0].calls[-1][:2], ['docker', 'kill'])                 # a job past its time is killed
        svc = self.service(FakeDocker({'ok': True}))
        for source, target, files in (('a.md', 'exe', {'a.md': b'x'}), ('a.md', 'pdf', {'b.md': b'x'}), ('../a.md', 'pdf', {'../a.md': b'x'}), ('a.md', 'pdf', {'a.md': b''}),
                                      ('a.md', 'pdf', {'a.md': 'text'}), ('a.md', 'pdf', {})):
            with self.assertRaises(RenderError):
                svc.convert(source, target, files)
        self.assertEqual(svc.run.calls, [])                                              # refused before any container starts
        bad = FakeDocker({'ok': True, 'file': 'result.pdf', 'preview': 'preview.jpg'}, {'result.pdf': b'%PDF', 'preview.jpg': b'<html>not a picture'})
        self.assertIsNone(self.service(bad).convert('a.md', 'pdf', {'a.md': b'x'})['preview'])

    def test_the_socket_round_trip_and_who_may_call(self):
        docker = FakeDocker({'ok': True, 'file': 'result.xlsx', 'preview': 'preview.jpg'}, {'result.xlsx': b'PK\x03\x04 sheet' * 5000, 'preview.jpg': JPEG})
        # A short path: unix socket paths are limited to about 100 bytes.
        folder = tempfile.mkdtemp(prefix='lr-', dir='/tmp'); self.addCleanup(__import__('shutil').rmtree, folder, True)
        path = os.path.join(folder, 's')
        allowed = {'uid': 501}
        server = render_service.serve(self.service(docker), path, allowed_uids={501}, peer_uid=lambda sock: allowed['uid'])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        client = RenderRpc(path, timeout=10)
        out = client.convert('table.csv', 'xlsx', {'table.csv': b'a,b\n1,2\n' * 3000})
        self.assertEqual((out['data'], out['preview']), (b'PK\x03\x04 sheet' * 5000, JPEG))
        self.assertEqual(docker.seen['in'], {'table.csv': b'a,b\n1,2\n' * 3000})
        docker.result, docker.files = {'ok': False, 'error': 'A .csv file cannot be turned into .pptx'}, {}
        with self.assertRaises(RenderRefused) as caught:
            client.convert('table.csv', 'pptx', {'table.csv': b'a,b'})
        self.assertEqual(str(caught.exception), 'A .csv file cannot be turned into .pptx')
        allowed['uid'] = 1234                                                             # any other local user gets no answer at all
        with self.assertRaises(CapabilityUnavailable):
            client.convert('table.csv', 'xlsx', {'table.csv': b'a,b'})
        with self.assertRaises(CapabilityUnavailable):
            RenderRpc(os.path.join(folder, 'missing'), timeout=2).convert('a.md', 'pdf', {'a.md': b'x'})


class Workspace:
    """A gateway over an in-memory workspace."""
    def __init__(self, files):
        self.files = files

    def workspace_stat(self, path):
        from agentai_platform.lifecycle.workspace import is_program
        if path not in self.files:
            return {'reason': 'not found'}
        if is_program(path, self.files[path][:8]):
            return {'reason': 'programs and installers are not delivered'}
        return {'size': len(self.files[path])}

    def workspace_read(self, path, size):
        return self.files[path]


class Renderer:
    def __init__(self, data=b'%PDF-1.7 converted', preview=JPEG, pages=2, error=None):
        self.data, self.preview, self.pages, self.error, self.calls = data, preview, pages, error, []

    def convert(self, source, target, files, *, preview=True):
        self.calls.append((source, target, dict(files)))
        if self.error:
            raise self.error
        return {'data': self.data if target else None, 'preview': self.preview, 'pages': self.pages if target else None}


class FileToolChecks(Base):
    def tools(self, files, renderer=None, enabled=lambda account: True):
        self.events = EventService(self.store, clock=lambda: 2000000000)
        self.renderer = renderer
        return FileTools(self.store, self.artifacts, gateway_for=lambda account: Workspace(files[account]), renderer=renderer, events=self.events, enabled=enabled)

    def listed(self, account='a'):
        return {f['display_name']: f for f in self.artifacts.list_account(Principal(account, 'actor-' + account, 'customer'))['files']}

    def test_a_markdown_file_becomes_a_pdf_with_a_picture_to_check(self):
        renderer = Renderer()
        tools = self.tools({'a': {'report.md': b'# Q3\n\nGood quarter.', 'img/chart.png': b'\x89PNG chart'}}, renderer)
        text, bad, shot = tools.call('a', {'path': 'report.md', 'convert_to': 'pdf', 'name': 'Q3 report', 'include': ['img/chart.png']}, name=NAME, request_id='t-a')
        self.assertFalse(bad)
        self.assertIn('Delivered "Q3 report.pdf" (2 pages, 18 B)', text)
        self.assertEqual(base64.b64decode(shot), JPEG)
        self.assertEqual(renderer.calls, [('report.md', 'pdf', {'report.md': b'# Q3\n\nGood quarter.', 'img/chart.png': b'\x89PNG chart'})])
        made = self.listed()['Q3 report.pdf']
        self.assertEqual((made['media_type'], made['task_id'], made['project_id']), ('application/pdf', 't-a', 'p-a'))
        self.assertEqual(self.artifacts.read_preview('a', made['id'], 1), JPEG)          # kept for the Files page
        event = [e for e in self.events.events(self.a, 't-a')['events'] if e['kind'] == 'artifact'][0]
        self.assertEqual(event['payload']['name'], 'Q3 report.pdf')
        with self.store.connect() as con:                                                # recorded as the assistant's own delivery
            self.assertEqual(json.loads(con.execute("SELECT public_payload FROM events WHERE kind='artifact'").fetchone()[0])['source'], 'agent')
        # The same call again changes nothing; a changed source is a new version of the same file.
        text, bad = tools.call('a', {'path': 'report.md', 'convert_to': 'pdf', 'name': 'Q3 report'}, name=NAME, request_id='t-a')[:2]
        self.assertIn('already delivered', text); self.assertFalse(bad)
        renderer.data = b'%PDF-1.7 second'
        text = tools.call('a', {'path': 'report.md', 'convert_to': 'pdf', 'name': 'Q3 report.pdf'}, name=NAME, request_id='t-a')[0]
        self.assertIn('version 2', text)
        self.assertEqual(sorted(f['version'] for f in self.artifacts.list_account(self.a)['files']), [1, 2])

    def test_any_file_is_delivered_as_written_and_several_as_a_zip(self):
        files = {'a': {'out/sales.xlsx': b'PK\x03\x04 real sheet', 'invite.ics': b'BEGIN:VCALENDAR', 'a.txt': b'A', 'b/b.txt': b'B'}}
        tools = self.tools(files, Renderer())
        text, bad, shot = tools.call('a', {'path': 'out/sales.xlsx'}, name=NAME, request_id='t-a')
        self.assertIn('Delivered "out/sales.xlsx"', text); self.assertTrue(shot)
        self.assertEqual(self.renderer.calls[-1][1], None)                               # a picture only: the file itself is not converted
        text, bad = tools.call('a', {'path': 'invite.ics'}, name=NAME, request_id='t-a')
        self.assertIn('No preview is available', text); self.assertFalse(bad)
        text, bad = tools.call('a', {'path': 'a.txt', 'convert_to': 'zip', 'include': ['b/b.txt'], 'name': 'Both files'}, name=NAME, request_id='t-a')
        self.assertIn('Delivered "Both files.zip"', text)
        parts, _ = self.artifacts.open_version(self.a, self.listed()['Both files.zip']['id'], 1)
        with zipfile.ZipFile(io.BytesIO(self.root.read_private(parts))) as archive:
            self.assertEqual({n: archive.read(n) for n in archive.namelist()}, {'a.txt': b'A', 'b/b.txt': b'B'})
        self.assertEqual(self.listed()['invite.ics']['media_type'], 'text/calendar')
        # Asking for the format a file already has delivers it untouched.
        tools.call('a', {'path': 'out/sales.xlsx', 'convert_to': 'xlsx', 'name': 'Copy'}, name=NAME, request_id='t-a')
        self.assertEqual(self.root.read_private(self.artifacts.open_version(self.a, self.listed()['Copy.xlsx']['id'], 1)[0]), b'PK\x03\x04 real sheet')

    def test_without_the_render_service_files_still_go_out_as_written(self):
        tools = self.tools({'a': {'report.md': b'# Hi'}}, None)
        text, bad = tools.call('a', {'path': 'report.md', 'convert_to': 'pdf'}, name=NAME, request_id='t-a')
        self.assertTrue(bad); self.assertIn('not available right now', text); self.assertEqual(self.listed(), {})
        text, bad = tools.call('a', {'path': 'report.md'}, name=NAME, request_id='t-a')
        self.assertFalse(bad); self.assertIn('report.md', self.listed())

    def test_refusals_deliver_nothing_and_say_why(self):
        files = {'a': {'report.md': b'# Hi', 'tool.exe': b'MZ\x90\x00', 'fake.pdf': b'\x7fELF binary'}, 'b': {'secret.md': b'B ONLY'}}
        tools = self.tools(files, Renderer())
        cases = [
            ({'path': 'missing.md'}, 'not found'), ({'path': 'secret.md'}, 'not found'),                    # another account's file is not there at all
            ({'path': '../b/secret.md'}, 'inside your workspace'), ({'path': '/etc/passwd'}, 'inside your workspace'), ({'path': 'tmp/notes.md'}, 'inside your workspace'),
            ({'path': 'tool.exe'}, 'programs and installers'), ({'path': 'fake.pdf'}, 'programs and installers'),
            ({'path': 'report.md', 'convert_to': 'exe'}, 'must be one of'), ({'path': 'report.md', 'name': 'a/b.md'}, 'without folders'),
            ({'path': 'report.md', 'include': ['report.md']}, 'only used when converting'), ({'path': 'report.md', 'extra': 1}, 'Give a "path"'),
            ({'path': 'report.md', 'convert_to': 'pdf', 'include': ['../x']}, 'up to 20 files'), ({}, 'inside your workspace'),
        ]
        for arguments, expected in cases:
            text, bad = tools.call('a', arguments, name=NAME, request_id='t-a')[:2]
            self.assertTrue(bad, arguments); self.assertIn(expected, text, arguments); self.assertIn('Nothing was delivered', text, arguments)
        self.assertEqual(tools.call('a', {'path': 'report.md'}, name=NAME, request_id=None)[1], True)       # no admitted task behind the call
        self.assertEqual(tools.call('a', {'path': 'report.md'}, name=NAME, request_id='t-b')[1], True)      # a task of another account
        self.assertTrue(tools.call('a', {'path': 'report.md'}, lambda: True, name=NAME, request_id='t-a')[1])
        for error, expected in ((RenderRefused('The document converter could not read this file'), 'could not be converted: The document converter could not read this file'),
                                (CapabilityUnavailable('down'), 'could not be read or converted right now')):
            self.renderer.error = error
            text, bad = tools.call('a', {'path': 'report.md', 'convert_to': 'docx'}, name=NAME, request_id='t-a')
            self.assertTrue(bad); self.assertIn(expected, text)
        self.assertEqual(self.listed(), {})
        self.assertEqual(self.on_disk(), [])
        off = self.tools(files, Renderer(), enabled=lambda account: False)
        self.assertEqual(off.call('a', {'path': 'report.md'}, name=NAME, request_id='t-a'), ('Delivering files is not available.', True))

    def test_a_converted_program_or_an_oversized_result_is_not_delivered(self):
        tools = self.tools({'a': {'page.html': b'<p>x</p>'}}, Renderer(data=b'MZ\x90\x00 not a picture'))
        text, bad = tools.call('a', {'path': 'page.html', 'convert_to': 'png'}, name=NAME, request_id='t-a')[:2]
        self.assertTrue(bad); self.assertIn('Programs and installers', text)
        from agentai_platform import file_tools
        old = file_tools.MAX_FILE_BYTES
        file_tools.MAX_FILE_BYTES = 10
        self.addCleanup(setattr, file_tools, 'MAX_FILE_BYTES', old)
        self.renderer.data = b'%PDF' + b'x' * 100
        text, bad = tools.call('a', {'path': 'page.html', 'convert_to': 'pdf'}, name=NAME, request_id='t-a')[:2]
        self.assertTrue(bad); self.assertIn('the limit for one file is 50 MB', text)
        self.assertEqual(self.listed(), {})

    def test_the_relay_lists_and_routes_the_tool(self):
        class Browser:
            store = self.store
        tools = self.tools({'a': {'report.md': b'# Hi'}}, Renderer(), enabled=lambda account: account == 'a')
        relay = Relay(Browser(), files=tools)
        names = lambda account: [t['name'] for t in relay.handle(account, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools']]
        self.assertIn(NAME, names('a')); self.assertNotIn(NAME, names('b'))
        spec = [t for t in relay.handle('a', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools'] if t['name'] == NAME][0]
        self.assertEqual(set(spec['inputSchema']['properties']), {'path', 'convert_to', 'name', 'include', '_lumina_origin'})
        self.assertIn('pdf', spec['inputSchema']['properties']['convert_to']['enum'])
        refused = relay.handle('b', {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': NAME, 'arguments': {'path': 'report.md'}}})
        self.assertEqual(refused['error']['message'], 'unknown tool')
        # With no origin proof configured the relay cannot name the task, and the tool then delivers nothing.
        reply = relay.handle('a', {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': NAME, 'arguments': {'path': 'report.md'}}})
        self.assertTrue(reply['result']['isError'])
        owned = Relay(Browser(), files=tools, origin=lambda account, name, arguments: {'origin': {'session_key': 's', 'run_id': 'r', 'call_id': 'c'}, 'status': 'verified'})
        owned._owner = lambda account, origin: 't-a'
        reply = owned.handle('a', {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': NAME, 'arguments': {'path': 'report.md', 'convert_to': 'pdf', '_lumina_origin': 'f' * 32}}})
        self.assertFalse(reply['result']['isError'])
        self.assertEqual([c['type'] for c in reply['result']['content']], ['text', 'image'])
        self.assertIn('report.pdf', self.listed())


if __name__ == '__main__':
    unittest.main()
