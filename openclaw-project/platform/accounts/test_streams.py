import json
import re
from unittest.mock import patch
from django.db import connection
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from .tests import AccountBoundaryTests, PASSWORD


class StreamHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def _service(self):
        from agentai_platform.events import EventService
        from .lifecycle import AccountStore
        return EventService(AccountStore(connection.settings_dict['NAME']))

    def test_events_endpoint_scoped_and_validated(self):
        a, b = self.signed('a'), self.signed('b')
        self.assertEqual(self.new_client().get('/v1/tasks/task-a/events', secure=True).status_code, 401)
        service = self._service()
        service.append('a', 'task-a', 'task_started', {'summary': 'go'})
        ok = a.get('/v1/tasks/task-a/events', secure=True).json()
        self.assertEqual([e['kind'] for e in ok['events']], ['task_started'])
        self.assertFalse(ok['live_streaming'])
        self.assertEqual(b.get('/v1/tasks/task-a/events', secure=True).status_code, 404)
        self.assertEqual(a.get('/v1/tasks/task-a/events?after=bad', secure=True).status_code, 400)
        self.assertEqual(a.get('/v1/tasks/task-b/events', secure=True).status_code, 404)

    def test_sse_stream_auth_cap_and_events(self):
        a = self.signed()
        self.assertEqual(a.post('/v1/tasks/task-a/stream', '{}', content_type='application/json', secure=True).status_code, 405)
        self.assertEqual(self.new_client().get('/v1/tasks/task-a/stream', secure=True).status_code, 401)
        from agentai_platform.security import Principal
        service = self._service()
        service.append('a', 'task-a', 'task_started', {'summary': 'go'})
        service.append('a', 'task-a', 'progress', {'summary': 'working', 'step': 1})
        principal = Principal('a', str(User.objects.get(email='a@example.invalid').pk), 'customer')
        # Three streams already open for the account: the fourth is rejected.
        for n in range(3):
            service.open_stream(principal, 'task-a', f'pre-{n}')
        response = a.get('/v1/tasks/task-a/stream', secure=True)
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response['Retry-After'])
        service.close_stream('pre-0')
        response = a.get('/v1/tasks/task-a/stream', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        chunks = []
        for chunk in response.streaming_content:
            chunks.append(chunk.decode())
            if len(chunks) >= 3:
                break  # stop early: generator close triggers cleanup
        open_chunk = chunks[0]
        self.assertIn('event: open', open_chunk)
        event_chunk = ''.join(chunks[1:])
        self.assertIn('event: task_event', event_chunk)
        self.assertIn('"kind": "task_started"', event_chunk)
        self.assertIn('id: 1', event_chunk)
        # Cross-account subscriber gets nothing: b cannot even read the task.
        self.assertEqual(self.signed('b').get('/v1/tasks/task-a/events', secure=True).status_code, 404)

    def test_timeline_renders_on_chat_page(self):
        a = self.signed()
        service = self._service()
        actor = str(User.objects.get(email='a@example.invalid').pk)
        with connection.cursor() as c:
            c.execute("INSERT INTO customer_requests(sequence,account_id,id,actor_id,project_id,"
                      "idempotency_key,payload_hash,message,state,created_epoch,conversation_id)"
                      " VALUES (1,'a','req-ev',?,'project-a','evkey',?,'do the thing','waiting',100,'conversation-a')",
                      [actor, '0' * 64])
            c.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd)"
                      " VALUES ('a','project-a','conversation-a','req-ev','running',0)")
        service.append('a', 'req-ev', 'task_started', {'summary': 'dispatched'})
        service.append('a', 'req-ev', 'result', {'summary': 'all done'})
        page = a.get('/account/chat/?project=project-a&conversation=conversation-a', secure=True)
        self.assertContains(page, 'task_started')
        self.assertContains(page, 'dispatched')
        self.assertContains(page, 'all done')
