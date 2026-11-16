"""Roles, the one permission table, organizations and their policy (roadmap #12, #15)."""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform import organizations, permissions, safety, spend_limits
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.organizations import OrganizationService
from agentai_platform.security import NotFound, Principal, allowed, require
from agentai_platform.store import Store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize()
        with self.store.connect() as con:
            for a in ('a', 'b', 'c'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
        self.changed = []
        self.orgs = OrganizationService(self.store, clock=lambda: 1000, on_role_change=self.changed.append)
        self.a, self.b, self.c = (Principal(x, 'actor-' + x, 'customer') for x in 'abc')

    def role(self, account):
        with self.store.connect() as con:
            return permissions.member_role(con, account, 'actor-' + account)


class TheTable(Base):
    def test_every_row_of_the_table(self):
        """One check per row and role, generated from the table itself: the function answers exactly what the row says."""
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        for role in permissions.ROLES:
            if role != 'owner':
                self.orgs.set_role(self.a, 'actor-b', role)
            who = self.a if role == 'owner' else self.b
            with self.store.connect() as con:
                for action, roles in permissions.TABLE.items():
                    with self.subTest(action=action, role=role):
                        self.assertEqual(allowed(who, action, con=con), role in roles)
        self.assertGreaterEqual(len(permissions.TABLE), 30)

    def test_the_roles_are_what_the_roadmap_says(self):
        can = lambda role, action: permissions.role_allows(role, action)
        self.assertTrue(all(can('owner', a) for a in permissions.TABLE))                                  # the owner: everything
        self.assertTrue(can('admin', 'member.invite') and can('admin', 'policy.change') and can('admin', 'connection.create'))
        self.assertFalse(can('admin', 'billing.manage') or can('admin', 'account.delete'))                # not billing ownership, not deleting the organization
        self.assertTrue(can('member', 'task.run') and can('member', 'connection.create') and can('member', 'data.export'))
        self.assertFalse(can('member', 'member.invite') or can('member', 'policy.change'))
        self.assertTrue(can('viewer', 'conversation.read') and can('viewer', 'file.read'))
        self.assertFalse(can('viewer', 'task.run') or can('viewer', 'connection.create') or can('viewer', 'action.approve') or can('viewer', 'file.write'))

    def test_an_unknown_action_or_a_stranger_is_refused(self):
        with self.store.connect() as con:
            self.assertFalse(allowed(self.a, 'no.such.action', con=con))
            self.assertFalse(allowed(Principal('a', 'actor-b', 'customer'), 'task.run', con=con))          # not a member of that account
            self.assertFalse(allowed(Principal('a', 'actor-a', 'operator'), 'task.run', con=con))
            with self.assertRaises(NotFound):
                require(Principal('a', 'actor-b', 'customer'), 'task.run', con=con)
            with self.assertRaises(permissions.NotPermitted):
                require(self.a, 'no.such.action', con=con)

    def test_every_tool_the_assistant_can_be_given_names_an_action(self):
        from agentai_platform.browse.adapter import STEP_NAME, TOOL_NAME
        from agentai_platform.connector_tools import ConnectorTools
        from agentai_platform.file_tools import NAME as FILES
        from agentai_platform.location import NAME as LOCATION
        from agentai_platform.longterm_memory import RECALL_NAME, REMEMBER_NAME
        from agentai_platform.mcp_connections.relay import GENERIC
        from agentai_platform.mcp_connections.service import namespaced
        from agentai_platform.show_tool import NAME as SHOW
        from agentai_platform.task_progress import TOOL_NAME as PROGRESS
        names = [TOOL_NAME, STEP_NAME, PROGRESS, LOCATION, RECALL_NAME, REMEMBER_NAME, FILES, SHOW, namespaced('a' * 32, 'tool')] + [g['name'] for g in GENERIC] + sorted(ConnectorTools.names)
        for name in names:
            with self.subTest(tool=name):
                self.assertIn(permissions.tool_action(name), permissions.TABLE)
        self.assertIsNone(permissions.tool_action('something_new'))


class Organizations(Base):
    def test_every_account_is_an_organization_of_one_whose_customer_is_its_owner(self):
        self.assertEqual([self.role(x) for x in 'abc'], ['owner'] * 3)
        view = self.orgs.view(self.a)
        self.assertEqual((view['id'], view['your_role'], [m['role'] for m in view['members']]), ('a', 'owner', ['owner']))
        with self.store.connect() as con:
            self.assertEqual(permissions.organization_of(con, 'a'), 'a')                                   # same id: nothing changes for existing customers

    def test_a_member_joins_keeps_their_own_account_and_a_role_change_is_seen_at_once(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'viewer')
        with self.store.connect() as con:
            self.assertEqual(permissions.organization_of(con, 'b'), 'a')
            self.assertFalse(allowed(self.b, 'task.run', con=con))
            self.store._authorize(con, self.b)                                                           # still their own account: they can read it
        self.orgs.set_role(self.a, 'actor-b', 'member')
        with self.store.connect() as con:
            self.assertTrue(allowed(self.b, 'task.run', con=con))
        self.assertEqual(self.changed, ['actor-b', 'actor-b'])                                            # their sessions are ended each time, so the next request sees the role

    def test_only_managers_manage_and_only_an_owner_makes_an_owner(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'admin')
        self.orgs.add_member(self.b, 'c', 'actor-c', 'member')                                           # an admin may invite
        with self.assertRaises(permissions.NotPermitted):
            self.orgs.set_role(self.c, 'actor-b', 'viewer')                                              # a member may not
        with self.assertRaises(permissions.NotPermitted):
            self.orgs.set_role(self.b, 'actor-c', 'owner')                                               # an admin cannot make an owner
        with self.assertRaises(permissions.NotPermitted):
            self.orgs.remove_member(self.b, 'actor-a')                                                   # nor remove one
        with self.assertRaises(Conflict):
            self.orgs.set_role(self.a, 'actor-a', 'member')                                              # the last owner stays
        with self.assertRaises(ValueError):
            self.orgs.add_member(self.a, 'c', 'actor-c', 'owner')

    def test_a_removed_member_can_do_nothing_and_is_not_an_owner_by_default(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        self.assertEqual(self.orgs.remove_member(self.a, 'actor-b'), 'b')
        self.assertIsNone(self.role('b'))
        with self.store.connect() as con:
            self.assertFalse(allowed(self.b, 'conversation.read', con=con))
            with self.assertRaises(NotFound):
                self.store._authorize(con, self.b)

    def test_another_organization_cannot_be_read_or_changed(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        self.assertEqual(len(self.orgs.view(self.c)['members']), 1)
        with self.assertRaises(NotFound):
            self.orgs.set_role(self.c, 'actor-b', 'viewer')
        with self.assertRaises(Conflict):
            self.orgs.add_member(self.c, 'b', 'actor-b', 'member')                                       # already in another organization


class Policy(Base):
    def test_no_policy_is_todays_behaviour(self):
        with self.store.connect() as con:
            self.assertEqual(organizations.policy(con, 'a'), {})
            self.assertTrue(organizations.tool_allowed(con, 'a', 'lumina_browser') and organizations.connector_allowed(con, 'a', 'gmail'))
            self.assertEqual(organizations.write_rule(con, 'a', 'send'), 'allowed')
            self.assertTrue(organizations.own_model_key_allowed(con, 'a'))

    def test_what_the_organization_sets_applies_to_every_member_and_only_to_them(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        self.orgs.set_policy(self.a, 'tools_allowed', ['files', 'display'])
        self.orgs.set_policy(self.a, 'connectors_allowed', ['calendar'])
        self.orgs.set_policy(self.a, 'write_kinds', {'send': 'admin_approval', 'delete': 'blocked'})
        self.orgs.set_policy(self.a, 'own_model_key', False)
        with self.store.connect() as con:
            for account in ('a', 'b'):
                self.assertFalse(organizations.tool_allowed(con, account, 'lumina_browser'))
                self.assertTrue(organizations.tool_allowed(con, account, 'lumina_file_deliver'))
                self.assertTrue(organizations.tool_allowed(con, account, 'lumina_task_update'))          # not a tool group: never affected
                self.assertFalse(organizations.connector_allowed(con, account, 'gmail'))
                self.assertEqual([organizations.write_rule(con, account, k) for k in ('send', 'delete', 'write')], ['admin_approval', 'blocked', 'allowed'])
                self.assertFalse(organizations.own_model_key_allowed(con, account))
            self.assertTrue(organizations.tool_allowed(con, 'c', 'lumina_browser'))                      # another organization is untouched
        self.orgs.set_policy(self.a, 'tools_allowed', None)
        with self.store.connect() as con:
            self.assertTrue(organizations.tool_allowed(con, 'b', 'lumina_browser'))

    def test_a_member_cannot_change_policy_and_bad_values_are_refused(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        with self.assertRaises(permissions.NotPermitted):
            self.orgs.set_policy(self.b, 'own_model_key', False)
        for key, value in (('tools_allowed', ['rockets']), ('write_kinds', {'send': 'maybe'}), ('own_model_key', 'no'), ('nothing', True), ('member_spend_limits', {'task': -1})):
            with self.assertRaises(ValueError):
                self.orgs.set_policy(self.a, key, value)

    def test_the_tool_relay_refuses_what_the_role_or_the_organization_does_not_allow(self):
        from agentai_platform.tool_relay import ToolPermit
        permit = ToolPermit(self.store)
        with self.store.connect() as con:
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('b','d',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('b','p','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('b','p','c','d')")
            con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
                VALUES ('b','r1','actor-b','p','c','k','h','m','running',1)''')
        self.assertIsNone(permit.refusal('b', 'r1', 'lumina_browser'))
        self.assertIn('not available', permit.refusal('b', 'r1', 'a_tool_nobody_named'))
        self.orgs.add_member(self.a, 'b', 'actor-b', 'viewer')
        self.assertIn('not allowed to do this', permit.refusal('b', 'r1', 'lumina_browser'))               # a viewer's task cannot act
        self.orgs.set_role(self.a, 'actor-b', 'member')
        self.orgs.set_policy(self.a, 'tools_allowed', ['files'])
        self.assertIn('organization does not allow', permit.refusal('b', 'r1', 'lumina_browser'))
        self.assertFalse(permit.listed('b', 'lumina_browser'))
        self.assertTrue(permit.listed('b', 'lumina_file_deliver') and permit.listed('c', 'lumina_browser'))

    def test_spending_limits_the_organization_locks_win_over_a_members_own(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        with self.store.connect() as con:
            spend_limits.put(con, 'b', {'task': 9_000_000, 'daily': None, 'period': None})
        self.orgs.set_policy(self.a, 'member_spend_limits', {'task': 2_000_000, 'daily': 5_000_000, 'period': None, 'locked': True})
        with self.store.connect() as con:
            self.assertEqual(spend_limits.get(con, 'b'), {'task': 2_000_000, 'daily': 5_000_000, 'period': None})
            self.assertEqual(spend_limits.get(con, 'c'), {'task': None, 'daily': None, 'period': None})
        self.orgs.set_policy(self.a, 'member_spend_limits', {'task': 2_000_000, 'daily': None, 'period': None, 'locked': False})
        with self.store.connect() as con:
            self.assertEqual(spend_limits.get(con, 'b')['task'], 9_000_000)                              # only a default now: the member's own choice replaces it
            self.assertEqual(spend_limits.get(con, 'a')['task'], 2_000_000)

    def test_a_safety_switch_the_organization_set_overrides_the_members_and_privacy_stays_locked(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        with self.store.connect() as con:
            from tests.test_safety_gates import SAFETY_SQL
            con.executescript(SAFETY_SQL)                                                                 # the web layer's own migration makes this table
            safety.set_feature(con, 'b', 'queue_limit', False, 'actor-b')
            self.assertFalse(safety.is_on(con, 'b', 'queue_limit'))
            safety.set_for_organization(con, 'a', 'queue_limit', True, 'actor-a')
            self.assertTrue(safety.is_on(con, 'b', 'queue_limit'))                                        # the organization's "on" wins over the member's "off"
            row = next(r for r in safety.listing(con, 'b') if r['key'] == 'queue_limit')
            self.assertEqual((row['source'], row['lock']), ('organization', 'organization'))               # shown as set by the organization
            self.assertTrue(safety.is_on(con, 'c', 'queue_limit'))
            with self.assertRaises(safety.Locked):
                safety.set_for_organization(con, 'a', 'personal_data_scrub', False, 'actor-a')            # a privacy protection is never switched off for a whole organization
            safety.set_for_organization(con, 'a', 'queue_limit', False, 'actor-a')
            path = Path(self.tmp.name) / 'snapshot.json'
            safety.export_snapshot(con, path)
        reader = safety.Reader(path)
        self.assertFalse(reader.on('b', 'queue_limit') or reader.on('a', 'queue_limit'))                  # the other processes see the organization scope too
        self.assertTrue(reader.on('c', 'queue_limit'))


if __name__ == '__main__':
    unittest.main()
