"""Who may do what: the one permission table (roadmap #12). Stdlib only, so every process can import it.

A person acts in an organization with one of four roles. Each row below is one action; the roles listed may do it. Every HTTP route names an action
(accounts/route_actions.py) and every tool the assistant can call names one (TOOL_ACTIONS here); a test fails when a new route or tool forgets. Nothing else in the code
decides by role: it asks `allowed`.

An organization of one (every customer today) has a single owner, who may do everything, so behaviour for existing customers is unchanged.

    owner    everything, including billing and deleting the organization
    admin    members, connections, policy; not billing ownership, not deleting the organization
    member   their own assistant, their own connections, the shared projects they are added to
    viewer   read what is shared with them; cannot run tasks that act, cannot connect anything
"""
from __future__ import annotations

ROLES = ('owner', 'admin', 'member', 'viewer')
_O, _A, _M, _V = 'owner', 'admin', 'member', 'viewer'
ALL_ROLES = frozenset(ROLES)
WORKERS = frozenset({_O, _A, _M})          # everyone who has an assistant of their own
MANAGERS = frozenset({_O, _A})

TABLE: dict[str, frozenset] = {
    # reading one's own account
    'account.read': ALL_ROLES,             # who am I, the app shell, presence, settings pages
    'conversation.read': ALL_ROLES,
    'task.read': ALL_ROLES,                # the timeline, the work picture, receipts of tasks
    'file.read': ALL_ROLES,
    'usage.read': ALL_ROLES,
    'access.read': ALL_ROLES,              # "What your assistant can access"
    'retention.read': ALL_ROLES,
    # working with the assistant
    'conversation.write': WORKERS,         # create, rename, archive, restore a chat; edit a draft plan or form
    'task.run': WORKERS,                   # send a message, launch a plan, a goal, a browser task
    'task.control': WORKERS,               # stop, pause, resume, retry, answer the browser, share a location
    'file.write': WORKERS,                 # upload, delete a file or artifact
    'memory.read': WORKERS,
    'memory.write': WORKERS,               # forget one or all
    'schedule.manage': WORKERS,
    'spending.manage': WORKERS,            # the person's own limits (an organization may lock them: #15)
    'model_key.manage': WORKERS,           # the person's own model key (an organization may forbid it: #15)
    'vault.manage': WORKERS,               # saved logins and cards
    'device.manage': WORKERS,              # the side panel in the person's own Chrome
    'channel.manage': WORKERS,             # Telegram linking
    'safety.manage': WORKERS,              # the safety menu (who may open it is decided on top of this, as before)
    # outside systems
    'connection.read': ALL_ROLES,          # see what is connected
    'connection.create': WORKERS,          # link, reconnect, choose what it may reach
    'connection.remove': WORKERS,
    'connection.use': WORKERS,             # the assistant reading through a connection
    'action.propose': WORKERS,             # the assistant preparing a write for approval
    'action.approve': WORKERS,             # approve, decline, undo; an organization may ask for an admin as well (#15)
    'action.execute': WORKERS,
    # the person's own data
    'data.export': WORKERS,
    'data.delete': WORKERS,                # delete one conversation, file or memory; ask for their own account to be deleted
    # the organization
    'member.read': ALL_ROLES,
    'member.invite': MANAGERS,
    'member.remove': MANAGERS,
    'member.role': MANAGERS,
    'policy.read': ALL_ROLES,
    'policy.change': MANAGERS,
    'organization.export': frozenset({_O}),
    'billing.read': MANAGERS,
    'billing.manage': frozenset({_O}),
    'account.delete': frozenset({_O}),     # delete the whole organization
}

# What each tool the assistant can be given needs (the tool relay asks before a tool runs). Keys are tool names, or a prefix ending in '*' for a family of names.
TOOL_ACTIONS: dict[str, str] = {
    'lumina_browser': 'task.run', 'lumina_browser_step': 'task.run',
    'lumina_task_update': 'task.run',
    'lumina_request_location': 'task.run',
    'lumina_show': 'task.run',
    'lumina_file_deliver': 'file.write',
    'lumina_memory_*': 'memory.write',
    'lumina_mcp_*': 'connection.use',      # the generic remote-MCP tools and every tool of a connected server
    'mcp__*': 'connection.use',
    'lumina_connector_list': 'connection.use', 'lumina_connector_read': 'connection.use', 'lumina_connector_search': 'connection.use',
    'lumina_connector_propose': 'action.propose', 'lumina_connector_workflow': 'action.propose',
    'lumina_ask_customer': 'task.run',
}


class NotPermitted(Exception):
    """The person's role does not include this action. Carries the action only: never a name, an id or content."""
    def __init__(self, action):
        super().__init__(action); self.action = action


def roles_for(action: str) -> frozenset:
    return TABLE.get(action, frozenset())          # an action nobody listed is an action nobody may do


def role_allows(role: str, action: str) -> bool:
    return role in roles_for(action)


def tool_action(name: str):
    """The action a tool needs, or None for a name no row covers."""
    if name in TOOL_ACTIONS:
        return TOOL_ACTIONS[name]
    for key, action in TOOL_ACTIONS.items():
        if key.endswith('*') and isinstance(name, str) and name.startswith(key[:-1]):
            return action
    return None


def member_role(con, account_id: str, actor_id: str):
    """The role this person holds for this account RIGHT NOW (read at call time, never cached), or None when they may not act in it at all.

    Needs what admission always needed (an active account and an active customer membership), plus the organization role. A membership with no organization row is a
    single-person account from before organizations existed in this database: its customer is its owner. A member who was removed has a row that says so, and gets nothing."""
    try:
        row = con.execute("""SELECT o.role,o.status FROM memberships m JOIN accounts a ON a.id=m.account_id
            LEFT JOIN organization_members o ON o.account_id=m.account_id AND o.actor_id=m.actor_id
            WHERE m.account_id=? AND m.actor_id=? AND m.role='customer' AND m.status='active' AND a.status='active'""", (account_id, actor_id)).fetchone()
    except Exception as error:
        if 'no such table' not in str(error) and 'no such column' not in str(error):
            raise
        row = con.execute("""SELECT NULL,NULL FROM memberships m JOIN accounts a ON a.id=m.account_id
            WHERE m.account_id=? AND m.actor_id=? AND m.role='customer' AND m.status='active' AND a.status='active'""", (account_id, actor_id)).fetchone()
    if not row:
        return None
    if row[0] is None:
        return 'owner'
    return row[0] if row[1] == 'active' else None


def organization_of(con, account_id: str) -> str:
    try:
        row = con.execute('SELECT organization_id FROM accounts WHERE id=?', (account_id,)).fetchone()
    except Exception:
        row = None
    return (row[0] if row and row[0] else account_id)


def may(con, account_id: str, actor_id: str, action: str) -> bool:
    """Does this person, in this account, hold a role that includes the action? One database read."""
    role = member_role(con, account_id, actor_id)
    return role is not None and role_allows(role, action)
