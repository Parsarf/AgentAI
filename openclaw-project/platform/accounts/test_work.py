"""The task-state routes over HTTP: scoped to the signed-in account, cursor reads, and the push ticket."""
import json
import tempfile
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from agentai_platform.live import ticket as live_ticket
from .tests import AccountBoundaryTests


class WorkHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def request(self, account, request_id, message='Find flights'):
        actor = str(User.objects.get(email=f'{account}@example.invalid').pk)
        with connection.cursor() as c:
            c.execute("""INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,intent)
                VALUES (%s,%s,%s,%s,%s,%s,'h',%s,'waiting',1700000000,'chat')""", [account, request_id, actor, 'project-' + account, 'conversation-' + account, 'k-' + request_id, message])

    def test_listing_and_detail_are_scoped_and_answer_unchanged_when_the_tab_is_current(self):
        a, b = self.signed('a'), self.signed('b')
        self.assertEqual(self.new_client().get('/v1/work', secure=True).status_code, 401)
        rid = 'a' * 32
        self.request('a', rid)
        listing = a.get('/v1/work', secure=True).json()
        self.assertEqual([(t['id'], t['phase'], t['title']) for t in listing['tasks']], [(rid, 'queued', 'Find flights')])
        self.assertEqual(a.get('/v1/work?rev=' + listing['rev'], secure=True).json(), {'rev': listing['rev'], 'unchanged': True})
        self.assertEqual(b.get('/v1/work', secure=True).json()['tasks'], [])
        detail = a.get(f'/v1/work/{rid}', secure=True).json()
        self.assertEqual((detail['task']['id'], detail['rows'], detail['cursor']), (rid, [], 0))
        self.assertTrue(a.get(f'/v1/work/{rid}?after=0&rev=' + detail['task']['rev'], secure=True).json()['unchanged'])
        self.assertEqual(b.get(f'/v1/work/{rid}', secure=True).status_code, 404)
        self.assertEqual(a.get(f'/v1/work/{rid}?after=x', secure=True).status_code, 400)
        self.assertEqual(a.get('/v1/work/' + 'f' * 32, secure=True).status_code, 404)

    def test_the_push_ticket_needs_a_session_and_a_configured_gateway_and_names_the_member(self):
        a = self.signed('a')
        self.assertEqual(self.post(self.new_client(), '/v1/work/ticket', {}).status_code, 401)
        self.assertEqual(self.post(a, '/v1/work/ticket', {}).status_code, 404)                 # no gateway on this server: the app polls
        with tempfile.NamedTemporaryFile() as f:
            f.write(b's' * 40); f.flush()
            with override_settings(LIVE_SECRET_FILE=f.name, PUSH_PATH='/v1/push'):
                out = self.post(a, '/v1/work/ticket', {}).json()
                self.assertEqual((out['path'], out['expires_in']), ('/v1/push', live_ticket.WORK_TTL_SECONDS))
                self.assertEqual(live_ticket.verify_work(b's' * 40, out['ticket']), ('a', str(User.objects.get(email='a@example.invalid').pk)))
