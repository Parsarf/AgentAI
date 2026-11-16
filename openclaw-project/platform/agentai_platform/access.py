"""What your assistant can access (roadmap #14): one picture of every way the assistant can reach something, built from the SAME records enforcement reads.

Nothing here is a description kept beside the truth. A connection's line comes from its `connector_grants` rows (the rows connector_kit checks before every call); a remote
tool server's line from its `mcp_tool_choices`; the tools from the list the tool relay serves, with the organization's policy applied exactly as the relay applies it; saved
logins, the model key, memory and schedules from their own tables. A test compares this picture with those tables so the two cannot drift.

Names and counts only. Never a token, a password, a key or a secret reference.
"""
from __future__ import annotations
import json
import time

from . import handoff, organizations, permissions
from .connectors import ConnectorService


class AccessOverview:
    """`tool_names(account)`: the names the tool relay offers this account right now. `model_key(account)`: {'host','hint'} or None. `memory_count(account)`: int or None
    (None: long-term memory is not on for the account)."""

    def __init__(self, store, connectors, client, *, tool_names=None, model_key=None, memory_count=None, clock=time.time):
        self.store, self.connectors, self.client, self.clock = store, connectors, client, clock
        self.tool_names, self.model_key, self.memory_count = tool_names, model_key, memory_count

    def view(self, principal) -> dict:
        account = principal.account_id
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            role = permissions.member_role(con, account, principal.actor_id)
            policy = organizations.policy(con, account)
            connections = []
            for row in con.execute("SELECT * FROM connector_connections WHERE account_id=? AND state!='revoked' ORDER BY created_epoch", (account,)).fetchall():
                declared = self.connectors.declared(row['service'])
                scope = ConnectorService.scope(con, account, row['id'])
                grants = [dict(g) for g in con.execute('SELECT resource_kind,resource_id,resource_name,access FROM connector_grants WHERE account_id=? AND connection_id=? ORDER BY resource_kind,resource_id',
                                                       (account, row['id']))]
                auto = [{'kind': r['kind'], 'include_irreversible': bool(r['include_irreversible'])}
                        for r in con.execute('SELECT kind,include_irreversible FROM action_auto_approvals WHERE account_id=? AND connection_id=? ORDER BY kind', (account, row['id']))]
                connections.append({
                    'id': row['id'], 'service': row['service'], 'label': declared.label if declared else getattr(self.connectors.catalog.get(row['service']), 'label', row['service']),
                    'identity': row['identity_label'], 'state': row['state'], 'needs_you': row['state'] == 'reconnect_required', 'needs_reason': row['needs_reason'],
                    'says': ConnectorService.describe_scope(scope), 'grants': grants, 'can_be_limited': bool(declared and declared.resource_kinds),
                    'resource_kinds': list(declared.resource_kinds) if declared else [], 'last_used_epoch': row['last_used_epoch'],
                    'freshness': self.client.freshness.listing(con, account, row['id'], declared) if self.client is not None else [],
                    'kinds_of_change': [{'name': w.name, 'label': w.label, 'can_undo': bool(w.undo), 'rule': organizations.write_rule(con, account, w.policy_kind)} for w in (declared.write_kinds if declared else ())],
                    'automatic_approvals': auto, 'allowed_by_organization': organizations.connector_allowed(con, account, row['service'])})
            remote = []
            try:
                for row in con.execute('SELECT id,name,url,state,enabled FROM mcp_connections WHERE account_id=? ORDER BY created_epoch', (account,)).fetchall():
                    tools = [r[0] for r in con.execute('SELECT tool_name FROM mcp_tool_choices WHERE account_id=? AND connection_id=? AND enabled=1 ORDER BY tool_name', (account, row['id']))]
                    from urllib.parse import urlsplit
                    remote.append({'id': row['id'], 'name': row['name'], 'recipient': urlsplit(row['url']).hostname, 'state': row['state'], 'enabled': bool(row['enabled']), 'tools_allowed': tools,
                                   'can_be_limited': False, 'says': f'Can use {len(tools)} tool{"s" if len(tools) != 1 else ""} you allowed. This service cannot be limited to parts of your account: '
                                                                    'you choose which of its tools are allowed.'})
            except Exception as error:
                if 'no such table' not in str(error):
                    raise
            saved = [{'kind': r['kind'], 'label': r['label'], 'site': r['site']} for r in con.execute('SELECT kind,label,site FROM vault_items WHERE account_id=? ORDER BY created_epoch', (account,))]
            unattended = [{'kind': 'schedule', 'name': r['name'], 'state': r['state'], 'pause_reason': r['pause_reason'], 'needs_connection_id': r['needs_connection_id']}
                          for r in con.execute('SELECT name,state,pause_reason,needs_connection_id FROM schedules WHERE account_id=? ORDER BY created_epoch', (account,))]
            unattended += [{'kind': 'watcher', 'name': r['name'], 'state': r['state'], 'pause_reason': None, 'needs_connection_id': None}
                           for r in con.execute('SELECT name,state FROM watchers WHERE account_id=? ORDER BY created_epoch', (account,))]
            names = sorted(self.tool_names(account)) if self.tool_names is not None else []
            tools = [{'name': n, 'group': organizations.tool_group(n), 'allowed': organizations.tool_allowed(con, account, n) and permissions.role_allows(role or '', permissions.tool_action(n) or ''),
                      'set_by_organization': not organizations.tool_allowed(con, account, n)} for n in names]
        key = self.model_key(account) if self.model_key is not None else None
        count = self.memory_count(account) if self.memory_count is not None else None
        return {'role': role, 'connections': connections, 'remote_tools': remote, 'tools': tools, 'saved_logins': saved,
                'model_key': {'host': key['host'], 'hint': str(key.get('hint', ''))[-4:]} if key else None,
                'own_model_key_allowed': policy.get('own_model_key') is not False,
                'memory': None if count is None else {'count': count, 'where': 'Settings, Memory'},
                'acts_without_you': unattended, 'waits': handoff.waits_public(),
                'set_by_organization': sorted(policy)}
