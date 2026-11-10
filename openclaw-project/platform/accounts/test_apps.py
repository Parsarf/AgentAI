from unittest.mock import patch
from django.test import TestCase
from . import test_files
from . import files
from agentai_platform.apps import application, delivery_prompt


class AppHTTPChecks(TestCase):
    # Reuse setup helpers without inheriting and rerunning unrelated upload/bundle tests.
    new_client = test_files.FileHTTPChecks.new_client
    post = test_files.FileHTTPChecks.post
    signed = test_files.FileHTTPChecks.signed
    setUp = test_files.FileHTTPChecks.setUp
    enable_storage = test_files.FileHTTPChecks.enable_storage
    seed_task = test_files.FileHTTPChecks.seed_task

    def test_app_source_is_owned_and_versioned(self):
        self.enable_storage()
        a, b = self.signed('a'), self.signed('b')
        self.seed_task()
        artifacts = files._services()[3]
        saved = artifacts.capture(account_id='a', project_id='project-a', task_id='tx', name='calculator.py', media_type='text/x-python', data=b'print(2+3)')
        url = f"/v1/artifacts/{saved['artifact_id']}/versions/1/app"
        response = a.get(url, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['app'], {'version': 1, 'title': 'calculator.py', 'runtime': 'python', 'code': 'print(2+3)'})
        self.assertEqual(b.get(url, secure=True).status_code, 404)
        self.assertEqual(self.new_client().get(url, secure=True).status_code, 401)
        self.assertEqual(a.get(url.replace('/1/app', '/2/app'), secure=True).status_code, 404)
        bad = artifacts.capture(account_id='a', project_id='project-a', task_id='tx', name='data.txt', media_type='text/plain', data=b'hello')
        self.assertEqual(a.get(f"/v1/artifacts/{bad['artifact_id']}/versions/1/app", secure=True).status_code, 422)

    def test_player_is_sandboxed_even_when_opened_directly(self):
        response = self.signed().get('/v1/apps/player', secure=True)
        self.assertEqual(response.status_code, 200)
        policy = response['Content-Security-Policy']
        self.assertIn('sandbox allow-scripts;', policy)
        self.assertNotIn('allow-same-origin', policy)
        self.assertIn("frame-ancestors 'self'", policy)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(self.new_client().get('/v1/apps/player', secure=True).status_code, 401)

    def test_manifest_validation_and_delivery_guidance(self):
        for runtime in ('html', 'python', 'javascript'):
            self.assertEqual(application({'version': 1, 'title': 'Test', 'runtime': runtime, 'code': 'hello'})['runtime'], runtime)
        with self.assertRaises(ValueError):
            application({'version': 1, 'title': 'Test', 'runtime': 'shell', 'code': 'rm'})
        self.assertIn('lumina-app', delivery_prompt())
        from agentai_platform.lifecycle.cell_config import WORKSPACE_RULES
        self.assertIn(delivery_prompt(), WORKSPACE_RULES)
        for value in (None, [], {'version': True}, {'version': 1, 'title': 'x', 'runtime': [], 'code': 'x'}):
            with self.assertRaises(ValueError):
                application(value)

    def test_missing_corrupt_and_oversized_sources_fail_without_running_anything(self):
        self.enable_storage()
        a = self.signed('a')
        self.seed_task()
        artifacts = files._services()[3]
        saved = artifacts.capture(account_id='a', project_id='project-a', task_id='tx', name='app.py', media_type='text/plain', data=b'print(1)')
        url = f"/v1/artifacts/{saved['artifact_id']}/versions/1/app"
        with patch('agentai_platform.storage.RootStore.read_private', side_effect=FileNotFoundError):
            self.assertEqual(a.get(url, secure=True).status_code, 404)
        with patch('agentai_platform.storage.RootStore.read_private', side_effect=OSError):
            self.assertEqual(a.get(url, secure=True).status_code, 503)
        with patch('agentai_platform.storage.RootStore.read_private', return_value=b'changed source') as read:
            response = a.get(url, secure=True)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()['error'], 'invalid_app_source')
            self.assertEqual(read.call_args.kwargs['max_bytes'], 512 * 1024)
        with patch('agentai_platform.storage.RootStore.read_private', side_effect=ValueError('content exceeds bound')):
            self.assertEqual(a.get(url, secure=True).status_code, 422)

    def test_only_the_player_has_a_framing_exception(self):
        a = self.signed('a')
        self.assertEqual(a.get('/v1/apps/player', secure=True)['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(a.get('/v1/app', secure=True)['X-Frame-Options'], 'DENY')
        self.assertEqual(self.new_client().get('/v1/apps/player', secure=True)['X-Frame-Options'], 'DENY')

