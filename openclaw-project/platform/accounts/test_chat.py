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

    def test_history_search_paging_and_archive_restore(self):
        conversation = self.conversation()
        a, b = self.clients
        self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'unique narwhal discussion', 'key': 'search-key'})
        listed = a.get('/v1/conversations?q=narwhal&limit=1', secure=True).json()
        self.assertEqual([c['id'] for c in listed['conversations']], [conversation])
        self.assertFalse(listed['has_more'])
        self.assertEqual(b.get('/v1/conversations?q=narwhal', secure=True).json()['conversations'], [])
        self.assertEqual(a.get('/v1/conversations?limit=-1', secure=True).status_code, 400)
        self.assertEqual(a.get('/v1/conversations?archived=maybe', secure=True).status_code, 400)
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/archive', {}).status_code, 200)
        self.assertEqual(a.get('/v1/conversations', secure=True).json()['conversations'], [])
        self.assertEqual(a.get('/v1/conversations?archived=1', secure=True).json()['conversations'][0]['id'], conversation)
        self.assertEqual(self.post(b, '/v1/conversations/' + conversation + '/restore', {}).status_code, 404)
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/restore', {}).status_code, 200)
        self.assertEqual(len(a.get('/v1/conversations', secure=True).json()['conversations']), 1)

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


class DefaultOpenChecks(ChatHTTPChecks):
    def test_chat_opens_into_a_ready_conversation_and_foreign_ids_do_not(self):
        a = self.clients[0]
        page = a.get('/account/chat/', secure=True)
        self.assertContains(page, 'name="message"')                           # composer is there without clicking anything
        self.assertEqual(len(self.service_conversations()), 1)
        a.get('/account/chat/', secure=True)
        self.assertEqual(len(self.service_conversations()), 1)                # reopening reuses it
        other = self.conversation(client=1)
        self.assertNotContains(a.get('/account/chat/?conversation=' + other, secure=True), 'name="message"')

    def service_conversations(self):
        return self.clients[0].get('/v1/conversations', secure=True).json()['conversations']


class ArchiveChecks(ChatHTTPChecks):
    def test_archive_hides_without_deleting_and_frees_the_limit(self):
        a = self.clients[0]
        conversation = self.conversation()
        self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'hello', 'key': 'arch1'})
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/archive', {}).status_code, 200)
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/archive', {}).status_code, 200)    # idempotent
        self.assertNotIn(conversation, [c['id'] for c in a.get('/v1/conversations', secure=True).json()['conversations']])
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM chat_messages WHERE conversation_id=%s', [conversation]); self.assertEqual(c.fetchone()[0], 1)
        self.assertEqual(self.post(self.clients[1], '/v1/conversations/' + conversation + '/archive', {}).status_code, 404)
        page = a.get('/account/chat/', secure=True)                          # opens a fresh conversation, not the archived one
        self.assertNotContains(page, 'hello')


class UiContractChecks(ChatHTTPChecks):
    def test_presence_follows_the_workspace(self):
        anon = self.new_client()
        self.assertEqual(anon.get('/v1/assistant/presence', secure=True).status_code, 401)
        mine, other = self.clients
        state = lambda client: client.get('/v1/assistant/presence', secure=True).json()['state']
        self.assertEqual(state(mine), 'unknown')                                  # no workspace bound yet
        with connection.cursor() as c:
            c.execute("INSERT INTO lifecycle_cells(account_id,deployment_id,tenant_ref,profile_revision,observed_state) VALUES (%s,%s,'t-presence','p','stopped')",
                      [self.account_ids[0], 'deployment-' + self.account_ids[0]])
        self.assertEqual(state(mine), 'asleep')
        with connection.cursor() as c:
            c.execute("UPDATE lifecycle_cells SET observed_state='running' WHERE account_id=%s", [self.account_ids[0]])
        self.assertEqual(state(mine), 'awake')
        self.assertEqual(state(other), 'unknown')                                 # another account's workspace is never reported

    def test_csrf_bootstrap_and_shell(self):
        import tempfile, os
        from django.test import override_settings
        anon = self.new_client()
        token = anon.get('/v1/csrf', secure=True)
        self.assertEqual(token.status_code, 200); self.assertTrue(token.json()['csrf_token'])
        self.assertEqual(anon.get('/v1/app', secure=True).status_code, 401)
        app = self.clients[0].get('/v1/app', secure=True).json()
        self.assertEqual(app['user']['email'], 'chatter@example.invalid')
        self.assertEqual(set(app['features']), {'chat', 'execution', 'browse', 'files', 'uploads', 'telegram', 'connectors', 'billing_mode', 'requests', 'usage'})
        self.assertNotIn('account_id', json.dumps(app))                     # the shell never needs, and is never handed, internal ids
        d = tempfile.mkdtemp()
        with override_settings(UI_BUNDLE_DIR=d):
            self.assertEqual(anon.get('/app/', secure=True).status_code, 404)           # nothing installed yet
            open(os.path.join(d, 'index.html'), 'w').write('<p>shell</p>'); open(os.path.join(d, 'a.js'), 'w').write('1')
            page = anon.get('/app/', secure=True)
            self.assertContains(page, 'shell'); self.assertIn("script-src 'self'", page['Content-Security-Policy']); self.assertEqual(page['Cache-Control'], 'no-store')
            self.assertEqual(anon.get('/app/some/client/route', secure=True).status_code, 200)       # SPA fallback
            self.assertEqual(anon.get('/app/missing.js', secure=True).status_code, 404)
            self.assertEqual(anon.get('/app/../settings.py', secure=True).status_code, 404)
            self.assertEqual(anon.get('/app/%2e%2e/%2e%2e/etc/passwd', secure=True).status_code, 404)
            self.assertIn(anon.post('/app/', {}, secure=True).status_code, (403, 405))   # writes are refused (CSRF first, then method)
        self.assertIn("default-src 'none'", anon.get('/account/login/', secure=True)['Content-Security-Policy'])   # classic pages keep the strict policy


class TaskControlHttpChecks(ChatHTTPChecks):
    """Pause, resume and retry over HTTP: CSRF, ownership, and what each state allows."""
    def task(self, client, request_id):
        return client.get('/v1/requests/' + request_id, secure=True).json()['request']

    def test_pause_resume_and_retry_roundtrip_with_ownership_and_state_checks(self):
        conversation = self.conversation(); a, b = self.clients
        sent = self.post(a, '/v1/conversations/' + conversation + '/send', {'message': 'compare two laptops', 'key': 'tc1', 'mode': 'text'})
        self.assertEqual(sent.status_code, 202, sent.content); rid = sent.json()['request']['id']
        listed = a.get('/v1/requests', secure=True).json()['requests'][0]
        self.assertEqual((listed['id'], listed['paused'], listed['retry_of']), (rid, False, None)); self.assertIsInstance(listed['ahead'], int)
        for action in ('pause', 'resume', 'retry'):                                       # another account cannot touch it, and learns nothing
            self.assertEqual(self.post(b, f'/v1/requests/{rid}/{action}', {}).status_code, 404, action)
        self.assertEqual(self.post(a, f'/v1/requests/{rid}/retry', {}).status_code, 409)       # it has not failed
        held = self.post(a, f'/v1/requests/{rid}/pause', {}); self.assertEqual(held.status_code, 202, held.content)
        self.assertEqual((held.json()['request']['paused'], held.json()['request']['ahead']), (True, None))
        self.assertTrue(self.task(a, rid)['paused'])
        back = self.post(a, f'/v1/requests/{rid}/resume', {}); self.assertFalse(back.json()['request']['paused'])
        self.assertEqual(self.post(a, f'/v1/requests/{rid}/cancel', {}).status_code, 202)
        self.assertEqual(self.post(a, f'/v1/requests/{rid}/pause', {}).status_code, 409)       # cancelled: nothing to hold
        retry = self.post(a, f'/v1/requests/{rid}/retry', {}); self.assertEqual(retry.status_code, 202, retry.content)
        new = retry.json()['request']; self.assertEqual((new['retry_of'], new['state']), (rid, 'waiting')); self.assertNotEqual(new['id'], rid)
        self.assertEqual(self.post(a, f'/v1/requests/{rid}/retry', {}).json()['request']['id'], new['id'])      # idempotent
        self.assertEqual(self.client_without_csrf(a, f'/v1/requests/{new["id"]}/pause'), 403)

    def client_without_csrf(self, client, path):
        return client.post(path, data='{}', content_type='application/json', secure=True).status_code


class OpenApiDriftChecks(ChatHTTPChecks):
    """Every public route must be documented, and nothing undocumented may be advertised: a new UI is built from this file."""
    DISABLED = {'streams', 'exports', 'memory', 'schedules', 'integrations', 'controls'}   # routes that answer 404 by design

    def test_routes_and_spec_agree(self):
        import re
        from . import urls
        norm = lambda p: re.sub(r'\{[^}]+\}', '{}', re.sub(r'<[^>]+>', '{}', '/' + p.lstrip('/')))
        routes = {norm(str(u.pattern)) for u in urls.urlpatterns}
        routes = {r for r in routes if r.startswith(('/v1', '/auth', '/internal', '/app')) and not any(r.startswith('/v1/' + k) for k in self.DISABLED)}
        routes -= {'/internal/accounts/{}/export', '/internal/accounts/{}/impersonate'}      # always-forbidden support actions, deliberately undocumented
        spec = json.load(open('openapi.json'))['paths']
        documented = {norm(k) for k in spec if k.startswith(('/v1', '/auth', '/internal', '/app'))}
        self.assertEqual(sorted(routes - documented), [])
        known_disabled = {norm(k) for k in spec if any(k.startswith('/v1/' + d) for d in self.DISABLED)}
        self.assertEqual(sorted(documented - routes - known_disabled), [])


class GenUiHttpChecks(ChatHTTPChecks):
    def send(self, client, conversation, message, key):
        return self.post(client, '/v1/conversations/' + conversation + '/send', {'message': message, 'key': key, 'mode': 'auto'})

    def test_form_roundtrip_conflict_isolation_and_bad_input(self):
        conversation = self.conversation(); other = self.conversation(client=1)
        a, b = self.clients
        plain = self.send(a, conversation, 'What is React?', 'g0')
        self.assertEqual(plain.status_code, 202); self.assertEqual(plain.json()['request']['response_type'], 'text')
        sent = self.send(a, conversation, 'Build me an e-commerce website', 'g1')
        self.assertEqual(sent.status_code, 202, sent.content)
        block = sent.json()['request']['block']
        self.assertEqual((block['kind'], block['version']), ('form', 1))
        listed = a.get('/v1/conversations/' + conversation + '/blocks', secure=True).json()['blocks']
        self.assertEqual([x['id'] for x in listed], [block['id']])
        saved = self.post(a, '/v1/blocks/' + block['id'] + '/state', {'version': 1, 'state': {'answers': {'kind': 'ecommerce', 'catalog': 40}}})
        self.assertEqual(saved.status_code, 200, saved.content); self.assertEqual(saved.json()['block']['version'], 2)
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/state', {'version': 1, 'state': {'answers': {}}}).status_code, 409)       # stale tab
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/state', {'version': 2, 'state': {'answers': {'kind': 'drop table'}}}).status_code, 400)
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/state', {'version': '2', 'state': {}}).status_code, 400)
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/state', {'version': 2, 'state': {}, 'account_id': 'x'}).status_code, 400)
        self.assertEqual(self.post(b, '/v1/blocks/' + block['id'] + '/state', {'version': 2, 'state': {'answers': {}}}).status_code, 404)        # other tenant
        self.assertEqual(self.post(b, '/v1/blocks/' + block['id'] + '/launch', {'version': 2}).status_code, 404)
        self.assertEqual(b.get('/v1/conversations/' + conversation + '/blocks', secure=True).status_code, 404)
        self.assertEqual(b.get('/v1/conversations/' + other + '/blocks', secure=True).json()['blocks'], [])
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/launch', {'version': 2}).status_code, 409)                                 # a form cannot be launched
        no_csrf = a.post('/v1/blocks/' + block['id'] + '/state', json.dumps({'version': 2, 'state': {}}), content_type='application/json', secure=True)
        self.assertEqual(no_csrf.status_code, 403)
        again = self.send(a, conversation, 'Build me an e-commerce website', 'g1')
        self.assertEqual(again.status_code, 202, again.content)
        self.assertEqual(again.json()['request']['block']['id'], block['id'])       # idempotent


class ChatListChecks(ChatHTTPChecks):
    def test_new_chat_needs_no_project_and_the_list_carries_titles_and_activity(self):
        a = self.clients[0]
        made = self.post(a, '/v1/conversations', {})
        self.assertEqual(made.status_code, 201, made.content)
        cid = made.json()['conversation']['id']
        first = [c for c in a.get('/v1/conversations', secure=True).json()['conversations'] if c['id'] == cid][0]
        self.assertEqual((first['title'], first['active']), (None, 0))
        self.post(a, '/v1/conversations/' + cid + '/send', {'message': 'What is the capital of Portugal? ' + 'x' * 200, 'key': 'cl1', 'mode': 'text'})
        row = [c for c in a.get('/v1/conversations', secure=True).json()['conversations'] if c['id'] == cid][0]
        self.assertTrue(row['title'].startswith('What is the capital of Portugal?')); self.assertLessEqual(len(row['title']), 90)
        self.assertEqual(row['active'], 1); self.assertTrue(row['last_activity'])                               # a waiting request counts as active
        self.assertEqual(self.post(self.clients[1], '/v1/conversations/' + cid + '/archive', {}).status_code, 404)
        for n in range(15):                                                                                       # more than the old limit of 10
            self.assertEqual(self.post(a, '/v1/conversations', {}).status_code, 201)


class PlanRunHttpChecks(ChatHTTPChecks):
    def test_launch_starts_phase_one_and_actions_are_scoped(self):
        a, b = self.clients
        conversation = self.conversation()
        from .chat import service
        s = service()
        plan = {'schemaVersion': '1.0', 'type': 'task_plan', 'title': 'T', 'phases': [
            {'id': 'a', 'title': 'A', 'description': '', 'enabled': True, 'optional': False, 'requiresApproval': False, 'dependsOn': []},
            {'id': 'b', 'title': 'B', 'description': '', 'enabled': True, 'optional': False, 'requiresApproval': True, 'dependsOn': ['a']}]}
        block = s.blocks.create_plan(self.account_ids[0], conversation, plan, key='http-plan-1')
        self.assertEqual(self.post(b, '/v1/blocks/' + block['id'] + '/live', {'version': 1, 'plan': plan}).status_code, 404)
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/stop', {}).status_code, 409)               # not launched yet
        listed = a.get('/v1/conversations/' + conversation + '/blocks', secure=True).json()['blocks'][0]
        self.assertEqual(listed['status'], 'draft'); self.assertNotIn('run', listed)
        r = self.post(a, '/v1/blocks/' + block['id'] + '/launch', {'version': 1})
        self.assertEqual(r.status_code, 202, r.content)
        run = a.get('/v1/conversations/' + conversation + '/blocks', secure=True).json()['blocks'][0]
        self.assertEqual((run['status'], run['run']['a']['state'], run['run']['b']['state']), ('launched', 'running', 'pending'))
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/phase', {'phase_id': 'b', 'action': 'approve'}).status_code, 200)  # approval can be given ahead of time
        self.assertEqual(self.post(a, '/v1/blocks/' + block['id'] + '/phase', {'phase_id': 'b', 'action': 'explode'}).status_code, 400)
        self.assertEqual(self.post(b, '/v1/blocks/' + block['id'] + '/phase', {'phase_id': 'b', 'action': 'skip'}).status_code, 404)
        stopped = self.post(a, '/v1/blocks/' + block['id'] + '/stop', {})
        self.assertEqual(stopped.status_code, 200); self.assertEqual(stopped.json()['block']['run']['b']['state'], 'cancelled')
        renamed = self.post(a, '/v1/conversations/' + conversation + '/rename', {'title': 'Store build'})
        self.assertEqual(renamed.status_code, 200)
        titles = [c['title'] for c in a.get('/v1/conversations', secure=True).json()['conversations'] if c['id'] == conversation]
        self.assertEqual(titles, ['Store build'])
        self.assertEqual(self.post(a, '/v1/conversations/' + conversation + '/rename', {'title': ''}).status_code, 400)
        self.assertEqual(self.post(b, '/v1/conversations/' + conversation + '/rename', {'title': 'x'}).status_code, 404)


class BrowseHttpChecks(ChatHTTPChecks):
    def seed(self, status='completed'):
        with connection.cursor() as c:
            c.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,created_epoch) VALUES (%s,'br1','a',%s,'k','h','find a paddle','completed',1)", [self.account_ids[0], self.project()])
            c.execute("INSERT INTO browse_runs(account_id,request_id,goal,status,url,answer,created_epoch,updated_epoch) VALUES (%s,'br1','find a paddle',%s,'https://shop.test/','done',1,1)", [self.account_ids[0], status])
            c.execute("INSERT INTO browse_steps(account_id,request_id,n,kind,data_json,created_epoch) VALUES (%s,'br1',1,'step','{\"summary\":\"opened\"}',1)", [self.account_ids[0]])

    def test_runs_are_listed_and_scoped_to_the_owner(self):
        self.seed()
        a, b = self.clients
        self.assertEqual([r['request_id'] for r in a.get('/v1/browse', secure=True).json()['runs']], ['br1'])
        self.assertEqual(b.get('/v1/browse', secure=True).json()['runs'], [])
        self.assertEqual(b.get('/v1/browse/br1', secure=True).status_code, 404)
        detail = a.get('/v1/browse/br1', secure=True).json()
        self.assertEqual((detail['status'], detail['takeover'], detail['events'][0]['n']), ('completed', False, 1))

    def test_control_validates_input_and_needs_the_service(self):
        self.seed('handoff')
        a, b = self.clients
        for bad in [{'action': 'click'}, {'action': 'click', 'x': 2000, 'y': 1}, {'action': 'type'}, {'action': 'nope'}, {'action': 'type', 'text': 'x' * 501}]:
            self.assertEqual(self.post(a, '/v1/browse/br1/control', bad).status_code, 400, bad)
        self.assertEqual(self.post(b, '/v1/browse/br1/control', {'action': 'scroll', 'text': 'down'}).status_code, 404)
        self.assertIn(self.post(a, '/v1/browse/br1/control', {'action': 'scroll', 'text': 'down'}).status_code, (409, 503))   # no browse service in tests

    def test_pause_resume_and_live_ticket_are_scoped_gated_and_degrade_without_the_service(self):
        import os
        import tempfile
        from django.test import override_settings
        from agentai_platform.live import ticket
        rid = 'a' * 32
        with connection.cursor() as c:
            c.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,created_epoch) VALUES (%s,%s,'a',%s,'k2','h2','find a paddle','running',1)", [self.account_ids[0], rid, self.project()])
            c.execute("INSERT INTO browse_runs(account_id,request_id,goal,status,url,created_epoch,updated_epoch) VALUES (%s,%s,'find a paddle','running','https://shop.test/',1,1)", [self.account_ids[0], rid])
        a, b = self.clients
        for path in ('pause', 'resume', 'live'):
            self.assertEqual(self.post(b, f'/v1/browse/{rid}/{path}', {}).status_code, 404, path)          # someone else's task
        self.assertEqual(self.post(a, f'/v1/browse/{rid}/pause', {}).status_code, 409)                  # no browse service in tests
        self.assertEqual(self.post(a, f'/v1/browse/{rid}/resume', {}).status_code, 409)
        self.assertEqual(self.post(a, f'/v1/browse/{rid}/live', {}).status_code, 404)                   # live view not set up on this server: the page uses snapshots
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'k' * 48); f.flush()
            with override_settings(LIVE_SECRET_FILE=f.name):
                got = self.post(a, f'/v1/browse/{rid}/live', {})
                self.assertEqual(got.status_code, 200)
                body = got.json()
                self.assertEqual(body['path'], f'/v1/live/{rid}/frame')
                self.assertEqual(ticket.verify(b'k' * 48, body['ticket'], rid), self.account_ids[0])    # bound to the owner and this one task
                with connection.cursor() as c:
                    c.execute("UPDATE browse_runs SET status='done' WHERE request_id=%s", [rid])
                self.assertEqual(self.post(a, f'/v1/browse/{rid}/live', {}).status_code, 409)           # finished tasks have nothing live to watch
