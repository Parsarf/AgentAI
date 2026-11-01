"""Authenticated HTTP contract for registry documents and interaction events."""
import json
from django.db import connection
from django.test import TestCase
from . import test_chat as fixtures


class RegistryDocumentHTTP(TestCase):
    setUp = fixtures.ChatHTTPChecks.setUp
    new_client = fixtures.ChatHTTPChecks.new_client
    post = fixtures.ChatHTTPChecks.post
    project = fixtures.ChatHTTPChecks.project
    conversation = fixtures.ChatHTTPChecks.conversation

    def artifact(self):
        conversation = self.conversation()
        spec = {'version': '1.0', 'responseId': 'sample', 'type': 'document', 'blocks': [{'id': 'next', 'type': 'button_group', 'props': {'buttons': [{'id': 'continue', 'label': 'Continue', 'action': {'kind': 'agent.request', 'message': 'Continue the comparison'}}]}}]}
        with connection.cursor() as con:
            con.execute("INSERT INTO data_blocks(account_id,id,conversation_id,kind,spec_json,created_epoch) VALUES (%s,'artifact-http',%s,'document',%s,1)", [self.account_ids[0], conversation, json.dumps(spec)])
        return conversation, '/v1/genui/artifacts/artifact-http'

    def test_registry_state_events_and_cross_account_boundaries(self):
        conversation, path = self.artifact(); a, b = self.clients
        registry = a.get('/v1/genui/registry', secure=True)
        self.assertEqual(registry.status_code, 200)
        detail = a.get('/v1/genui/registry?component=calculator', secure=True)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(a.get('/v1/genui/registry?component=script', secure=True).status_code, 404)
        state = {'version': 1, 'state_revision': 1, 'state': {'next': {'selected': 'continue'}}}
        self.assertEqual(self.post(b, path + '/state', state).status_code, 404)
        self.assertEqual(self.post(a, path + '/state', state).status_code, 200)
        self.assertEqual(self.post(a, path + '/state', state).status_code, 409)
        event = {'id': 'http-event-1', 'node_id': 'next', 'action_id': 'continue', 'version': 1, 'values': {}}
        self.assertEqual(self.post(b, path + '/events', event).status_code, 404)
        first = self.post(a, path + '/events', event)
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(self.post(a, path + '/events', event).json(), first.json())
        self.assertEqual(self.post(a, path + '/events', dict(event, id='http-event-2', version=2)).status_code, 409)
        self.assertEqual(self.post(a, path + '/events', dict(event, id='http-event-3', action_id='forged')).status_code, 400)
        listed = a.get(f'/v1/conversations/{conversation}/blocks', secure=True).json()['blocks'][0]
        self.assertEqual(listed['state']['next']['selected'], 'continue')
        self.assertEqual(listed['state_revision'], 3)           # the answer itself is recorded: which button, and that the component is now locked
        self.assertEqual((listed['state']['next']['chosen'], bool(listed['state']['next']['answered'])), ('continue', True))
        self.assertEqual(a.post(path + '/events', json.dumps(event), content_type='application/json', secure=True).status_code, 403)

    def test_updates_report_validation_errors_and_preserve_original_data(self):
        conversation, path = self.artifact(); a = self.clients[0]
        invalid = {'version': 1, 'document': {'version': '1.0', 'responseId': 'update', 'blocks': [{'id': 'bad', 'type': 'script', 'props': {}}]}}
        result = self.post(a, path + '/update', invalid)
        self.assertEqual(result.status_code, 400)
        self.assertIn('detail', result.json())
        listed = a.get(f'/v1/conversations/{conversation}/blocks', secure=True).json()['blocks'][0]
        self.assertEqual(listed['version'], 1)
        self.assertEqual(listed['spec']['blocks'][0]['id'], 'next')

    def test_file_resolution_is_document_project_and_mime_scoped(self):
        import tempfile
        from django.test import override_settings
        from agentai_platform.artifacts import ArtifactService
        from agentai_platform.storage import RootStore
        from .lifecycle import AccountStore
        conversation, path = self.artifact(); a, b = self.clients
        project = self.project()
        with connection.cursor() as con:
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES (%s,%s,%s,'ui-file-task','completed',1)", [self.account_ids[0], project, conversation])
        with tempfile.TemporaryDirectory() as root, override_settings(STORAGE_DIR=root, STORAGE_READY=True, ARTIFACT_SIGNING_KEY=b'k' * 32):
            service = ArtifactService(AccountStore(connection.settings_dict['NAME']), storage=RootStore(root), signing_key=b'k' * 32)
            service.capture(account_id=self.account_ids[0], project_id=project, task_id='ui-file-task', name='sample.png', media_type='image/png', data=b'\x89PNG\r\n\x1a\nfixture')
            service.capture(account_id=self.account_ids[0], project_id=project, task_id='ui-file-task', name='active.html', media_type='text/html', data=b'<script>danger()</script>')
            spec = {'version': '1.0', 'responseId': 'media', 'blocks': [{'id': 'image', 'type': 'image', 'props': {'assetRef': 'file:sample.png', 'alt': 'Sample'}}, {'id': 'active', 'type': 'file_attachment', 'props': {'assetRef': 'file:active.html', 'label': 'Active file'}}]}
            with connection.cursor() as con:
                con.execute("UPDATE data_blocks SET spec_json=%s WHERE id='artifact-http'", [json.dumps(spec)])
            image = a.get(path + '/asset?path=sample.png', secure=True)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(b''.join(image.streaming_content), b'\x89PNG\r\n\x1a\nfixture')
            self.assertEqual(image['X-Content-Type-Options'], 'nosniff')
            self.assertIn('sandbox', image['Content-Security-Policy'])
            self.assertEqual(b.get(path + '/asset?path=sample.png', secure=True).status_code, 404)
            self.assertEqual(a.get(path + '/asset?path=unreferenced.png', secure=True).status_code, 404)
            self.assertEqual(a.get(path + '/asset?path=../sample.png', secure=True).status_code, 400)
            self.assertEqual(a.get(path + '/asset?path=active.html', secure=True).status_code, 404)
            download = a.get(path + '/asset?path=active.html&download=1', secure=True)
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download['Content-Type'], 'application/octet-stream')
            self.assertIn('attachment', download['Content-Disposition'])
            download.close()

    def test_diagnostics_are_scoped_csrf_protected_and_cannot_contain_answers(self):
        from .models import Audit
        _, path = self.artifact(); a, b = self.clients
        payload = {'version': 1, 'kind': 'save_failed', 'category': 'conflict'}
        self.assertEqual(self.post(b, path + '/diagnostics', payload).status_code, 404)
        self.assertEqual(self.post(a, path + '/diagnostics', dict(payload, category='secret answer')).status_code, 400)
        self.assertEqual(self.post(a, path + '/diagnostics', dict(payload, values={'secret': 'private'})).status_code, 400)
        self.assertEqual(a.post(path + '/diagnostics', json.dumps(payload), content_type='application/json', secure=True).status_code, 403)
        self.assertEqual(self.post(a, path + '/diagnostics', payload).status_code, 202)
        self.assertEqual(Audit.objects.filter(action='genui.save_failed.conflict', account_id=self.account_ids[0]).count(), 1)

    def test_invalid_submitted_fields_return_errors_without_queuing_work(self):
        conversation, path = self.artifact(); a = self.clients[0]
        spec = {'version': '1.0', 'responseId': 'form', 'blocks': [{'id': 'form', 'type': 'form', 'props': {'fields': [{'id': 'quantity', 'label': 'Quantity', 'type': 'number', 'min': 1, 'max': 20}], 'submit': {'label': 'Calculate', 'action': {'kind': 'agent.request', 'message': 'Calculate total'}}}}]}
        with connection.cursor() as con:
            con.execute("UPDATE data_blocks SET spec_json=%s WHERE id='artifact-http'", [json.dumps(spec)])
        payload = {'id': 'bad-values', 'node_id': 'form', 'action_id': 'submit', 'version': 1, 'values': {'quantity': 100}}
        response = self.post(a, path + '/events', payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.json()['field_errors'])
        self.assertNotIn('100', json.dumps(response.json()))
        with connection.cursor() as con:
            con.execute('SELECT count(*) FROM gen_artifact_events WHERE account_id=%s', [self.account_ids[0]])
            self.assertEqual(con.fetchone()[0], 0)
