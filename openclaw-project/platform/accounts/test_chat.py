import contextlib
import io
import json
import uuid
from unittest.mock import patch
from django.db import connection
from django.core.management import call_command
from django.contrib.auth.models import User
from django.test import TestCase
from .models import Identity
from .services import token_for, consume
from .tests import AccountBoundaryTests, PASSWORD
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.request_queue import RequestQueue
from .lifecycle import AccountStore


class ChatHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post

    def setUp(self):
        self.output = io.StringIO();redirect = contextlib.redirect_stdout(self.output);redirect.__enter__();self.addCleanup(redirect.__exit__, None, None, None)
        self.clients = []
        for email in ['chatter@example.invalid', 'other@example.invalid']:
            call_command('onboard_trial', email=email, stdout=self.output)
            user = User.objects.get(email=email);code = token_for(user, 'onboarding');consume(code, 'onboarding', PASSWORD, uuid.uuid4())
            client = self.new_client();self.assertEqual(self.post(client, '/auth/login', {'email': email, 'password': PASSWORD}).status_code, 200)
            self.clients.append(client)
        with connection.cursor() as c:
            for row in Identity.objects.all():
                c.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (%s,%s,1,'stopped')", [row.account_id, 'deployment-' + row.account_id])
        self.account_ids = [Identity.objects.get(user__email=e).account_id for e in ['chatter@example.invalid', 'other@example.invalid']]

    def project(self, client=0):
        listing = self.clients[client].get('/v1/projects', secure=True).json()['projects']
        self.assertTrue(listing)
        return listing[0]['id']

    def conversation(self, client=0, project=None):
        response = self.post(self.clients[client], '/v1/conversations', {'project_id': project or self.project(client)})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['conversation']['id']

    def test_project_creation_quota_and_validation(self):
        a = self.clients[0]
        created = self.post(a, '/v1/projects', {'name': 'My second project'})
        self.assertEqual(created.status_code, 201, created.content)
        with connection.cursor() as c:
            for i in range(9):
                c.execute("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,%s)", [self.account_ids[0], 'pad-' + str(i), 'pad'])
        self.assertEqual(self.post(a, '/v1/projects', {'name': 'one too many'}).status_code, 409)
        self.assertEqual(self.post(a, '/v1/projects', {'name': 'x' * 121}).status_code, 400)
        self.assertEqual(self.post(a, '/v1/projects', {'name': ''}).status_code, 400)

    def test_conversation_scoping_and_validation(self):
        conversation = self.conversation()
        other = self.conversation(client=1)
        a, b = self.clients
        self.assertEqual(a.get('/v1/conversations/' + conversation, secure=True).json()['conversation']['id'], conversation)
        self.assertEqual(b.get('/v1/conversations/' + conversation, secure=True).status_code, 404)
        self.assertEqual(b.get('/v1/conversations/' + other, secure=True).status_code, 200)
        self.assertEqual(self.post(b, '/v1/conversations', {'project_id': self.project()}).status_code, 404)
        listed = a.get('/v1/conversations', secure=True).json()['conversations']
        self.assertEqual([c['id'] for c in listed], [conversation])

    def test_send_idempotency_and_transcript(self):
        conversation = self.conversation()
        a = self.clients[0]
        first = self.post(a, '/v1/conversations/' + conversation + '/send', {'message': '<script>private</script>', 'key': 'send-key'})
        self.assertEqual(first.status_code, 202, first.content)
        body = first.json()['request']
        self.assertEqual((body['execution_enabled'], body['admission']), (False, 'route_unconfigured'))
        duplicate = self.post(a, '/v1/conversations/' + conversation + '/send', {'message': '<script>private</script>', 'key': 'send-key'})
        self.assertEqual(duplicate.json()['request']['id'], body['id'])
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM tasks');self.assertEqual(c.fetchone()[0], 0)
            c.execute('SELECT count(*) FROM chat_messages');self.assertEqual(c.fetchone()[0], 1)
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'changed', 'key': 'send-key'}).status_code, 409)
        messages = a.get('/v1/conversations/' + conversation + '/messages', secure=True).json()
        self.assertEqual([m['provenance'] for m in messages['messages']], ['customer'])
        self.assertEqual(messages['execution_enabled'], False)
        self.assertEqual(a.get('/v1/conversations/' + conversation + '/messages?after=notanumber', secure=True).status_code, 400)
        self.assertEqual(self.clients[1].get('/v1/conversations/' + conversation + '/messages', secure=True).status_code, 404)
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'x' * 16001, 'key': 'big'}).status_code, 400)
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'x' * 16000, 'key': 'fits'}).status_code, 202)
        self.assertEqual(a.get('/v1/conversations?account_id=other', secure=True).status_code, 400)

    def test_task_read_cancel_and_cross_account(self):
        conversation = self.conversation()
        a, b = self.clients
        sent = self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'work', 'key': 't1'}).json()['request']
        task = a.get('/v1/tasks/' + sent['id'], secure=True).json()['task']
        self.assertEqual((task['state'], task['execution_enabled']), ('waiting', False))
        self.assertEqual(b.get('/v1/tasks/' + sent['id'], secure=True).status_code, 404)
        self.assertEqual(self.post(b, '/v1/tasks/' + sent['id'] + '/cancel', {}).status_code, 404)
        cancelled = self.post(a, '/v1/tasks/' + sent['id'] + '/cancel', {})
        self.assertEqual(cancelled.status_code, 202)
        self.assertEqual(a.get('/v1/tasks/' + sent['id'], secure=True).json()['task']['state'], 'cancelled')
        self.assertEqual(a.get('/v1/tasks', secure=True).status_code, 503)

    def test_budget_denial_recorded_without_native_call(self):
        conversation = self.conversation()
        store = AccountStore(connection.settings_dict['NAME'])
        scoped = ChatService(store, queue=RequestQueue(store),
                             ledger=BudgetLedger(store, service_limit_microusd=10 ** 9), pricer=FixedRoute(5000000))
        with patch('accounts.chat.service', lambda: scoped):
            response = self.post(self.clients[0], '/v1/conversations/' + conversation + '/send', {'message': 'too expensive', 'key': 'denied'})
        self.assertEqual(response.status_code, 402, response.content)
        self.assertEqual(response.json()['error'], 'budget_denied')
        self.assertEqual(response.json()['category'], 'account_allowance_exhausted')
        with connection.cursor() as c:
            c.execute("SELECT state FROM customer_requests WHERE idempotency_key='denied'");self.assertEqual(c.fetchone()[0], 'cancelled')
            c.execute('SELECT count(*) FROM tasks');self.assertEqual(c.fetchone()[0], 0)

    def test_chat_page_flow_and_escaping(self):
        conversation = self.conversation()
        a = self.clients[0]
        self.post(a, '/v1/conversations/' + conversation + '/send', {'message': '<script>x</script>', 'key': 'page1'})
        page = a.get('/account/chat/', secure=True)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Agent execution is not connected yet')
        page = a.get('/account/chat/?conversation=' + conversation, secure=True)
        self.assertContains(page, '&lt;script&gt;x&lt;/script&gt;')
        self.assertContains(page, 'Cancel')
        foreign = a.get('/account/chat/?conversation=' + self.conversation(client=1), secure=True)
        self.assertNotContains(foreign, '&lt;script&gt;')
        denied = a.get('/account/chat/?conversation=' + conversation + '&error=budget_denied&category=account_allowance_exhausted', secure=True)
        self.assertContains(denied, 'cannot fund this request')
        self.assertContains(denied, 'account_allowance_exhausted')
        self.assertEqual(a.get('/account/chat/?error=evil', secure=True).status_code, 200)
        self.assertEqual(self.new_client().get('/account/chat/', secure=True).status_code, 302)

    def test_form_send_redirect_and_cancel_redirect(self):
        conversation = self.conversation()
        a = self.clients[0]
        page = a.get('/account/chat/?conversation=' + conversation, secure=True)
        import re
        from django.utils.http import urlencode
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        response = a.post('/v1/conversations/' + conversation + '/send',
                          urlencode({'message': 'from the form', 'key': 'formkey', 'csrfmiddlewaretoken': token}),
                          content_type='application/x-www-form-urlencoded', secure=True,
                          HTTP_REFERER='https://localhost/account/chat/?conversation=' + conversation)
        self.assertEqual(response.status_code, 302, response.content)
        self.assertTrue(response['Location'].startswith('/account/chat/?conversation=' + conversation))
        follow = a.get(response['Location'], secure=True)
        self.assertContains(follow, 'from the form')


class ExecutionSwitchChecks(ChatHTTPChecks):
    """With the owner's customer_execution switch on, sends are priced and the page reports a live assistant."""

    def switch_on(self):
        import tempfile, os
        from django.test import override_settings
        d = tempfile.mkdtemp()
        switches, facts = os.path.join(d, 'switches.json'), os.path.join(d, 'facts.json')
        json.dump({'execution_ready': True}, open(facts, 'w'))
        from agentai_platform.switches import SwitchStore
        store = SwitchStore(switches, facts_path=facts)
        store.confirm('customer_execution', 'execution_cost', 'test'); store.set('customer_execution', True, 'test')
        context = override_settings(SWITCHES_FILE=switches, SWITCH_FACTS_FILE=facts, SERVICE_ALLOCATION_MICROUSD=50_000_000)
        context.__enter__(); self.addCleanup(context.__exit__, None, None, None)

    def test_page_and_send_reflect_the_switch(self):
        conversation = self.conversation()
        a = self.clients[0]
        page = a.get('/account/chat/?conversation=' + conversation, secure=True)
        self.assertContains(page, 'Agent execution is not connected yet')
        self.switch_on()
        page = a.get('/account/chat/?conversation=' + conversation, secure=True)
        self.assertContains(page, 'Your assistant is live'); self.assertNotContains(page, 'http-equiv="refresh"')
        sent = self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'hello', 'key': 'live-1'})
        self.assertEqual(sent.status_code, 202, sent.content)
        self.assertEqual(sent.json()['request']['admission'], 'reserved')
        page = a.get('/account/chat/?conversation=' + conversation, secure=True)
        self.assertContains(page, 'http-equiv="refresh"')                     # refreshes itself while a task is waiting
