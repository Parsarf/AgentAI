"""Organizations: who belongs, with which role, and what the organization decides for its members (roadmap Phase 2: the organization model, #12 role changes, #15 policy).

An organization owns one or more people. Each person has their own account and their own assistant cell, so a member's chats, files, memory and connections are as separate from
another member's as from another customer's. What an organization shares is its roles and its policy. Every customer today is an organization of one, whose owner they are.

Policy (#15) reuses the idea of the safety switches: a setting the organization has made overrides the member's own, and the member sees it as "set by your organization".
No row for a key means the member decides, which is exactly today's behaviour. Stdlib only: the worker, the tool relay and the connector layer read `policy()` directly.
"""
from __future__ import annotations
import json
import time

from . import permissions
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

# What an organization can decide. `kind` is how a value is checked; `plain` is the sentence the settings page shows.
TOOL_GROUPS = ('browser', 'files', 'memory', 'display', 'location', 'remote_tools', 'connectors', 'knowledge')
WRITE_RULES = ('allowed', 'admin_approval', 'blocked')
POLICIES = {
    'tools_allowed': {'kind': 'tool_list', 'plain': 'Which tools members\' assistants may use.'},
    'connectors_allowed': {'kind': 'name_list', 'plain': 'Which services members may connect.'},
    'write_kinds': {'kind': 'write_rules', 'plain': 'Which kinds of change the assistant may make in connected services, and which need an admin\'s approval as well.'},
    'member_spend_limits': {'kind': 'limits', 'plain': 'Spending limits that apply to every member.'},
    'own_model_key': {'kind': 'flag', 'plain': 'Whether members may use their own model key.'},
    'knowledge_sources': {'kind': 'name_list', 'plain': 'Which connected sources may be added to the knowledge index.'},
}
# What a tool the assistant can be given belongs to, for `tools_allowed` (a name no row covers belongs to no group and is not affected).
TOOL_GROUP_OF = {'lumina_browser': 'browser', 'lumina_browser_step': 'browser', 'lumina_file_deliver': 'files', 'lumina_memory_*': 'memory', 'lumina_show': 'display',
                 'lumina_request_location': 'location', 'lumina_mcp_*': 'remote_tools', 'mcp__*': 'remote_tools', 'lumina_connector_*': 'connectors',
                 'lumina_mail_*': 'connectors', 'lumina_calendar_*': 'connectors',       # the mail and calendar tools read through connected accounts too
                 'lumina_meeting_brief': 'connectors', 'lumina_meeting_times': 'connectors', 'lumina_meeting_wait': 'connectors', 'lumina_knowledge_*': 'knowledge', 'lumina_commitment_*': 'knowledge', 'lumina_commitments': 'knowledge'}


def tool_group(name):
    if name in TOOL_GROUP_OF:
        return TOOL_GROUP_OF[name]
    for key, group in TOOL_GROUP_OF.items():
        if key.endswith('*') and isinstance(name, str) and name.startswith(key[:-1]):
            return group
    return None


def clean_policy(key, value):
    """Validate one policy value. `None` removes the policy (the member decides again). Raises ValueError."""
    spec = POLICIES.get(key)
    if spec is None:
        raise ValueError('unknown policy')
    if value is None:
        return None
    kind = spec['kind']
    if kind == 'flag':
        if type(value) is not bool:
            raise ValueError('invalid policy value')
        return value
    if kind in ('tool_list', 'name_list'):
        if not isinstance(value, list) or len(value) > 64 or any(not isinstance(v, str) or not 1 <= len(v) <= 64 for v in value):
            raise ValueError('invalid policy value')
        if kind == 'tool_list' and set(value) - set(TOOL_GROUPS):
            raise ValueError('unknown tool group')
        return sorted(set(value))
    if kind == 'write_rules':
        if not isinstance(value, dict) or len(value) > 40 or any(not isinstance(k, str) or not 1 <= len(k) <= 40 or v not in WRITE_RULES for k, v in value.items()):
            raise ValueError('invalid policy value')
        return dict(sorted(value.items()))
    if kind == 'limits':
        from . import spend_limits
        if not isinstance(value, dict) or set(value) - {'task', 'daily', 'period', 'locked'}:
            raise ValueError('invalid policy value')
        limits = spend_limits.clean({k: value.get(k) for k in spend_limits.FIELDS})
        return {**limits, 'locked': bool(value.get('locked', True))}
    raise ValueError('unknown policy kind')


def policy(con, account_id: str) -> dict:
    """{key: value} of what this account's organization has decided. {} when it decided nothing, the tables are not there, or anything fails: no policy is today's behaviour."""
    try:
        rows = con.execute("""SELECT p.key,p.value_json FROM organization_policies p JOIN accounts a ON a.organization_id=p.organization_id WHERE a.id=?""", (account_id,)).fetchall()
        return {r[0]: json.loads(r[1]) for r in rows if r[0] in POLICIES}
    except Exception:
        return {}


def tool_allowed(con, account_id: str, tool_name: str) -> bool:
    allowed = policy(con, account_id).get('tools_allowed')
    group = tool_group(tool_name)
    return allowed is None or group is None or group in allowed


def connector_allowed(con, account_id: str, service: str) -> bool:
    allowed = policy(con, account_id).get('connectors_allowed')
    return allowed is None or service in allowed


def write_rule(con, account_id: str, kind: str) -> str:
    """'allowed' | 'admin_approval' | 'blocked' for one write kind ('*' in the policy is the default for kinds it does not name)."""
    rules = policy(con, account_id).get('write_kinds') or {}
    return rules.get(kind, rules.get('*', 'allowed'))


def own_model_key_allowed(con, account_id: str) -> bool:
    return policy(con, account_id).get('own_model_key') is not False


def knowledge_source_allowed(con, account_id: str, source: str) -> bool:
    allowed = policy(con, account_id).get('knowledge_sources')
    return allowed is None or source in allowed


class OrganizationService:
    """Members, roles and policy. `on_role_change(actor_id)` is told when a person's role or membership changes, so their open sessions end and the next request sees the new
    role (the web layer bumps the identity epoch, as "sign out everywhere" does)."""

    def __init__(self, store, *, clock=time.time, on_role_change=None):
        self.store, self.clock, self.on_role_change = store, clock, on_role_change
        self.coordinator = Coordinator(store, clock=clock)

    def _org(self, con, principal: Principal) -> str:
        return permissions.organization_of(con, principal.account_id)

    def view(self, principal: Principal) -> dict:
        """The caller's organization: its members with their roles, and its policy with which settings are locked for the caller."""
        with self.store.connect() as con:
            require(principal, 'member.read', con=con)
            org = self._org(con, principal)
            row = con.execute('SELECT id,name,status FROM organizations WHERE id=?', (org,)).fetchone()
            mine = permissions.member_role(con, principal.account_id, principal.actor_id)
            members = [{'actor_id': r['actor_id'], 'account_id': r['account_id'], 'role': r['role'], 'you': r['actor_id'] == principal.actor_id and r['account_id'] == principal.account_id}
                       for r in con.execute("SELECT actor_id,account_id,role FROM organization_members WHERE organization_id=? AND status='active' ORDER BY created_epoch,actor_id", (org,))]
            if not members:                                     # a single-person account from before organizations: its customer is its owner
                members = [{'actor_id': principal.actor_id, 'account_id': principal.account_id, 'role': 'owner', 'you': True}]
            current = policy(con, principal.account_id)
        return {'id': org, 'name': row['name'] if row else '', 'your_role': mine, 'members': members,
                'can': {a: permissions.role_allows(mine or '', a) for a in ('member.invite', 'member.remove', 'member.role', 'policy.change', 'billing.manage', 'organization.export', 'account.delete')},
                'policy': [{'key': key, 'plain': spec['plain'], 'value': current.get(key), 'set': key in current} for key, spec in POLICIES.items()],
                'tool_groups': list(TOOL_GROUPS), 'write_rules': list(WRITE_RULES)}

    def add_member(self, principal: Principal, account_id: str, actor_id: str, role: str = 'member'):
        """Put an existing person (their own account, their own assistant) into the caller's organization. The invitation screens come later; the check does not."""
        if role not in permissions.ROLES or role == 'owner':
            raise ValueError('invalid role')
        with self.coordinator.transaction() as con:
            require(principal, 'member.invite', con=con)
            org = self._org(con, principal)
            if not con.execute("SELECT 1 FROM memberships WHERE account_id=? AND actor_id=? AND role='customer' AND status='active'", (account_id, actor_id)).fetchone():
                raise NotFound('unavailable')
            held = con.execute('SELECT organization_id FROM accounts WHERE id=?', (account_id,)).fetchone()
            others = con.execute("SELECT count(*) FROM organization_members WHERE organization_id=? AND status='active' AND NOT (account_id=? AND actor_id=?)", (held[0], account_id, actor_id)).fetchone()[0] if held and held[0] else 0
            if held and held[0] and held[0] != org and (held[0] != account_id or others):
                raise Conflict('this person already belongs to another organization')
            now = int(self.clock())
            con.execute('DELETE FROM organization_members WHERE account_id=? AND actor_id=?', (account_id, actor_id))
            con.execute('UPDATE accounts SET organization_id=? WHERE id=?', (org, account_id))
            con.execute("INSERT INTO organization_members(organization_id,actor_id,account_id,role,status,created_epoch,updated_epoch) VALUES (?,?,?,?,'active',?,?)", (org, actor_id, account_id, role, now, now))
            # Knowledge this person had shared belongs to the organization they left: it becomes theirs alone again, and is indexed again under the new organization.
            con.execute("UPDATE knowledge_sources SET organization_id=?,scope='account',audience='',state=CASE WHEN state='ready' THEN 'queued' ELSE state END,step='moved to another organization' WHERE account_id=?",
                        (org, account_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, actor_id, 'organization.member.add', 'completed')
        self._changed(actor_id)

    # -- named groups (#40): shared knowledge can be meant for one group of people only --------------------------------------------------------------------
    def groups(self, principal: Principal) -> list:
        with self.store.connect() as con:
            require(principal, 'member.read', con=con)
            org = self._org(con, principal)
            groups = [dict(r) for r in con.execute('SELECT id,name,created_epoch FROM organization_groups WHERE organization_id=? ORDER BY lower(name)', (org,))]
            for g in groups:
                g['members'] = [r['actor_id'] for r in con.execute('SELECT actor_id FROM organization_group_members WHERE organization_id=? AND group_id=? ORDER BY actor_id', (org, g['id']))]
        return groups

    def create_group(self, principal: Principal, name: str) -> dict:
        import uuid
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('invalid name')
        with self.coordinator.transaction() as con:
            require(principal, 'group.manage', con=con)
            org = self._org(con, principal)
            if con.execute('SELECT 1 FROM organization_groups WHERE organization_id=? AND lower(name)=lower(?)', (org, name.strip())).fetchone():
                raise Conflict('a group with that name exists')
            if con.execute('SELECT count(*) FROM organization_groups WHERE organization_id=?', (org,)).fetchone()[0] >= 100:
                raise Conflict('too many groups')
            group = uuid.uuid4().hex
            con.execute('INSERT INTO organization_groups(organization_id,id,name,created_epoch) VALUES (?,?,?,?)', (org, group, name.strip(), int(self.clock())))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, group, 'organization.group.create', 'completed')
            return {'id': group, 'name': name.strip(), 'members': []}

    def set_group_member(self, principal: Principal, group_id: str, actor_id: str, member: bool) -> dict:
        with self.coordinator.transaction() as con:
            require(principal, 'group.manage', con=con)
            org = self._org(con, principal)
            if not con.execute('SELECT 1 FROM organization_groups WHERE organization_id=? AND id=?', (org, str(group_id))).fetchone():
                raise NotFound('unavailable')
            if member:
                if not con.execute("SELECT 1 FROM organization_members WHERE organization_id=? AND actor_id=? AND status='active'", (org, str(actor_id))).fetchone():
                    raise NotFound('unavailable')
                con.execute('INSERT OR IGNORE INTO organization_group_members(organization_id,group_id,actor_id,created_epoch) VALUES (?,?,?,?)', (org, group_id, actor_id, int(self.clock())))
            else:
                con.execute('DELETE FROM organization_group_members WHERE organization_id=? AND group_id=? AND actor_id=?', (org, group_id, actor_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, group_id, 'organization.group.member', 'completed')
        return {'group': group_id, 'actor_id': actor_id, 'member': bool(member)}

    def delete_group(self, principal: Principal, group_id: str) -> dict:
        """Remove a group. Sources shared with it stop being shared (they are their owners' alone again): nobody gains access by a group disappearing."""
        with self.coordinator.transaction() as con:
            require(principal, 'group.manage', con=con)
            org = self._org(con, principal)
            if not con.execute('SELECT 1 FROM organization_groups WHERE organization_id=? AND id=?', (org, str(group_id))).fetchone():
                raise NotFound('unavailable')
            con.execute('DELETE FROM organization_group_members WHERE organization_id=? AND group_id=?', (org, group_id))
            con.execute('DELETE FROM organization_groups WHERE organization_id=? AND id=?', (org, group_id))
            con.execute("UPDATE knowledge_sources SET scope='account',audience='',state=CASE WHEN state='ready' THEN 'queued' ELSE state END WHERE organization_id=? AND audience=?",
                        (org, 'group:' + group_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, group_id, 'organization.group.delete', 'completed')
        return {'deleted': group_id}

    def set_role(self, principal: Principal, actor_id: str, role: str):
        if role not in permissions.ROLES:
            raise ValueError('invalid role')
        with self.coordinator.transaction() as con:
            require(principal, 'member.role', con=con)
            org = self._org(con, principal)
            mine = permissions.member_role(con, principal.account_id, principal.actor_id)
            row = con.execute("SELECT role FROM organization_members WHERE organization_id=? AND actor_id=? AND status='active'", (org, actor_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            if (role == 'owner' or row['role'] == 'owner') and mine != 'owner':
                raise permissions.NotPermitted('member.role')           # only an owner makes or unmakes an owner
            owners = con.execute("SELECT count(*) FROM organization_members WHERE organization_id=? AND role='owner' AND status='active'", (org,)).fetchone()[0]
            if row['role'] == 'owner' and role != 'owner' and owners <= 1:
                raise Conflict('an organization keeps at least one owner')
            con.execute('UPDATE organization_members SET role=?,updated_epoch=? WHERE organization_id=? AND actor_id=?', (role, int(self.clock()), org, actor_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, actor_id, 'organization.member.role', 'completed')
        self._changed(actor_id)

    def remove_member(self, principal: Principal, actor_id: str) -> str:
        """Take a person out of the organization. -> their account id (the caller offboards that account's data: offboarding.py). The last owner cannot be removed."""
        with self.coordinator.transaction() as con:
            require(principal, 'member.remove', con=con)
            org = self._org(con, principal)
            mine = permissions.member_role(con, principal.account_id, principal.actor_id)
            row = con.execute("SELECT role,account_id FROM organization_members WHERE organization_id=? AND actor_id=? AND status='active'", (org, actor_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['role'] == 'owner':
                if mine != 'owner':
                    raise permissions.NotPermitted('member.remove')
                if con.execute("SELECT count(*) FROM organization_members WHERE organization_id=? AND role='owner' AND status='active'", (org,)).fetchone()[0] <= 1:
                    raise Conflict('an organization keeps at least one owner')
            con.execute("UPDATE organization_members SET status='removed',updated_epoch=? WHERE organization_id=? AND actor_id=?", (int(self.clock()), org, actor_id))
            con.execute('DELETE FROM organization_group_members WHERE organization_id=? AND actor_id=?', (org, actor_id))
            # What they shared is no longer shared: a removed person's documents are not left readable by the organization they left.
            con.execute("UPDATE knowledge_sources SET scope='account',audience='',state=CASE WHEN state='ready' THEN 'queued' ELSE state END WHERE account_id=? AND scope='organization'",
                        (row['account_id'],))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, actor_id, 'organization.member.remove', 'completed')
            account = row['account_id']
        self._changed(actor_id)
        return account

    def set_policy(self, principal: Principal, key: str, value):
        value = clean_policy(key, value)
        with self.coordinator.transaction() as con:
            require(principal, 'policy.change', con=con)
            org = self._org(con, principal)
            if not con.execute('SELECT 1 FROM organizations WHERE id=?', (org,)).fetchone():
                con.execute('INSERT INTO organizations(id,created_epoch) VALUES (?,?)', (org, int(self.clock())))
            if value is None:
                con.execute('DELETE FROM organization_policies WHERE organization_id=? AND key=?', (org, key))
            else:
                con.execute('INSERT OR REPLACE INTO organization_policies(organization_id,key,value_json,updated_by,updated_epoch) VALUES (?,?,?,?,?)',
                            (org, key, json.dumps(value, sort_keys=True), principal.actor_id, int(self.clock())))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, key, 'organization.policy.' + ('clear' if value is None else 'set'), 'completed')
        return self.view(principal)

    def _changed(self, actor_id):
        if self.on_role_change is not None:
            self.on_role_change(actor_id)
