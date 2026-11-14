import contextlib
import io
import json
import os
import re
import uuid
import tempfile
from pathlib import Path
from django.db import connection
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.contrib.auth.models import User
from .models import Identity
from .services import token_for, consume
from .tests import AccountBoundaryTests, PASSWORD

BOUNDARY = '----agentai-test-boundary-7381'


def multipart_body(token, files):
    """Deterministic multipart body: text files only (byte-exact for tests)."""
    parts = ['--' + BOUNDARY, 'Content-Disposition: form-data; name="csrfmiddlewaretoken"', '', token]
    import json as _json
    parts += ['--' + BOUNDARY, 'Content-Disposition: form-data; name="filenames"', '',
              _json.dumps([name for name, _ in files])]
    for name, data in files:
        payload = data.decode('utf-8')
        parts += ['--' + BOUNDARY,
                  f'Content-Disposition: form-data; name="file"; filename="{name}"',
                  'Content-Type: application/octet-stream',
                  f'Content-Length: {len(data)}', '', payload]
    parts += ['--' + BOUNDARY + '--', '']
    return '\r\n'.join(parts)


class FileHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def enable_storage(self, uploads=False):
        root = tempfile.mkdtemp(prefix='agentai-files-test-')
        os.chmod(root, 0o700)
        enabled = override_settings(STORAGE_DIR=root, ARTIFACT_SIGNING_KEY=b'k' * 32,
                                    STORAGE_READY=True, UPLOADS_ENABLED=uploads)
        enabled.enable()
        self.addCleanup(enabled.disable)
        self.addCleanup(lambda: __import__('shutil').rmtree(root, ignore_errors=True))

    def multipart(self, client, path, files):
        page = client.get('/account/login/', secure=True)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        body = multipart_body(token, files)
        return client.post(path, body, content_type=f'multipart/form-data; boundary={BOUNDARY}',
                           secure=True, HTTP_REFERER='https://localhost/account/')

    def seed_task(self):
        with connection.cursor() as c:
            c.execute("INSERT INTO deployments(account_id,id,generation,state) SELECT account_id,'dx',1,'stopped' FROM projects GROUP BY account_id")
            c.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) SELECT account_id, id, 'cx', 'dx' FROM projects")
            c.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) SELECT account_id, id, 'cx', 'tx', 'completed', 0 FROM projects")

    def test_routes_fail_closed_without_storage(self):
        a = self.signed()
        self.assertEqual(self.post(a, '/v1/projects/project-a/files', {}).status_code, 503)
        self.assertEqual(a.post('/v1/projects/project-a/files', '{}', content_type='application/json', secure=True).status_code, 403)
        self.assertEqual(a.get('/v1/projects/project-a/files', secure=True).status_code, 503)
        self.assertEqual(self.post(a, '/v1/artifacts/x/versions/1/ticket', {}).status_code, 503)
        self.assertEqual(a.get('/v1/artifacts/x/versions/1/download', secure=True).status_code, 503)
        self.assertEqual(self.new_client().get('/v1/projects/project-a/files', secure=True).status_code, 401)

    def test_malformed_ids_are_a_clean_client_error_not_a_server_error(self):
        self.enable_storage()
        a = self.signed()
        for fid in ('..%2f..%2fetc', '%00', 'a' * 300, "x' OR '1'='1"):
            self.assertIn(a.get(f'/v1/projects/project-a/files/{fid}/preview', secure=True).status_code, (400, 404), fid)

    def test_upload_validation_and_ownership(self):
        self.enable_storage(uploads=True)
        a, b = self.signed('a'), self.signed('b')
        ok = self.multipart(a, '/v1/projects/project-a/files', [('notes.txt', b'hello world')])
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(ok.json()['result']['accepted'][0]['media_type'], 'text/plain')
        rejected = self.multipart(a, '/v1/projects/project-a/files', [('evil.exe', b'MZ')])
        self.assertEqual(rejected.status_code, 422)
        self.assertIn('allowlist', rejected.json()['reason'])
        self.assertEqual(self.multipart(b, '/v1/projects/project-a/files', [('x.txt', b'x')]).status_code, 404)
        listing = a.get('/v1/projects/project-a/files', secure=True).json()
        self.assertEqual(len(listing['files']), 1)
        # The account fixture seeds one placeholder artifact; it lists like any other.
        self.assertEqual(len(listing['artifacts']), 1)

    def test_upload_disabled_without_scan_capability(self):
        self.enable_storage(uploads=False)
        a = self.signed()
        response = self.multipart(a, '/v1/projects/project-a/files', [('notes.txt', b'hello')])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'uploads_not_enabled')

    def test_ticket_download_flow_single_use_and_scoped(self):
        self.enable_storage()
        a, b = self.signed('a'), self.signed('b')
        self.seed_task()
        from agentai_platform.artifacts import ArtifactService
        from agentai_platform.security import Principal
        from .store import AccountStore
        from agentai_platform.storage import RootStore
        from django.conf import settings as dj
        artifacts = ArtifactService(AccountStore(connection.settings_dict['NAME']),
                                    storage=RootStore(dj.STORAGE_DIR), signing_key=b'k' * 32)
        captured = artifacts.capture(account_id='a', project_id='project-a', task_id='tx',
                                     name='result.txt', media_type='text/plain', data=b'result body')
        minted = self.post(a, f"/v1/artifacts/{captured['artifact_id']}/versions/1/ticket", {})
        self.assertEqual(minted.status_code, 201, minted.content)
        path = minted.json()['download']['path']
        # Bearer ticket: exactly one fetch of exactly this version; replay fails.
        download = a.get(path, secure=True)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b''.join(download.streaming_content), b'result body')
        self.assertEqual(a.get(path, secure=True).status_code, 404)
        self.assertEqual(a.get('/v1/artifacts/x/versions/1/download?ticket=guess', secure=True).status_code, 404)
        self.assertEqual(self.post(b, f"/v1/artifacts/{captured['artifact_id']}/versions/1/ticket", {}).status_code, 404)

    def artifacts(self):
        from agentai_platform.artifacts import ArtifactService
        from .store import AccountStore
        from agentai_platform.storage import RootStore
        from django.conf import settings as dj
        return ArtifactService(AccountStore(connection.settings_dict['NAME']), storage=RootStore(dj.STORAGE_DIR), signing_key=b'k' * 32)

    def test_account_file_list_preview_delete_and_download_all(self):
        self.enable_storage()
        a, b = self.signed('a'), self.signed('b')
        self.seed_task()
        artifacts = self.artifacts()
        make = lambda name, media, data: artifacts.capture(account_id='a', project_id='project-a', task_id='tx', name=name, media_type=media, data=data)
        sheet = make('reports/Q3 sales.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', b'PK\x03\x04 sheet')
        note = make('note.md', 'text/markdown', b'# Hello\n<script>alert(1)</script>')
        page = make('page.html', 'text/html', b'<script>alert(1)</script>')
        picture = make('pic.png', 'image/png', b'\x89PNG\r\n\x1a\n pixels')
        names = lambda client: sorted(f['display_name'] for f in client.get('/v1/files', secure=True).json()['files'] if f['id'] != 'artifact-' + ('a' if client is a else 'b'))   # minus the fixture's own row
        listing = a.get('/v1/files', secure=True).json()
        self.assertEqual(names(a), ['note.md', 'page.html', 'pic.png', 'reports/Q3 sales.xlsx'])
        self.assertEqual(listing['used_bytes'], sum(f['size_bytes'] for f in listing['files']))
        self.assertEqual(names(b), [])
        self.assertEqual(self.new_client().get('/v1/files', secure=True).status_code, 401)
        # Previews: a picture as itself, text as plain text (never rendered), nothing for a format with no picture; always sandboxed.
        shown = a.get(f"/v1/artifacts/{picture['artifact_id']}/versions/1/preview", secure=True)
        self.assertEqual((shown.status_code, shown['Content-Type'], shown['Content-Security-Policy']), (200, 'image/png', "default-src 'none'; sandbox"))
        for made in (note, page):
            text = a.get(f"/v1/artifacts/{made['artifact_id']}/versions/1/preview", secure=True)
            self.assertEqual((text.status_code, text['Content-Type'], text['X-Content-Type-Options']), (200, 'text/plain; charset=utf-8', 'nosniff'))
        self.assertEqual(a.get(f"/v1/artifacts/{sheet['artifact_id']}/versions/1/preview", secure=True).json(), {'error': 'no_preview'})      # no render service here
        artifacts.save_preview('a', sheet['artifact_id'], 1, b'\xff\xd8\xff\xe0 first page')
        self.assertEqual(a.get(f"/v1/artifacts/{sheet['artifact_id']}/versions/1/preview", secure=True)['Content-Type'], 'image/jpeg')
        self.assertEqual(b.get(f"/v1/artifacts/{picture['artifact_id']}/versions/1/preview", secure=True).status_code, 404)
        self.assertEqual(a.get(f"/v1/artifacts/{picture['artifact_id']}/versions/9/preview", secure=True).status_code, 404)
        # A download is always a download, named by the file, whatever is in it.
        path = self.post(a, f"/v1/artifacts/{page['artifact_id']}/versions/1/ticket", {}).json()['download']['path']
        got = a.get(path, secure=True)
        self.assertEqual(b''.join(got.streaming_content), b'<script>alert(1)</script>')
        self.assertEqual((got['Content-Type'], got['Content-Disposition']), ('application/octet-stream', 'attachment; filename="page.html"'))
        path = self.post(a, f"/v1/artifacts/{sheet['artifact_id']}/versions/1/ticket", {}).json()['download']['path']
        self.assertEqual(a.get(path, secure=True)['Content-Disposition'], 'attachment; filename="Q3 sales.xlsx"')
        # Download all: one archive for the account.
        bundle = self.post(a, '/v1/files/bundle', {})
        self.assertEqual((bundle.status_code, bundle.json()['bundle']['file_count']), (201, 5))
        self.assertEqual(len(names(a)), 4)                                                  # the archive itself is not listed as a file
        # Delete: only the owner, permanently, bytes included.
        self.assertEqual(self.post(b, f"/v1/artifacts/{sheet['artifact_id']}/delete", {}).status_code, 404)
        self.assertEqual(a.get(f"/v1/artifacts/{sheet['artifact_id']}/delete", secure=True).status_code, 405)
        gone = self.post(a, f"/v1/artifacts/{sheet['artifact_id']}/delete", {})
        self.assertEqual((gone.status_code, gone.json()['deleted']['versions']), (200, 1))
        self.assertEqual(self.post(a, f"/v1/artifacts/{sheet['artifact_id']}/delete", {}).status_code, 404)
        self.assertEqual(self.post(a, f"/v1/artifacts/{sheet['artifact_id']}/versions/1/ticket", {}).status_code, 404)
        self.assertEqual(a.get(f"/v1/artifacts/{sheet['artifact_id']}/versions/1/preview", secure=True).status_code, 404)
        self.assertEqual(names(a), ['note.md', 'page.html', 'pic.png'])
        from django.conf import settings as dj
        self.assertFalse(any(sheet['artifact_id'] in str(p) for p in Path(dj.STORAGE_DIR).rglob('*')))

    def test_download_as_exports_an_answer_a_conversation_and_a_table(self):
        self.enable_storage()
        a, b = self.signed('a'), self.signed('b')
        self.seed_task()
        with connection.cursor() as c:
            c.execute("UPDATE conversations SET title='Trip plan' WHERE account_id='a'")
            c.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','cx','customer','Plan my trip')")
            c.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','cx','agent',%s)", ['# Day 1\n\nMuseum.\n\n```lumina-doc\n{\"x\":1}\n```\n\nDone.'])
            c.execute("SELECT id FROM chat_messages WHERE account_id='a' AND provenance='agent'")
            answer = str(c.fetchone()[0])
        # Markdown and text need no converter; the interface block is not part of what was written.
        one = self.post(a, '/v1/conversations/cx/export', {'format': 'md', 'message': answer})
        self.assertEqual((one.status_code, one['Content-Disposition']), (200, 'attachment; filename="Trip plan.md"'))
        self.assertEqual(one.content.decode(), '# Day 1\n\nMuseum.\n\n\n\nDone.')
        whole = self.post(a, '/v1/conversations/cx/export', {'format': 'txt'}).content.decode()
        self.assertIn('**You**\n\nPlan my trip', whole); self.assertIn('**Lumina**\n\n# Day 1', whole); self.assertNotIn('lumina-doc', whole)
        self.assertEqual(self.post(b, '/v1/conversations/cx/export', {'format': 'md'}).status_code, 404)               # not their conversation
        self.assertEqual(self.post(a, '/v1/conversations/cx/export', {'format': 'md', 'message': '999999'}).status_code, 404)
        self.assertEqual(self.post(a, '/v1/conversations/cx/export', {'format': 'exe'}).status_code, 400)
        self.assertEqual(self.post(a, '/v1/conversations/cx/export', {'format': 'pdf'}).json(), {'error': 'convert_not_available'})      # no render service configured
        table = {'format': 'xlsx', 'name': 'Prices', 'columns': ['Item', 'Price'], 'rows': [['Tea', 3.5], ['=cmd', 2]]}
        self.assertEqual(self.post(a, '/v1/export/table', table).status_code, 503)
        sent = {}
        class Renderer:
            def convert(self, source, target, files, *, preview=True):
                sent.update(source=source, target=target, files=files)
                return {'data': b'converted ' + target.encode(), 'preview': None, 'pages': None}
        from unittest import mock
        from . import wiring
        with mock.patch.object(wiring, 'renderer', lambda: Renderer()):
            pdf = self.post(a, '/v1/conversations/cx/export', {'format': 'pdf', 'message': answer})
            self.assertEqual((pdf.status_code, pdf.content, pdf['Content-Type'], pdf['Content-Disposition']), (200, b'converted pdf', 'application/pdf', 'attachment; filename="Trip plan.pdf"'))
            self.assertEqual((sent['source'], sent['target'], sent['files']), ('answer.md', 'pdf', {'answer.md': b'# Day 1\n\nMuseum.\n\n\n\nDone.'}))
            sheet = self.post(a, '/v1/export/table', table)
            self.assertEqual((sheet.status_code, sheet.content, sheet['Content-Disposition']), (200, b'converted xlsx', 'attachment; filename="Prices.xlsx"'))
            spec = json.loads(sent['files']['table.json'])
            self.assertEqual(spec['sheets'][0]['rows'], [['Tea', 3.5], ["'=cmd", 2]])           # text that looks like a formula stays text
            for bad in ({'format': 'xlsx', 'columns': [], 'rows': []}, {'format': 'xlsx', 'columns': ['a'], 'rows': [[{'x': 1}]]}, {'format': 'pdf', 'columns': ['a'], 'rows': []},
                        {'format': 'xlsx', 'columns': ['a'], 'rows': 'x'}, {'format': 'xlsx', 'columns': ['a'], 'rows': [], 'extra': 1}):
                self.assertEqual(self.post(a, '/v1/export/table', bad).status_code, 400, bad)
        self.assertEqual(self.post(self.new_client(), '/v1/export/table', table).status_code, 401)
        self.assertEqual([f['id'] for f in a.get('/v1/files', secure=True).json()['files']], ['artifact-a'])      # only the fixture's row: an export is sent back, never stored

    def test_bundle_via_form_redirect_and_accounting(self):
        self.enable_storage()
        a = self.signed()
        self.seed_task()
        # Fresh project created through the API: no fixture artifacts involved.
        created = self.post(a, '/v1/projects', {'name': 'Bundle project'})
        self.assertEqual(created.status_code, 201, created.content)
        project_id = created.json()['project']['id']
        with connection.cursor() as c:
            c.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','dx2',1,'stopped')")
            c.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a',%s,'bxc','dx2')", [project_id])
            c.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a',%s,'bxc','tbx','completed',0)", [project_id])
        response = self.post(a, f'/v1/projects/{project_id}/bundle', {})
        self.assertEqual(response.status_code, 409)  # no results yet -> no empty bundle
        from agentai_platform.artifacts import ArtifactService
        from .store import AccountStore
        from agentai_platform.storage import RootStore
        from django.conf import settings as dj
        artifacts = ArtifactService(AccountStore(connection.settings_dict['NAME']),
                                    storage=RootStore(dj.STORAGE_DIR), signing_key=b'k' * 32)
        artifacts.capture(account_id='a', project_id=project_id, task_id='tbx',
                          name='result.txt', media_type='text/plain', data=b'body')
        response = self.post(a, f'/v1/projects/{project_id}/bundle', {})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['bundle']['file_count'], 1)
        listing = a.get(f'/v1/projects/{project_id}/files', secure=True).json()
        self.assertEqual(len(listing['artifacts']), 2)  # result + bundle
        self.assertTrue(listing['artifacts'][-1]['display_name'].endswith('.zip'))

    def test_chat_page_lists_files_section(self):
        self.enable_storage()
        a = self.signed()
        page = a.get('/account/chat/?project=project-a', secure=True)
        self.assertContains(page, 'Files &amp; results')
        self.assertNotContains(page, 'Upload files (10MiB each')  # scan capability off
