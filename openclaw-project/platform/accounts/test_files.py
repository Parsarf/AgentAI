import contextlib
import io
import json
import os
import re
import uuid
import tempfile
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
        self.assertEqual(a.post('/v1/projects/project-a/files', '{}', content_type='application/json', secure=True).status_code, 503)
        self.assertEqual(a.get('/v1/projects/project-a/files', secure=True).status_code, 503)
        self.assertEqual(self.post(a, '/v1/artifacts/x/versions/1/ticket', {}).status_code, 503)
        self.assertEqual(a.get('/v1/artifacts/x/versions/1/download', secure=True).status_code, 503)
        self.assertEqual(self.new_client().get('/v1/projects/project-a/files', secure=True).status_code, 401)

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
        from .lifecycle import AccountStore
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
        from .lifecycle import AccountStore
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
