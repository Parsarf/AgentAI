"""The composition root: one place builds services, and what it builds follows the owner's switches.

These pin two things the scattered wiring used to get wrong or leave to chance: (1) every surface gets the SAME chat service, and its wiring follows the
`customer_execution` switch; (2) no view module or worker command quietly builds its own database handle, switch reader or chat service again.
"""
import json
import os
import re
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from agentai_platform import chat as chat_rules, request_states
from agentai_platform.chat import FixedRoute, UnmeasuredRoute
from agentai_platform.switches import SwitchStore
from . import wiring
from .store import AccountStore
from .tests import AccountBoundaryTests

ACCOUNTS = Path(__file__).resolve().parent


class WiringChecks(TestCase):
    def switches(self, **on):
        d = tempfile.mkdtemp()
        switches, facts = os.path.join(d, 'switches.json'), os.path.join(d, 'facts.json')
        json.dump({'execution_ready': True}, open(facts, 'w'))
        store = SwitchStore(switches, facts_path=facts)
        if on.get('customer_execution'):
            store.confirm('customer_execution', 'execution_cost', 'test'); store.set('customer_execution', True, 'test')
        context = override_settings(SWITCHES_FILE=switches, SWITCH_FACTS_FILE=facts, SERVICE_ALLOCATION_MICROUSD=50_000_000, CUSTOMER_RESERVATION_MICROUSD=700)
        context.__enter__(); self.addCleanup(context.__exit__, None, None, None)

    def test_the_store_runs_on_djangos_connection(self):
        store = wiring.store()
        self.assertIsInstance(store, AccountStore)
        with store.connect() as con:
            self.assertEqual(con.execute('SELECT ?', (7,)).fetchone()[0], 7)      # `?` placeholders work on Django's cursor

    def test_with_execution_off_the_chat_service_only_records(self):
        self.switches()
        self.assertFalse(wiring.switch_on('customer_execution'))
        s = wiring.chat_service()
        self.assertFalse(s.execution)
        self.assertIsInstance(s.pricer, UnmeasuredRoute)          # nothing is priced, so nothing can be funded
        self.assertIsNone(s.ledger.service_limit)                 # and this ledger refuses to admit
        self.assertIsNone(s.gateway_factory)                      # no cell is contacted
        self.assertFalse(s.queue.require_cell)

    def test_with_execution_on_the_chat_service_is_fully_wired(self):
        self.switches(customer_execution=True)
        self.assertTrue(wiring.switch_on('customer_execution'))
        s = wiring.chat_service()
        self.assertTrue(s.execution)
        self.assertIsInstance(s.pricer, FixedRoute)
        self.assertEqual(s.pricer.reservation('hello'), (700, 'plan-reservation-v1'))
        self.assertEqual(s.ledger.service_limit, 50_000_000)
        self.assertTrue(s.queue.require_cell)
        self.assertIsNotNone(s.gateway_factory)
        self.assertIsNotNone(s.events)

    def test_the_intake_service_never_funds_whatever_the_switch_says(self):
        self.switches(customer_execution=True)
        s = wiring.intake_chat_service()
        self.assertIsInstance(s.pricer, UnmeasuredRoute)
        self.assertIsNone(s.ledger.service_limit)
        self.assertIsNone(s.gateway_factory)
        self.assertFalse(s.execution)

    def test_a_switch_change_is_seen_by_the_next_call_without_a_restart(self):
        self.switches()
        self.assertFalse(wiring.chat_service().execution)
        store = wiring.switches()
        store.confirm('customer_execution', 'execution_cost', 'test'); store.set('customer_execution', True, 'test')
        self.assertTrue(wiring.chat_service().execution)

    def test_missing_switch_file_means_everything_is_off(self):
        with override_settings(SWITCHES_FILE='', SWITCH_FACTS_FILE=''):
            for name in ('customer_execution', 'browse_tasks', 'billing_checkout', 'open_access', 'open_signups', 'connectors_linking'):
                self.assertFalse(wiring.switch_on(name), name)
            self.assertEqual(wiring.access_mode(), 'invite_only')

    def test_rollout_questions_are_off_without_their_files(self):
        with override_settings(ENGINE_FILE='/nonexistent/own.json', MCP_SWITCH_FILE='', LTM_SWITCH_FILE='/nonexistent/ltm.json'):
            self.assertFalse(wiring.own_model_on('a')); self.assertFalse(wiring.own_model_active('a'))
            self.assertFalse(wiring.mcp_on('a')); self.assertFalse(wiring.memory_on('a'))

    def test_rollout_files_open_a_feature_to_the_listed_accounts_only(self):
        d = Path(tempfile.mkdtemp())
        (d / 'own.json').write_text('{"own_model_keys": ["a"]}'); (d / 'mcp.json').write_text('{"mcp_connections": true}'); (d / 'ltm.json').write_text('{"long_term_memory": ["b"]}')
        with override_settings(ENGINE_FILE=str(d / 'own.json'), MCP_SWITCH_FILE=str(d / 'mcp.json'), LTM_SWITCH_FILE=str(d / 'ltm.json')):
            self.assertTrue(wiring.own_model_on('a')); self.assertFalse(wiring.own_model_on('b'))
            self.assertTrue(wiring.mcp_on('a')); self.assertTrue(wiring.mcp_on('b'))
            self.assertFalse(wiring.memory_on('a')); self.assertTrue(wiring.memory_on('b'))

    def test_safety_question_fails_closed(self):
        self.assertTrue(wiring.safety_on('a', 'upload_limits'))                # on by default
        self.assertTrue(wiring.safety_on('a', 'no_such_protection'))

    def test_private_files(self):
        d = Path(tempfile.mkdtemp()); secret = d / 's'; secret.write_text('  0123456789abcdef  \n'); os.chmod(secret, 0o600)
        self.assertEqual(wiring.read_private(str(secret), 16), '0123456789abcdef')
        self.assertIsNone(wiring.read_private(str(secret), 64))                # too short for what the caller needs
        os.chmod(secret, 0o644); self.assertIsNone(wiring.read_private(str(secret)))        # readable by others: not a secret
        os.chmod(secret, 0o600); link = d / 'l'; link.symlink_to(secret); self.assertIsNone(wiring.read_private(str(link)))
        self.assertIsNone(wiring.read_private('')); self.assertEqual(wiring.read_text(''), ''); self.assertEqual(wiring.read_text(str(d / 'missing')), '')
        with override_settings(PANEL_ORIGINS=[], PANEL_SECRET_FILE=str(secret)):
            self.assertEqual(wiring.panel_secret(), b'')                       # no extension origin configured: the panel is off even with a key
        with override_settings(LIVE_SECRET_FILE=''):
            self.assertEqual(wiring.live_secret(), b'')


class OneHomeForWiring(TestCase):
    """Views and worker commands get collaborators from accounts/wiring.py. This fails when a module starts building its own again."""

    FORBIDDEN = {
        r"connection\.settings_dict\['NAME'\]": 'the database handle: use wiring.store()',
        r'\bAccountStore\(': 'the database handle: use wiring.store()',
        r'\bSwitchStore\(': "owner switches: use wiring.switch_on(name) / wiring.switches()",
        r'\bChatService\(': 'the chat service: use wiring.chat_service()',
        r'\bBudgetLedger\(': 'the ledger: use wiring.ledger()',
        r'\bRequestQueue\(': 'the queue: use wiring.request_queue()',
        r'\bBrowseRpc\(': 'the browse service client: use wiring.browse_rpc(account)',
        r'\bBridgeRpc\(': 'the cell bridge client: use wiring.cell_rpc(account) / wiring.cell_gateway(account)',
        r'\bRootStore\(': 'file storage: use wiring.file_service() / wiring.artifact_service()',
        r"Principal\(request\.account_id": 'the request principal: use wiring.principal(request)',
    }
    EXEMPT = {'wiring.py', 'store.py'}

    def sources(self):
        files = [p for p in ACCOUNTS.glob('*.py') if not p.name.startswith('test') and p.name not in self.EXEMPT]
        files += list((ACCOUNTS / 'management' / 'commands').glob('*.py'))
        return files

    def test_no_module_builds_its_own_collaborators(self):
        found = []
        for path in self.sources():
            text = path.read_text()
            for pattern, advice in self.FORBIDDEN.items():
                for match in re.finditer(pattern, text):
                    line = text.count('\n', 0, match.start()) + 1
                    found.append(f'{path.relative_to(ACCOUNTS)}:{line} builds {advice}')
        self.assertEqual(found, [])


class AppLimitsChecks(TestCase):
    setUp = AccountBoundaryTests.setUp
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed

    def test_the_app_reports_the_limits_the_server_enforces(self):
        limits = self.signed('a').get('/v1/app', secure=True).json()['limits']
        self.assertEqual(limits, {'max_message_chars': chat_rules.MAX_MESSAGE_CHARS, 'max_projects': chat_rules.MAX_PROJECTS,
                                  'max_conversations_per_project': chat_rules.MAX_CONVERSATIONS_PER_PROJECT})
        self.assertEqual(limits['max_conversations_per_project'], 100)        # it used to say 10 while 100 was enforced


class UniformNotFound(TestCase):
    """A route does not have to remember to turn "no such object" into the audited 404: the endpoint wrapper does, the same way as "not yours"."""
    setUp = AccountBoundaryTests.setUp
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed

    def test_unknown_and_foreign_objects_look_the_same_and_are_audited(self):
        from .models import Audit
        a = self.signed('a')
        before = Audit.objects.filter(action='access.denied').count()
        for path in ('/v1/tasks/' + 'f' * 32, '/v1/conversations/' + 'f' * 32, '/v1/conversations/' + 'f' * 32 + '/messages', '/v1/operations/' + 'f' * 32):
            r = a.get(path, secure=True)
            self.assertEqual((r.status_code, r.json()), (404, {'error': 'unavailable'}), path)
        self.assertEqual(Audit.objects.filter(action='access.denied').count(), before + 4)

    def test_the_wrapper_maps_a_service_not_found_by_itself(self):
        from unittest.mock import patch
        from agentai_platform.security import NotFound
        with patch('accounts.location.service') as factory:
            factory.return_value.pending.side_effect = NotFound('unavailable')      # the view has no handler of its own for this
            r = self.signed('a').get('/v1/location', secure=True)
        self.assertEqual((r.status_code, r.json()), (404, {'error': 'unavailable'}))


class RequestStateVocabulary(TestCase):
    def test_groups(self):
        self.assertEqual(set(request_states.ACTIVE) | set(request_states.FINAL), {'waiting', 'starting', 'running', 'uncertain', 'completed', 'failed', 'cancelled'})
        self.assertFalse(set(request_states.ACTIVE) & set(request_states.FINAL))
        self.assertLess(set(request_states.LIVE), set(request_states.CLAIMED)); self.assertLess(set(request_states.CLAIMED), set(request_states.ACTIVE))
        self.assertEqual(request_states.live_run(), "r.state IN ('starting','running') AND r.closing=0 AND r.cancel_requested=0")
        self.assertEqual(request_states.live_run(''), "state IN ('starting','running') AND closing=0 AND cancel_requested=0")


class WorkerWiring(TestCase):
    """The worker commands are assembled from the same composition root as the web app. These build them for real (no cell, no browser: nothing is contacted until a request runs)."""

    def test_the_request_worker_is_assembled_and_idles(self):
        from io import StringIO
        from django.core.management import call_command
        from accounts.management.commands import request_worker
        worker = request_worker.build_worker(wiring.store())
        driver = worker.driver
        self.assertTrue(worker.queue.require_cell)                    # the worker only ever runs a request in its own cell
        self.assertIs(driver.queue, worker.queue)
        self.assertIsNone(driver.ledger.service_limit)                # the driver settles; admission happened at send time
        self.assertIsNotNone(driver.events); self.assertIsNotNone(driver.genui); self.assertIsNotNone(driver.panel); self.assertIsNotNone(driver.display)
        self.assertEqual(driver.goal_chain_limit, request_worker.settings.GOAL_CHAIN_LIMIT)
        self.assertEqual(driver.browse_factory('a').account_id, 'a'); self.assertEqual(driver.browse_factory('a').path, request_worker.settings.BROWSE_SOCKET)
        with override_settings(STORAGE_DIR='', STORAGE_READY=False):
            self.assertIsNone(request_worker.build_worker(wiring.store()).driver.artifacts)      # no storage configured: files are simply not captured
        out = StringIO()
        with override_settings(SWITCHES_FILE='', SWITCH_FACTS_FILE=''):
            call_command('request_worker', once=True, stdout=out)     # customer_execution off: one idle pass, nothing claimed

    def test_the_tool_relay_is_assembled(self):
        from accounts.management.commands import tool_relay
        with override_settings(HINDSIGHT_URL='', HINDSIGHT_BANK_SECRET_FILE='', MCP_OAUTH_CLIENTS_FILE='', MCP_SWITCH_FILE='', ENGINE_FILE='/nonexistent/own.json'):
            relay, identity, own_models = tool_relay.build(wiring.store())
            self.assertIsNotNone(relay.tool); self.assertIsNotNone(relay.progress); self.assertIsNotNone(relay.location); self.assertIsNotNone(relay.remote)
            self.assertIsNone(relay.memory)                           # long-term memory is not configured: its tools do not exist
            self.assertIsNotNone(identity); self.assertIsNotNone(own_models)
            self.assertFalse(own_models.enabled('a'))                 # own model keys are closed until the owner's rollout file opens them
            self.assertFalse(own_models.admission('a', True))         # and no live funded run means no model call is relayed


class FormResults(TestCase):
    """What a classic HTML form post gets back is declared on the route, not inferred from the view function's name."""

    def test_nothing_in_the_wrapper_depends_on_a_function_name(self):
        wrapper = (ACCOUNTS / 'views.py').read_text().split('def endpoint(')[1].split('\ndef customer(')[0]
        self.assertNotIn('__name__', wrapper)

    def test_an_unknown_form_result_is_refused_when_the_route_is_defined(self):
        from .views import endpoint
        with self.assertRaises(ValueError):
            endpoint(['POST'], form='somewhere')

    def test_routes_keep_the_result_they_had(self):
        from . import billing, chat, connections, files, requests as request_views, telegram, views
        src = lambda fn: __import__('inspect').getsource(__import__('inspect').unwrap(fn))
        expected = {'chat': [chat.chat_send, chat.chat_cancel, chat.chat_archive, chat.chat_conversations, chat.chat_rename, chat.chat_restore, chat.chat_goal, chat.chat_pause, chat.chat_resume, chat.chat_retry],
                    'requests': [request_views.requests, request_views.cancel], 'connections': [connections.disconnect],
                    'json': [connections.link, telegram.link, files.ticket, billing.checkout, billing.portal],
                    'login': [views.signout, views.revoke_sessions, views.finish], 'signin': [views.signin], 'pending': [views.recovery]}
        for form, routes in expected.items():
            for route in routes:
                self.assertIn(f"form='{form}'", src(route).split('def ')[0], route.__name__)
