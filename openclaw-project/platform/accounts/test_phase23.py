"""Roadmap Phase 2 and 3 over HTTP: every route names an action, roles are enforced, the access page is the enforcement tables, one account never reaches another's
connections, changes, exports or offboarding, and the whole write cycle works through the routes."""
import io
import json
import os
import tempfile
import zipfile
from unittest.mock import patch

from django.db import connection
from django.test import override_settings

from agentai_platform import permissions
from agentai_platform.synthetic_connector import SyntheticBench
from agentai_platform.vault import Keyring
from . import route_actions, urls, wiring
from .test_chat import ChatHTTPChecks

ON = {'synthetic_connector', 'connector_writes', 'account_self_service'}


class Base(ChatHTTPChecks):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        key = os.path.join(self.tmp.name, 'connector.key')
        with open(os.open(key, os.O_WRONLY | os.O_CREAT, 0o600), 'w') as handle:
            handle.write(Keyring.generate() + '\n')
        files = os.path.join(self.tmp.name, 'files'); os.mkdir(files, 0o700)
        override = override_settings(CONNECTOR_KEY_FILE=key, STORAGE_DIR=files, ARTIFACT_SIGNING_KEY='k' * 40, STORAGE_READY=True, ACCOUNT_COOLING_OFF_SECONDS=0)
        override.enable(); self.addCleanup(override.disable)
        real = wiring.switch_on
        switch = patch.object(wiring, 'switch_on', lambda name: name in ON or real(name))
        switch.start(); self.addCleanup(switch.stop)
        self.a, self.b = self.clients

    def rows(self, sql, args=()):
        with connection.cursor() as c:
            c.execute(sql, args)
            return c.fetchall()

    def connect(self, client=None, grants=(('folder', 'inbox', 'write'),)):
        client = client or self.a
        made = self.post(client, '/v1/integrations/synthetic/connect', {})
        self.assertEqual(made.status_code, 201, made.content)
        connection_id = made.json()['connection']['id']
        if grants:
            done = self.post(client, f'/v1/integrations/{connection_id}/grants', {'grants': [{'kind': k, 'id': i, 'access': acc} for k, i, acc in grants]})
            self.assertEqual(done.status_code, 200, done.content)
        return connection_id

    def request_id(self, client=None, index=0):
        """A task of this account for a change to belong to."""
        conversation = self.conversation(self.clients.index(client or self.a))
        sent = self.post(client or self.a, f'/v1/conversations/{conversation}/send', {'message': 'please file this', 'key': 'k-' + conversation[:8]})
        return (sent.json().get('request') or sent.json())['id'], conversation

    def propose(self, connection_id, payload, account=0, kind='note.create'):
        from agentai_platform.security import Principal
        request, conversation = self.request_id(self.clients[account])
        actor = self.rows('SELECT actor_id FROM customer_requests WHERE id=%s', [request])[0][0]
        _c, _cl, actions, _w = wiring.action_services()
        return actions.propose(Principal(self.account_ids[account], actor, 'customer'), connection_id, kind, payload, request_id=request), request, conversation


class EveryRouteNamesAnAction(Base):
    def test_every_route_has_a_row_and_every_row_has_a_route(self):
        routes = {str(u.pattern) for u in urls.urlpatterns}
        self.assertEqual(sorted(routes - set(route_actions.ROUTES)), [], 'a route in urls.py names no action in accounts/route_actions.py')
        self.assertEqual(sorted(set(route_actions.ROUTES) - routes), [], 'route_actions.py names a route that does not exist')
        special = {route_actions.PUBLIC, route_actions.OPERATOR, route_actions.OWN_PROOF}
        for route, entry in route_actions.ROUTES.items():
            for action in (entry.values() if isinstance(entry, dict) else [entry]):
                self.assertTrue(action in special or action in permissions.TABLE, f'{route}: {action} is not in the permission table')

    def test_an_owner_of_an_organization_of_one_behaves_exactly_as_before(self):
        self.assertEqual(self.a.get('/v1/organization', secure=True).json()['organization']['your_role'], 'owner')
        self.assertEqual(self.a.get('/v1/me', secure=True).status_code, 200)
        conversation = self.conversation()
        self.assertIn(self.post(self.a, f'/v1/conversations/{conversation}/send', {'message': 'hello', 'key': 'k1'}).status_code, (200, 202))

    def test_a_viewer_can_read_and_cannot_act_and_a_role_change_takes_effect_on_the_next_request(self):
        conversation = self.conversation(1)
        actor = str(self.rows('SELECT actor_id FROM memberships WHERE account_id=%s', [self.account_ids[1]])[0][0])
        from agentai_platform.security import Principal
        owner = Principal(self.account_ids[0], str(self.rows('SELECT actor_id FROM memberships WHERE account_id=%s', [self.account_ids[0]])[0][0]), 'customer')
        from agentai_platform.organizations import OrganizationService
        orgs = OrganizationService(wiring.store())                                  # no session bump here: the role is read from the database on every request anyway
        orgs.add_member(owner, self.account_ids[1], actor, 'viewer')
        self.assertEqual(self.b.get('/v1/conversations', secure=True).status_code, 200)             # reading still works
        refused = self.post(self.b, f'/v1/conversations/{conversation}/send', {'message': 'do it', 'key': 'k2'})
        self.assertEqual((refused.status_code, refused.json()), (403, {'error': 'not_permitted', 'needs': 'task.run'}))
        self.assertEqual(self.post(self.b, '/v1/integrations/synthetic/connect', {}).status_code, 403)
        self.assertEqual(self.post(self.b, '/v1/organization/policy', {'key': 'own_model_key', 'value': False}).status_code, 403)
        orgs.set_role(owner, actor, 'member')
        self.assertIn(self.post(self.b, f'/v1/conversations/{conversation}/send', {'message': 'do it', 'key': 'k3'}).status_code, (200, 202))
        self.assertEqual(self.post(self.b, '/v1/organization/policy', {'key': 'own_model_key', 'value': False}).status_code, 403)      # still not a manager
        self.assertEqual(self.post(self.a, '/v1/organization/policy', {'key': 'own_model_key', 'value': False}).status_code, 200)
        self.assertFalse(self.b.get('/v1/controls', secure=True).json()['own_model_key_allowed'])                                       # set by the organization, seen by the member
        removed = self.post(self.a, f'/v1/organization/members/{actor}/remove', {})
        self.assertEqual(removed.status_code, 200, removed.content)
        self.assertIn(self.b.get('/v1/conversations', secure=True).status_code, (401, 404))                                            # a removed member can do nothing

    def test_role_changes_end_the_persons_sessions(self):
        actor = str(self.rows('SELECT actor_id FROM memberships WHERE account_id=%s', [self.account_ids[1]])[0][0])
        from agentai_platform.security import Principal
        owner = Principal(self.account_ids[0], str(self.rows('SELECT actor_id FROM memberships WHERE account_id=%s', [self.account_ids[0]])[0][0]), 'customer')
        wiring.organization_service().add_member(owner, self.account_ids[1], actor, 'member')
        self.assertEqual(self.b.get('/v1/conversations', secure=True).status_code, 401)             # signed out: the next sign-in carries the new role


class AccessPage(Base):
    def test_every_line_is_the_enforcement_tables(self):
        connection_id = self.connect(grants=(('folder', 'inbox', 'write'), ('folder', 'projects', 'read')))
        view = self.a.get('/v1/controls', secure=True).json()
        shown = view['connections'][0]
        table = sorted((r[0], r[1], r[2]) for r in self.rows('SELECT resource_kind,resource_id,access FROM connector_grants WHERE connection_id=%s', [connection_id]))
        self.assertEqual(sorted((g['resource_kind'], g['resource_id'], g['access']) for g in shown['grants']), table)      # the page and the rows enforcement reads cannot drift
        self.assertEqual(shown['says'], 'Can read: 2 folders. Can change (each change still needs your approval): 1 folder.')
        self.post(self.a, f'/v1/integrations/{connection_id}/grants', {'grants': [{'kind': 'folder', 'id': 'inbox', 'access': 'read'}]})
        again = self.a.get('/v1/controls', secure=True).json()['connections'][0]
        self.assertEqual(again['says'], 'Can read: 1 folder. Cannot change anything.')
        self.assertEqual({t['name'] for t in view['tools']} >= {'lumina_show', 'lumina_connector_list', 'lumina_connector_propose'}, True)
        for tool in view['tools']:
            self.assertIn(permissions.tool_action(tool['name']), permissions.TABLE)                                         # every tool shown is a tool the relay can check
        body = json.dumps(view)
        for leak in ('secret_ref', 'access_token', 'refresh_token', 'synthetic-', 'refresh-', 'cs-'):
            self.assertNotIn(leak, body)                                                                                   # names and counts only
        self.assertEqual(self.b.get('/v1/controls', secure=True).json()['connections'], [])                                # another account sees none of it
        self.assertEqual({w['kind'] for w in view['waits']} >= {'action_approval', 'browser_takeover', 'question'}, True)

    def test_a_connection_starts_with_nothing_selected_and_the_picker_lists_what_the_service_offers(self):
        connection_id = self.connect(grants=())
        self.assertIn('nothing yet', self.a.get(f'/v1/integrations/{connection_id}', secure=True).json()['connection']['says'])
        offered = self.a.get(f'/v1/integrations/{connection_id}/resources', secure=True).json()['resources']
        self.assertEqual([r['id'] for r in offered], ['inbox', 'projects', 'archive'])
        self.assertEqual(self.b.get(f'/v1/integrations/{connection_id}/resources', secure=True).status_code, 404)
        self.assertEqual(self.post(self.b, f'/v1/integrations/{connection_id}/grants', {'grants': []}).status_code, 404)
        self.assertEqual(self.b.get(f'/v1/integrations/{connection_id}', secure=True).status_code, 404)

    def test_removing_a_connection_answers_with_the_receipt_and_is_always_possible(self):
        connection_id = self.connect()
        with patch.object(wiring, 'switch_on', lambda name: False):
            self.assertEqual(self.post(self.a, '/v1/integrations/synthetic/connect', {}).status_code, 503)                 # off: nothing can be connected ...
            self.assertEqual(self.post(self.b, f'/v1/integrations/{connection_id}/remove', {}).status_code, 404)
            removed = self.post(self.a, f'/v1/integrations/{connection_id}/remove', {})                                     # ... but a connection can always be ended
        self.assertEqual(removed.status_code, 200, removed.content)
        self.assertEqual(removed.json()['receipt']['source'], 'customer')
        self.assertEqual(self.rows('SELECT count(*) FROM connector_secrets')[0][0], 0)
        self.assertEqual(self.a.get('/v1/controls', secure=True).json()['connections'], [])


class WriteCycle(Base):
    def test_preview_approve_execute_once_verify_undo_through_the_routes(self):
        connection_id = self.connect()
        action, request, conversation = self.propose(connection_id, {'folder': 'inbox', 'title': 'Plan', 'body': 'Draft'})
        waiting = self.a.get('/v1/handoffs', secure=True).json()['waiting']
        self.assertEqual([(w['kind'], w['action_id']) for w in waiting], [('action_approval', action['id'])])
        task = next(t for t in self.a.get('/v1/work', secure=True).json()['tasks'] if t['id'] == request)
        need = next(n for n in task['needs'] if n['kind'] == 'action')                                                    # shown on the task that asked, as "needs you"
        self.assertEqual((need['id'], need['payload_hash'], task['attention']), (action['id'], action['payload_hash'], 'approval'))
        self.assertEqual(self.post(self.b, f'/v1/actions/{action["id"]}/approve', {'payload_hash': action['payload_hash']}).status_code, 404)
        self.assertEqual(self.b.get(f'/v1/actions/{action["id"]}', secure=True).status_code, 404)
        self.assertEqual(self.post(self.a, f'/v1/actions/{action["id"]}/approve', {'payload_hash': '0' * 64}).status_code, 409)       # another payload: no approval
        approved = self.post(self.a, f'/v1/actions/{action["id"]}/approve', {'payload_hash': action['payload_hash']})
        self.assertEqual((approved.status_code, approved.json()['action']['state']), (200, 'approved'))
        self.assertEqual(self.post(self.a, f'/v1/actions/{action["id"]}/approve', {'payload_hash': action['payload_hash']}).status_code, 409)   # the second click
        runner = wiring.action_runner()
        runner.tick(); runner.tick()
        done = self.a.get(f'/v1/actions/{action["id"]}', secure=True).json()['action']
        self.assertEqual((done['state'], done['verified']), ('done', True))
        self.assertEqual(self.rows("SELECT count(*) FROM synthetic_records WHERE kind='note'")[0][0], 1)
        resumed = self.rows("SELECT message FROM customer_requests WHERE conversation_id=%s ORDER BY sequence DESC LIMIT 1", [conversation])[0][0]
        self.assertIn('carried it out once', resumed)                                                                     # the chat that waited was resumed with the outcome
        undo = self.post(self.a, f'/v1/actions/{action["id"]}/undo', {})
        self.assertEqual((undo.status_code, undo.json()['action']['kind']), (201, 'note.delete'))
        self.post(self.a, f'/v1/actions/{undo.json()["action"]["id"]}/approve', {'payload_hash': undo.json()['action']['payload_hash']})
        runner.tick()
        self.assertEqual(self.a.get(f'/v1/actions/{action["id"]}', secure=True).json()['action']['state'], 'undone')
        self.assertEqual(self.rows("SELECT deleted FROM synthetic_records WHERE kind='note'")[0][0], 1)
        listed = self.a.get('/v1/actions', secure=True).json()['actions']
        self.assertEqual(len(listed), 2)
        self.assertEqual(self.b.get('/v1/actions', secure=True).json()['actions'], [])

    def test_what_cannot_be_undone_offers_its_registered_follow_up(self):
        connection_id = self.connect()
        action, _r, _c = self.propose(connection_id, {'folder': 'inbox', 'to': 'sam', 'text': 'Hello'}, kind='message.send')
        self.assertEqual(action['preview']['irreversible'], 'A message that has been sent cannot be taken back.')
        self.post(self.a, f'/v1/actions/{action["id"]}/approve', {'payload_hash': action['payload_hash']})
        wiring.action_runner().tick()
        self.assertEqual(self.post(self.a, f'/v1/actions/{action["id"]}/undo', {}).status_code, 409)
        self.assertEqual(self.post(self.a, f'/v1/actions/{action["id"]}/compensate', {'kind': 'note.delete'}).status_code, 409)
        follow = self.post(self.a, f'/v1/actions/{action["id"]}/compensate', {'kind': 'message.correction'})
        self.assertEqual((follow.status_code, follow.json()['action']['compensates']), (201, action['id']))

    def test_automatic_approval_is_a_choice_and_never_silent_for_what_cannot_be_undone(self):
        connection_id = self.connect()
        self.assertEqual(self.post(self.a, f'/v1/integrations/{connection_id}/auto-approve', {'kind': 'message.send', 'enabled': True}).status_code, 400)
        ok = self.post(self.a, f'/v1/integrations/{connection_id}/auto-approve', {'kind': 'note.create', 'enabled': True})
        self.assertEqual((ok.status_code, ok.json()['automatic_approvals']), (200, [{'kind': 'note.create', 'include_irreversible': False}]))
        self.assertEqual(self.post(self.b, f'/v1/integrations/{connection_id}/auto-approve', {'kind': 'note.create', 'enabled': True}).status_code, 404)
        action, _r, _c = self.propose(connection_id, {'folder': 'inbox', 'title': 'Auto', 'body': ''})
        self.assertEqual(action['state'], 'approved')

    def test_a_question_is_answered_through_its_route_by_its_own_account_only(self):
        from agentai_platform.handoff import Handoffs
        request, conversation = self.request_id()
        with wiring.store().connect() as con:
            handoff = Handoffs(wiring.store()).create(con, account_id=self.account_ids[0], actor_id='x', kind='question', request_id=request, question='Which one?', options=['A', 'B'])
        self.assertEqual(self.post(self.b, f'/v1/handoffs/{handoff}/answer', {'answer': 'A'}).status_code, 404)
        self.assertEqual(self.post(self.a, f'/v1/handoffs/{handoff}/answer', {'answer': ''}).status_code, 400)
        self.assertEqual(self.post(self.a, f'/v1/handoffs/{handoff}/answer', {'answer': 'B'}).status_code, 200)
        self.assertEqual(self.post(self.a, f'/v1/handoffs/{handoff}/answer', {'answer': 'A'}).status_code, 409)

    def test_several_questions_are_answered_together_and_each_answer_must_fit_its_question(self):
        from agentai_platform.handoff import Handoffs
        request, conversation = self.request_id()
        asked = [{'question': 'Which size?', 'options': [{'label': 'M', 'price': '$20'}, {'label': 'L'}]}, {'question': 'Which colour?', 'options': []}]
        with wiring.store().connect() as con:
            handoff = Handoffs(wiring.store()).create(con, account_id=self.account_ids[0], actor_id='x', kind='question', request_id=request, question='1. Which size? 2. Which colour?',
                                                      evidence={'questions': asked})
        self.assertEqual(self.a.get('/v1/handoffs', secure=True).json()['waiting'][0]['questions'], asked)
        for wrong in ({'answers': [{'choice': 'XL'}, {'skip': True}]}, {'answers': [{'choice': 'M'}]}, {'answers': 'M'}, {'answer': 7}):
            self.assertEqual(self.post(self.a, f'/v1/handoffs/{handoff}/answer', wrong).status_code, 400, wrong)
        done = self.post(self.a, f'/v1/handoffs/{handoff}/answer', {'answers': [{'choice': 'M'}, {'text': 'navy'}]})
        self.assertEqual((done.status_code, done.json()['handoff']['state'], done.json()['handoff']['in_place']), (200, 'answered', False))

    def test_changes_are_off_until_the_owner_switch_is_on(self):
        connection_id = self.connect()
        with patch.object(wiring, 'switch_on', lambda name: name == 'synthetic_connector'):
            self.assertEqual(self.post(self.a, f'/v1/integrations/{connection_id}/auto-approve', {'kind': 'note.create', 'enabled': True}).status_code, 503)
            from agentai_platform.connector_kit import ConnectorFault
            with self.assertRaises(ConnectorFault):
                self.propose(connection_id, {'folder': 'inbox', 'title': 'x', 'body': ''})


class DataLifecycle(Base):
    def test_the_retention_page_is_the_table(self):
        from agentai_platform import retention
        shown = self.a.get('/v1/retention', secure=True).json()
        self.assertEqual(shown['rules'], retention.public())
        self.assertTrue(shown['self_service'])

    def test_an_export_is_made_downloaded_once_and_only_by_its_account(self):
        conversation = self.conversation()
        self.post(self.a, f'/v1/conversations/{conversation}/send', {'message': 'my private note', 'key': 'k-exp'})
        self.connect()
        asked = self.post(self.a, '/v1/exports', {})
        self.assertEqual(asked.status_code, 202, asked.content)
        export = asked.json()['export']['id']
        self.assertEqual(self.post(self.a, '/v1/exports', {}).status_code, 409)
        wiring.account_jobs().tick()
        self.assertEqual(self.a.get(f'/v1/exports/{export}', secure=True).json()['export']['state'], 'completed')
        self.assertEqual(self.b.get(f'/v1/exports/{export}', secure=True).status_code, 404)
        self.assertEqual(self.post(self.b, f'/v1/exports/{export}/ticket', {}).status_code, 404)
        link = self.post(self.a, f'/v1/exports/{export}/ticket', {}).json()['path']
        anonymous = self.new_client()                                                                                     # the link itself proves the caller
        got = anonymous.get(link, secure=True)
        self.assertEqual((got.status_code, got['Content-Type']), (200, 'application/zip'))
        archive = zipfile.ZipFile(io.BytesIO(b''.join(got.streaming_content)))
        self.assertIn('my private note', archive.read('conversations/messages.json').decode())
        whole = b''.join(archive.read(n) for n in archive.namelist())
        for leak in (b'synthetic-', b'refresh-', b'secret_ref', b'ciphertext'):
            self.assertNotIn(leak, whole)
        self.assertEqual(anonymous.get(link, secure=True).status_code, 404)                                               # once
        self.assertEqual(anonymous.get(f'/v1/exports/{export}/download?ticket=nope', secure=True).status_code, 404)

    def test_deleting_one_chat(self):
        conversation = self.conversation()
        self.post(self.a, f'/v1/conversations/{conversation}/send', {'message': 'forget this', 'key': 'k-del'})
        self.assertEqual(self.post(self.b, f'/v1/conversations/{conversation}/delete', {}).status_code, 404)
        with connection.cursor() as c:                                                                                     # its task is over
            c.execute("UPDATE customer_requests SET state='completed' WHERE conversation_id=%s", [conversation])
        done = self.post(self.a, f'/v1/conversations/{conversation}/delete', {})
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(self.rows('SELECT count(*) FROM chat_messages WHERE conversation_id=%s', [conversation])[0][0], 0)
        self.assertEqual(self.a.get('/v1/conversations', secure=True).json()['conversations'], [])
        self.assertEqual(self.a.get(f'/v1/conversations/{conversation}/messages', secure=True).status_code, 404)

    def test_closing_an_account_end_to_end_and_the_scan_finds_only_what_stays(self):
        from django.contrib.auth.models import User
        from accounts.models import Identity
        # A deliverable address: mail to a reserved name (@example.invalid, the other tests' users) is never sent (accounts/delivery.py deliverable).
        User.objects.filter(pk__in=Identity.objects.filter(account_id=self.account_ids[0]).values('user')).update(email='closing.customer@mailbox.lumina-tests.net')
        conversation = self.conversation()
        self.post(self.a, f'/v1/conversations/{conversation}/send', {'message': 'everything of mine', 'key': 'k-off'})
        with connection.cursor() as c:
            c.execute("UPDATE customer_requests SET state='completed' WHERE account_id=%s", [self.account_ids[0]])
        self.connect()
        account = self.account_ids[0]
        self.assertIsNone(self.a.get('/v1/account/offboarding', secure=True).json()['offboarding'])
        self.assertEqual(self.post(self.b, '/v1/account/offboarding/cancel', {}).status_code, 409)
        started = self.post(self.a, '/v1/account/offboarding', {})
        self.assertEqual((started.status_code, started.json()['offboarding']['waiting_for']), (200, 'export_choice'))
        self.assertEqual(self.post(self.a, '/v1/account/offboarding/skip', {}).status_code, 200)
        jobs = wiring.account_jobs()
        for _ in range(8):
            jobs.tick()
        report = json.loads(self.rows("SELECT report_json FROM account_jobs WHERE account_id=%s AND kind='deletion'", [account])[0][0])
        self.assertEqual((report['verification']['clean'], report['verification']['found']), (True, {}))                 # the verification scan: nothing but what stays by design
        self.assertEqual(self.rows('SELECT status FROM accounts WHERE id=%s', [account])[0][0], 'deleted')
        self.assertEqual(self.rows('SELECT count(*) FROM chat_messages WHERE account_id=%s', [account])[0][0], 0)
        self.assertEqual(self.rows('SELECT count(*) FROM connector_secrets WHERE account_id=%s', [account])[0][0], 0)
        erased = self.rows("SELECT email FROM auth_user WHERE username LIKE 'deleted-%%'")[0][0]
        self.assertTrue(erased.endswith('@deleted.invalid') and 'chatter' not in erased)                                  # the address is erased
        self.assertEqual(self.rows("SELECT count(*) FROM accounts_tombstone WHERE account_id=%s AND kind='account'", [account])[0][0], 1)
        self.assertEqual(self.a.get('/v1/conversations', secure=True).status_code, 401)                                   # nobody can sign in to it
        self.assertEqual(self.b.get('/v1/conversations', secure=True).status_code, 200)                                   # the other customer is untouched
        from django.core import mail
        self.assertEqual([m.subject for m in mail.outbox], ['Your Lumina account has been deleted'])
        self.assertIn('Nothing of yours is left', mail.outbox[0].body)

    def test_a_second_customer_can_be_deleted_after_the_first(self):
        """Found by the live proof: sign-in addresses are unique, so two deleted customers cannot both be left with an empty one."""
        jobs = wiring.account_jobs()
        for account in self.account_ids:
            jobs.start_offboarding_by_operator(account, 'test', cooling_off=0)
        for _ in range(12):
            jobs.tick()
        states = self.rows("SELECT state FROM account_jobs WHERE kind='deletion' ORDER BY created_epoch")
        self.assertEqual([s[0] for s in states], ['completed', 'completed'])
        self.assertEqual(self.rows("SELECT count(*) FROM auth_user WHERE email LIKE '%%@deleted.invalid'")[0][0], 2)
        self.assertEqual(self.rows("SELECT count(*) FROM auth_user WHERE email LIKE '%%example.invalid'")[0][0], 0)

    def test_self_service_is_off_until_the_owner_switch_is_on(self):
        with patch.object(wiring, 'switch_on', lambda name: False):
            self.assertEqual(self.post(self.a, '/v1/exports', {}).status_code, 503)
            self.assertEqual(self.post(self.a, '/v1/account/offboarding', {}).status_code, 503)
            self.assertEqual(self.a.get('/v1/retention', secure=True).status_code, 200)

    def test_the_sweeper_command_runs_and_reports_counts_only(self):
        from django.core.management import call_command
        out = io.StringIO()
        call_command('retention_sweep', stdout=out)
        self.assertIn('"removed"', out.getvalue())
        out = io.StringIO()
        call_command('account_jobs', stdout=out); call_command('connector_refresh', stdout=out)
        self.assertNotIn('synthetic-', out.getvalue())


class LiveProofScript(Base):
    """deploy/phase23_live.py is what proves the exit gates on the server at deploy time. Here it runs against the test database, so the script itself is known to work."""
    def test_every_gate_passes_and_the_disposable_account_ends_deleted(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('phase23_live', Path(__file__).resolve().parents[1] / 'deploy' / 'phase23_live.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

        class Enabled:
            stdout = 'enabled\n'
        out = io.StringIO()
        with patch.object(module.subprocess, 'run', lambda *a, **k: Enabled()), patch.object(module.time, 'sleep', lambda s: None), patch('sys.stdout', out), \
                override_settings(ALLOWED_HOSTS=['testserver']):
            code = module.main()
        report = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual({c['id']: c['passed'] for c in report['cases']},
                         {name: True for name in ('P2-ROLES', 'P2-SWEEPER', 'P3-WRITE-CYCLE', 'P3-COMPENSATION', 'P3-WORKFLOW', 'P3-HANDOFF', 'P3-PARTIAL', 'P2-OFFBOARD')}, out.getvalue())
        self.assertEqual((code, report['passed']), (0, True))
        self.assertEqual(self.rows('SELECT status FROM accounts WHERE id=%s', [report['account']])[0][0], 'deleted')
        self.assertEqual(self.rows('SELECT count(*) FROM synthetic_records WHERE account_id=%s', [report['account']])[0][0], 0)

    def test_it_refuses_to_start_without_the_switches(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('phase23_live', Path(__file__).resolve().parents[1] / 'deploy' / 'phase23_live.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        out = io.StringIO()
        with patch.object(wiring, 'switch_on', lambda name: False), patch('sys.stdout', out):
            self.assertEqual(module.main(), 2)
        self.assertIn('NOT RUN', out.getvalue())
        self.assertEqual(self.rows("SELECT count(*) FROM auth_user WHERE username LIKE 'p23-%%'")[0][0], 0)
