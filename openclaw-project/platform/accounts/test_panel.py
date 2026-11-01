import json
import tempfile
from unittest import mock
from django.test import TestCase, override_settings
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.budget import BudgetDenied
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.live import ticket as live_ticket
from agentai_platform.panel import ticket as pt
from agentai_platform.security import NotFound
from .tests import AccountBoundaryTests

SECRET = b'p' * 48
ORIGIN = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'
DEVICE = 'a1b2c3d4e5f60718'
RID = 'c' * 32
CONNECTED = {'allowed': True, 'use': True, 'connected': True, 'devices': [{'device_id': DEVICE, 'connected': True}]}


class FakeRpc:
    def __init__(self, state=CONNECTED, down=False):
        self.state, self.down, self.calls = state, down, []

    def __call__(self, op, **params):
        self.calls.append(op)
        if self.down:
            raise CapabilityUnavailable('down')
        return self.state


class FakeService:
    """Stands in for ChatService where a test needs a particular run state; the real one is covered in tests/test_panel_chat.py."""
    def __init__(self, live=True, request=None):
        self.live, self.sent, self.cancelled, self.send_error = live, [], [], None
        self.request = request or {'id': RID, 'state': 'running', 'paused': 0, 'outcome': None}

    def conversation(self, principal, conversation_id):
        if conversation_id != 'conversation-a' or principal.account_id != 'a':
            raise NotFound('unavailable')
        return {'id': conversation_id}

    def panel_view(self, principal, conversation_id, *, limit=30):
        return {'conversation_id': conversation_id, 'messages': [{'id': 1, 'request_id': RID, 'provenance': 'customer', 'content': 'hello', 'created_at': 'now', 'surface': 'panel'}],
                'request': self.request, 'live': self.live, 'live_request_id': RID if self.live else None}

    def send(self, principal, **kwargs):
        if self.send_error:
            raise self.send_error
        self.sent.append((principal, kwargs))
        return {'id': RID}

    def cancel(self, principal, request_id):
        self.cancelled.append((principal.account_id, request_id))
        return {}

    def task(self, principal, request_id):
        return {'id': request_id, 'conversation_id': 'conversation-a' if request_id == RID else 'conversation-other'}


class PanelBase(TestCase):
    """The settings, the signed-in-style helpers and the ticket/call helpers both groups of checks use. Has no tests of its own."""
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed

    def setUp(self):
        AccountBoundaryTests.setUp(self)
        key = tempfile.NamedTemporaryFile(); key.write(SECRET); key.flush(); self.addCleanup(key.close)
        cm = override_settings(PANEL_ORIGINS=[ORIGIN], PANEL_SECRET_FILE=key.name); cm.enable(); self.addCleanup(cm.disable)
        self.actor = str(self.users['a'].pk)

    def ticket(self, account='a', actor=None, conversation='conversation-a', device=DEVICE, now=None):
        return pt.mint(SECRET, account, actor or self.actor, conversation, device, **({'now': now} if now else {}))

    def call(self, method, path, ticket='default', origin=ORIGIN, body=None, raw=None):
        client = self.new_client()
        headers = {}
        if origin is not None: headers['HTTP_ORIGIN'] = origin
        if ticket == 'default': ticket = self.ticket()
        if ticket: headers['HTTP_AUTHORIZATION'] = 'Panel ' + ticket
        if method == 'GET': return client.get(path, secure=True, **headers)
        if method == 'OPTIONS': return client.options(path, secure=True, **headers)
        data = raw if raw is not None else json.dumps(body if body is not None else {})
        return client.post(path, data, content_type='application/json', secure=True, **headers)


class PanelEndpointChecks(PanelBase):
    def setUp(self):
        super().setUp()
        self.rpc, self.svc = FakeRpc(), FakeService()
        for target, value in (('accounts.panel.BrowseRpc', lambda account, path: self.rpc), ('accounts.panel.service', lambda: self.svc)):
            p = mock.patch(target, value); p.start(); self.addCleanup(p.stop)

    # ---- the feature is off, or closed to strangers
    def test_off_without_a_key_or_an_origin(self):
        with override_settings(PANEL_ORIGINS=[]):
            self.assertEqual(self.call('GET', '/v1/panel/state').status_code, 404)
        with override_settings(PANEL_SECRET_FILE='/nonexistent'):
            self.assertEqual(self.call('GET', '/v1/panel/state').status_code, 404)
        with tempfile.NamedTemporaryFile() as short:
            short.write(b'k' * 10); short.flush()
            with override_settings(PANEL_SECRET_FILE=short.name):
                self.assertEqual(self.call('GET', '/v1/panel/state').status_code, 404)

    def test_only_our_extension_origin_may_call(self):
        for origin in [None, '', 'https://evil.example', 'https://getlumina.pro', 'chrome-extension://zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz']:
            for method, path in [('GET', '/v1/panel/state'), ('POST', '/v1/panel/send'), ('OPTIONS', '/v1/panel/send')]:
                r = self.call(method, path, origin=origin, body={'message': 'x', 'key': 'abcdefgh'})
                self.assertEqual(r.status_code, 403, (origin, path))
                self.assertNotIn('Access-Control-Allow-Origin', r)

    def test_preflight_answers_for_our_origin_without_credentials(self):
        r = self.call('OPTIONS', '/v1/panel/send', ticket=None)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['Access-Control-Allow-Origin'], ORIGIN)
        self.assertIn('Authorization', r['Access-Control-Allow-Headers'])
        self.assertNotIn('Access-Control-Allow-Credentials', r)
        self.assertEqual(self.rpc.calls, [])

    # ---- the ticket is the only credential
    def test_a_missing_bad_expired_or_foreign_ticket_is_refused(self):
        wrong_key = pt.mint(b'q' * 48, 'a', self.actor, 'conversation-a', DEVICE)
        for t in ['', None, 'garbage', wrong_key, live_ticket.mint(SECRET, 'a', RID), self.ticket(now=lambda: 1_000)]:
            r = self.call('GET', '/v1/panel/state', ticket=t)
            self.assertEqual((r.status_code, r.json()), (401, {'error': 'ticket'}), t)
        self.assertEqual(self.rpc.calls, [])

    def test_a_signed_in_session_cookie_alone_gets_nothing(self):
        client = self.signed('a')
        r = client.get('/v1/panel/state', secure=True, HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 401)

    def test_the_ticket_cannot_reach_another_account_person_or_conversation(self):
        self.assertEqual(self.call('GET', '/v1/panel/state', ticket=self.ticket(account='b', conversation='conversation-b')).status_code, 404)
        self.assertEqual(self.call('GET', '/v1/panel/state', ticket=self.ticket(account='a', conversation='conversation-b')).status_code, 404)

    def test_responses_set_no_cookie(self):
        r = self.call('GET', '/v1/panel/state')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.cookies)

    # ---- the computer must be there
    def test_state_needs_that_exact_computer_connected_and_the_choice_on(self):
        for state in [{**CONNECTED, 'use': False}, {**CONNECTED, 'allowed': False}, {**CONNECTED, 'devices': [{'device_id': DEVICE, 'connected': False}]},
                      {**CONNECTED, 'devices': [{'device_id': 'b' * 16, 'connected': True}]}, {**CONNECTED, 'devices': []}]:
            self.rpc.state = state
            r = self.call('GET', '/v1/panel/state')
            self.assertEqual((r.status_code, r.json()), (409, {'error': 'browser_off'}), state)

    def test_writes_are_refused_when_the_computer_is_gone_and_nothing_is_sent(self):
        self.rpc.state = {**CONNECTED, 'devices': [{'device_id': DEVICE, 'connected': False}]}
        self.assertEqual(self.call('POST', '/v1/panel/send', body={'message': 'hi', 'key': 'abcdefgh'}).status_code, 409)
        self.assertEqual(self.call('POST', '/v1/panel/stop').status_code, 409)
        self.assertEqual((self.svc.sent, self.svc.cancelled), ([], []))

    def test_service_away_is_a_clear_503(self):
        self.rpc.down = True
        r = self.call('GET', '/v1/panel/state')
        self.assertEqual((r.status_code, r.json()), (503, {'error': 'unavailable_now'}))
        self.assertEqual(r['Access-Control-Allow-Origin'], ORIGIN)

    # ---- reading
    def test_state_returns_plain_fields_for_this_conversation(self):
        r = self.call('GET', '/v1/panel/state')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['live'], True)
        self.assertEqual(data['messages'], [{'id': 1, 'role': 'customer', 'text': 'hello', 'surface': 'panel', 'at': 'now'}])
        self.assertEqual(data['request'], {'id': RID, 'state': 'running', 'paused': False, 'outcome': None})
        self.assertEqual(r['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(r['Cache-Control'], 'no-store')

    def test_events_are_this_conversations_only_and_trimmed_to_public_fields(self):
        feed = {'task_state': 'running', 'events': [{'sequence': 4, 'kind': 'tool', 'source': 'worker', 'created_at': 't', 'payload': {'summary': 'Opened a page', 'tool': 'browser', 'secret': 'x', 'ref': 'r', 'status': 'ok'}}]}
        with mock.patch('accounts.panel.EventService') as events:
            events.return_value.events.return_value = feed
            r = self.call('GET', f'/v1/panel/events?request={RID}&after=3&limit=50')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['events'], [{'sequence': 4, 'kind': 'tool', 'payload': {'summary': 'Opened a page', 'status': 'ok', 'tool': 'browser'}}])
            self.assertEqual(events.return_value.events.call_args.kwargs, {'after': 3, 'limit': 50})
            self.assertEqual(self.call('GET', f'/v1/panel/events?request={"d" * 32}').status_code, 404)       # a run of some other conversation
            for query in ['', '?request=nope', f'?request={RID}&after=-1', f'?request={RID}&limit=0', f'?request={RID}&limit=101', f'?request={RID}&after=x']:
                self.assertEqual(self.call('GET', '/v1/panel/events' + query).status_code, 400, query)

    # ---- writing
    def test_send_steers_this_conversation_and_labels_the_message(self):
        r = self.call('POST', '/v1/panel/send', body={'message': 'also check the price', 'key': 'abcdefgh1234'})
        self.assertEqual((r.status_code, r.json()), (202, {'ok': True, 'request': RID}))
        principal, kwargs = self.svc.sent[0]
        self.assertEqual((principal.account_id, principal.actor_id, principal.role), ('a', self.actor, 'customer'))
        self.assertEqual((kwargs['conversation_id'], kwargs['message'], kwargs['key'], kwargs['surface'], kwargs['mode']), ('conversation-a', 'also check the price', 'abcdefgh1234', 'panel', 'auto'))

    def test_send_never_starts_a_new_task_when_no_run_is_going(self):
        self.svc.live = False
        r = self.call('POST', '/v1/panel/send', body={'message': 'hello', 'key': 'abcdefgh1234'})
        self.assertEqual((r.status_code, r.json()), (409, {'error': 'no_active_run'}))
        self.assertEqual(self.svc.sent, [])

    def test_send_rejects_bad_bodies_and_any_attempt_to_pick_a_conversation(self):
        good = {'message': 'hi', 'key': 'abcdefgh1234'}
        for body in [{**good, 'conversation_id': 'conversation-b'}, {**good, 'goal': True}, {'message': 'hi'}, {'key': 'abcdefgh1234'}, {**good, 'message': 5}, {**good, 'key': 'bad key!'}, {**good, 'key': 'short'}]:
            self.assertEqual(self.call('POST', '/v1/panel/send', body=body).status_code, 400, body)
        for raw in ['not json', '[]', '"x"']:
            self.assertEqual(self.call('POST', '/v1/panel/send', raw=raw).status_code, 400, raw)
        self.assertEqual(self.call('POST', '/v1/panel/send', raw=json.dumps({**good, 'message': 'x' * 25_000})).status_code, 400)
        self.assertEqual(self.svc.sent, [])

    def test_send_maps_the_chat_services_refusals(self):
        body = {'message': 'hi', 'key': 'abcdefgh1234'}
        self.svc.send_error = Conflict('x')
        self.assertEqual(self.call('POST', '/v1/panel/send', body=body).json(), {'error': 'request_conflict'})
        self.svc.send_error = ValueError('x')
        self.assertEqual(self.call('POST', '/v1/panel/send', body=body).status_code, 400)
        self.svc.send_error = BudgetDenied('queue_full')
        r = self.call('POST', '/v1/panel/send', body=body)
        self.assertEqual((r.status_code, r.json()['error']), (402, 'budget_denied'))

    def test_stop_cancels_the_running_request_of_this_conversation(self):
        r = self.call('POST', '/v1/panel/stop')
        self.assertEqual((r.status_code, r.json()), (202, {'ok': True}))
        self.assertEqual(self.svc.cancelled, [('a', RID)])
        self.svc.live = False
        self.assertEqual(self.call('POST', '/v1/panel/stop').status_code, 409)

    def test_wrong_method_is_refused_with_cors_headers(self):
        r = self.call('POST', '/v1/panel/state')
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(self.call('GET', '/v1/panel/send').status_code, 405)

    def test_the_panel_is_metered_by_account(self):
        codes = [self.call('POST', '/v1/panel/send', body={'message': 'x', 'key': 'abcdefgh1234'}).status_code for _ in range(32)]
        self.assertEqual(codes[:30], [202] * 30)
        self.assertEqual(codes[30:], [429, 429])

    def test_a_flood_of_forged_tickets_from_one_address_is_limited(self):
        codes = {self.call('GET', '/v1/panel/state', ticket='forged').status_code for _ in range(605)}
        self.assertIn(429, codes)


class PanelEndToEndChecks(PanelBase):
    """The device side is real here: the worker's PanelOffer asks the browse service over its socket, the service relays to the connected computer's link, and the ticket that
    arrives there is what the panel then uses against the endpoints. Only the chat service is a stand-in."""
    def setUp(self):
        import os, threading
        from pathlib import Path
        from agentai_platform.browse import devices as dv, service as svc
        from agentai_platform.browse.client import BrowseRpc
        from agentai_platform.panel.offer import PanelOffer
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store, self.hub = dv.DeviceStore(Path(self.tmp.name) / 'd.json'), dv.DeviceHub()
        self.store.set_wants_local('a', True)
        device = self.store.redeem(self.store.pair('a'), 'Mac')
        self.device = device['device_id']
        self.sent = []
        class Conn:
            def send_text(conn, text): self.sent.append(json.loads(text))
            def close(conn, code=1000, reason=''): pass
        self.link = self.hub.attach('a', self.device, Conn())
        service = svc.BrowseService(spawn=lambda *a: None, root=self.tmp.name, jev_mode='off', devices=dv.DeviceDesk(self.store, self.hub))
        path = os.path.join(self.tmp.name, 'b.sock')
        server = svc.serve(service, path, allowed_uids={os.getuid()}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=server.serve_forever, daemon=True).start(); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        override = override_settings(BROWSE_SOCKET=path); override.enable(); self.addCleanup(override.disable)
        self.svc = FakeService()
        p = mock.patch('accounts.panel.service', lambda: self.svc); p.start(); self.addCleanup(p.stop)
        self.offer = PanelOffer(lambda: SECRET, lambda account: BrowseRpc(account, path))
        self.claim = mock.Mock(account_id='a', actor_id=str(self.users['a'].pk), conversation_id='conversation-a')

    def test_the_ticket_the_worker_hands_over_works_against_the_endpoints_and_stops_when_the_computer_does(self):
        self.assertTrue(self.offer.tick(self.claim))
        panel = self.sent[0]['panel']
        self.assertEqual((panel['conversation_id'], panel['device_id'], panel['expires_in']), ('conversation-a', self.device, 90))
        r = self.call('GET', '/v1/panel/state', ticket=panel['ticket'])
        self.assertEqual((r.status_code, r.json()['live']), (200, True))
        r = self.call('POST', '/v1/panel/send', ticket=panel['ticket'], body={'message': 'also red ones', 'key': 'abcdefgh1234'})
        self.assertEqual(r.status_code, 202); self.assertEqual(self.svc.sent[0][1]['surface'], 'panel')
        self.link.close('gone')                                                                  # the computer disconnects: the very same ticket stops working
        self.assertEqual(self.call('GET', '/v1/panel/state', ticket=panel['ticket']).json(), {'error': 'browser_off'})
        self.assertEqual(self.call('POST', '/v1/panel/send', ticket=panel['ticket'], body={'message': 'x', 'key': 'abcdefgh1234'}).status_code, 409)
        self.assertEqual(len(self.svc.sent), 1)

    def test_switching_use_my_own_browser_off_stops_the_ticket_and_its_renewal(self):
        self.assertTrue(self.offer.tick(self.claim))
        ticket = self.sent[0]['panel']['ticket']
        self.store.set_wants_local('a', False)
        self.assertEqual(self.call('GET', '/v1/panel/state', ticket=ticket).status_code, 409)
        other = type(self.offer)(lambda: SECRET, self.offer.rpc_factory)
        self.assertFalse(other.tick(self.claim)); self.assertEqual(len(self.sent), 1)

    def test_a_ticket_for_another_computer_of_the_account_is_refused(self):
        self.assertTrue(self.offer.tick(self.claim))
        forged = pt.mint(SECRET, 'a', self.actor, 'conversation-a', 'b' * 16)                      # right account and conversation, a computer that is not the connected one
        self.assertEqual(self.call('GET', '/v1/panel/state', ticket=forged).status_code, 409)
