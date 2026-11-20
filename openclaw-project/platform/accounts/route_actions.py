"""Every HTTP route names the action it needs (roadmap #12). The account middleware asks `security.allowed` with it before the view runs.

A value is an action from agentai_platform/permissions.py, or {method: action} when reading and changing need different ones, or one of:
    PUBLIC     no signed-in customer is needed (sign-in pages, health, the public config)
    OPERATOR   an internal operator route: it has its own check (a verified operator with a time-limited grant: services.operator_scope)
    OWN_PROOF  the route proves the caller itself (a provider webhook's signature, a side-panel or download ticket) and then acts as that account's customer

tests/…/test_permissions fails when a route in urls.py has no row here, or a row here names a route that no longer exists."""
PUBLIC, OPERATOR, OWN_PROOF = 'public', 'operator', 'own_proof'
R, W = 'GET', 'POST'

ROUTES = {
    # -- no customer needed ------------------------------------------------------------------------------------------------------------------
    '': PUBLIC, 'healthz': PUBLIC, 'readyz': PUBLIC, 'account/': PUBLIC, 'account/<str:page>/': PUBLIC, 'account/ui': PUBLIC, 'account/ui/': PUBLIC,
    'auth/login': PUBLIC, 'auth/logout': PUBLIC, 'auth/recovery': PUBLIC, 'auth/reset': PUBLIC, 'auth/activate': PUBLIC, 'auth/signup': PUBLIC, 'auth/signup/verify': PUBLIC,
    'auth/mfa': PUBLIC, 'auth/revoke-sessions': PUBLIC, 'v1/signup/config': PUBLIC, 'v1/csrf': PUBLIC, 'app/': PUBLIC, 'app/<path:path>': PUBLIC,
    'v1/me': PUBLIC, 'v1/app': PUBLIC,                       # answer "not signed in" themselves; a signed-in customer of any role may read them
    # -- operators ---------------------------------------------------------------------------------------------------------------------------
    'internal/accounts/<str:account>/invite': OPERATOR, 'internal/accounts/<str:account>/revoke': OPERATOR, 'internal/accounts/<str:account>/suspend': OPERATOR,
    'internal/accounts/<str:account>/audit': OPERATOR, 'internal/accounts/<str:account>/impersonate': OPERATOR, 'internal/accounts/<str:account>/export': OPERATOR,
    'internal/accounts/<str:account>/deployment/operations': OPERATOR, 'internal/accounts/<str:account>/deployment/operations/<str:operation_id>/retry': OPERATOR,
    # -- routes that prove the caller themselves -------------------------------------------------------------------------------------------------
    'v1/billing/webhook': OWN_PROOF, 'v1/telegram/webhook': OWN_PROOF,
    'v1/panel/session': OWN_PROOF, 'v1/panel/state': OWN_PROOF, 'v1/panel/events': OWN_PROOF, 'v1/panel/history': OWN_PROOF, 'v1/panel/send': OWN_PROOF, 'v1/panel/stop': OWN_PROOF,
    'v1/apps/player': OWN_PROOF, 'v1/artifacts/<str:artifact_id>/versions/<str:version>/download': OWN_PROOF, 'v1/exports/<str:export_id>/download': OWN_PROOF,
    # -- the customer's pages ----------------------------------------------------------------------------------------------------------------
    'account/chat/': 'account.read', 'account/requests/': 'task.read', 'account/usage/': 'usage.read', 'account/connections/': 'connection.read', 'account/billing/': 'billing.read',
    'v1/assistant/presence': 'account.read', 'v1/genui/registry': 'account.read', 'v1/estimates/<str:kind>': 'usage.read', 'v1/costs': 'usage.read',
    # -- projects, chats, files --------------------------------------------------------------------------------------------------------------
    'v1/projects': {R: 'conversation.read', W: 'conversation.write'}, 'v1/projects/<str:project_id>': {R: 'conversation.read', W: 'conversation.write'},
    'v1/projects/<str:project_id>/files': {R: 'file.read', W: 'file.write'}, 'v1/projects/<str:project_id>/files/<str:file_id>/preview': 'file.read',
    'v1/projects/<str:project_id>/bundle': 'file.read', 'v1/files': 'file.read', 'v1/files/bundle': 'file.read', 'v1/export/table': 'file.read',
    'v1/conversations/<str:conversation_id>/export': 'file.read', 'v1/artifacts/<str:artifact_id>/delete': 'file.write',
    'v1/catalogue': 'file.read', 'v1/catalogue/place': 'file.write', 'v1/folders': 'file.write', 'v1/folders/<str:folder_id>': 'file.write', 'v1/uploads/<str:file_id>/delete': 'file.write',
    'v1/artifacts/<str:artifact_id>/versions/<str:version>/preview': 'file.read', 'v1/artifacts/<str:artifact_id>/versions/<str:version>/app': 'file.read',
    'v1/artifacts/<str:artifact_id>/versions/<str:version>/ticket': 'file.read', 'v1/media/<str:image_id>': 'file.read', 'v1/genui/artifacts/<str:artifact_id>/asset': 'file.read',
    'v1/conversations': {R: 'conversation.read', W: 'conversation.write'}, 'v1/conversations/<str:conversation_id>': {R: 'conversation.read', W: 'conversation.write'},
    'v1/conversations/<str:conversation_id>/messages': 'conversation.read', 'v1/conversations/<str:conversation_id>/blocks': 'conversation.read',
    'v1/conversations/<str:conversation_id>/archive': 'conversation.write', 'v1/conversations/<str:conversation_id>/restore': 'conversation.write',
    'v1/conversations/<str:conversation_id>/rename': 'conversation.write', 'v1/conversations/<str:conversation_id>/delete': 'data.delete',
    # -- running and steering work -----------------------------------------------------------------------------------------------------------
    'v1/conversations/<str:conversation_id>/send': 'task.run', 'v1/conversations/<str:conversation_id>/goal': 'task.run',
    'v1/blocks/<str:block_id>/state': 'conversation.write', 'v1/blocks/<str:block_id>/submit': 'task.run', 'v1/blocks/<str:block_id>/launch': 'task.run',
    'v1/blocks/<str:block_id>/live': 'task.read', 'v1/blocks/<str:block_id>/phase': 'task.control', 'v1/blocks/<str:block_id>/stop': 'task.control',
    'v1/blocks/<str:block_id>/replan': 'task.run', 'v1/blocks/<str:block_id>/proposal': 'task.control', 'v1/blocks/<str:block_id>/auto-replan': 'task.control',
    'v1/genui/artifacts/<str:artifact_id>/diagnostics': 'conversation.write', 'v1/genui/artifacts/<str:artifact_id>/state': {R: 'conversation.read', W: 'conversation.write'},
    'v1/genui/artifacts/<str:artifact_id>/events': 'task.run', 'v1/genui/artifacts/<str:artifact_id>/update': 'task.run',
    'v1/requests': 'task.read', 'v1/requests/<str:request_id>': 'task.read', 'v1/requests/<str:request_id>/cancel': 'task.control',
    'v1/requests/<str:request_id>/pause': 'task.control', 'v1/requests/<str:request_id>/resume': 'task.control', 'v1/requests/<str:request_id>/retry': 'task.run',
    'v1/tasks': 'task.read', 'v1/tasks/<str:request_id>': 'task.read', 'v1/tasks/<str:request_id>/cancel': 'task.control',
    'v1/tasks/<str:request_id>/events': 'task.read', 'v1/tasks/<str:request_id>/stream': 'task.read',
    'v1/work': 'task.read', 'v1/work/ticket': 'task.read', 'v1/work/<str:request_id>': 'task.read',
    'v1/objectives': 'task.read', 'v1/objectives/<str:objective_id>': {R: 'task.read', W: 'task.control'}, 'v1/objectives/<str:objective_id>/cancel': 'task.control',
    'v1/operations': 'task.read', 'v1/operations/<str:operation_id>': 'task.read',
    'v1/browse': {R: 'task.read', W: 'task.run'}, 'v1/browse/<str:request_id>': 'task.read', 'v1/browse/<str:request_id>/live': 'task.read', 'v1/browse/<str:request_id>/shot/<str:name>': 'task.read',
    'v1/browse/<str:request_id>/control': 'task.control', 'v1/browse/<str:request_id>/release': 'task.control', 'v1/browse/<str:request_id>/pause': 'task.control',
    'v1/browse/<str:request_id>/resume': 'task.control', 'v1/browse/<str:request_id>/answer': 'task.control',
    'v1/location': 'task.read', 'v1/location/<str:location_id>': 'task.control',
    # -- the person's own settings -----------------------------------------------------------------------------------------------------------
    'v1/spending-limits': {R: 'usage.read', W: 'spending.manage'},
    'v1/saved': 'memory.read', 'v1/saved/<str:field>/forget': 'memory.write',
    'v1/vault': 'vault.manage', 'v1/vault/add': 'vault.manage', 'v1/vault/<str:item_id>/delete': 'vault.manage',
    'v1/devices': 'device.manage', 'v1/devices/pair': 'device.manage', 'v1/devices/use': 'device.manage', 'v1/devices/<str:device_id>/revoke': 'device.manage',
    'v1/longterm-memory': 'memory.read', 'v1/longterm-memory/forget-all': 'memory.write', 'v1/longterm-memory/<str:entry_id>/forget': 'memory.write',
    'v1/model-key': {R: 'access.read', W: 'model_key.manage'}, 'v1/model-key/save': 'model_key.manage', 'v1/model-key/remove': 'model_key.manage', 'v1/model-key/select': 'model_key.manage',
    'v1/safety': 'safety.manage', 'v1/safety/change': 'safety.manage', 'v1/safety/access': 'safety.manage', 'v1/safety/access/change': 'safety.manage',
    'v1/account/telegram': 'channel.manage', 'v1/account/telegram/link': 'channel.manage', 'v1/account/telegram/unlink': 'channel.manage',
    'v1/account/billing': 'billing.read', 'v1/account/billing/checkout': 'billing.manage', 'v1/account/billing/portal': 'billing.manage',
    # -- outside systems ---------------------------------------------------------------------------------------------------------------------
    'v1/account/connections': 'connection.read', 'v1/account/connections/link': 'connection.create', 'v1/account/connections/callback': 'connection.create',
    'v1/account/connections/disconnect': 'connection.remove', 'v1/account/drafts': 'connection.read',
    'v1/account/mcp': {R: 'connection.read', W: 'connection.create'}, 'v1/account/mcp/callback': 'connection.create',
    'v1/account/mcp/<str:connection_id>/<str:action>': 'connection.create', 'v1/account/mcp-approvals/<str:call_id>': 'action.approve',
    'v1/hub': 'connection.read', 'v1/hub/pulse': 'connection.read', 'v1/hub/ask': 'task.run', 'v1/assistant/ask': 'task.run', 'v1/search': 'file.read', 'v1/hub/link': 'connection.create', 'v1/hub/link/callback': PUBLIC, 'v1/hub/link/finish': 'connection.create', 'v1/hub/mail/threads': 'connection.read', 'v1/hub/mail/labels': 'connection.read', 'v1/hub/mail/thread': 'connection.read',
    'v1/hub/mail/message': 'connection.read', 'v1/hub/mail/search-older': 'connection.read', 'v1/hub/events': 'connection.read', 'v1/hub/event': 'connection.read',
    'v1/hub/events/search': 'connection.read', 'v1/hub/refresh': 'connection.use', 'v1/hub/settings': 'connection.use', 'v1/hub/calendars': 'connection.use',
    'v1/controls': 'access.read',
    'v1/integrations': 'connection.read', 'v1/integrations/<str:connection_id>': 'connection.read', 'v1/integrations/<str:connection_id>/resources': 'connection.read',
    'v1/integrations/<str:connection_id>/grants': 'connection.create', 'v1/integrations/<str:connection_id>/remove': 'connection.remove',
    'v1/integrations/<str:connection_id>/auto-approve': 'action.approve', 'v1/integrations/synthetic/connect': 'connection.create',
    'v1/actions': 'task.read', 'v1/actions/<str:action_id>': 'task.read', 'v1/actions/<str:action_id>/approve': 'action.approve', 'v1/actions/<str:action_id>/decline': 'action.approve',
    'v1/actions/<str:action_id>/undo': 'action.approve', 'v1/actions/<str:action_id>/compensate': 'action.approve',
    'v1/workflows/<str:workflow_id>': 'task.read', 'v1/workflows/<str:workflow_id>/approve': 'action.approve', 'v1/workflows/<str:workflow_id>/decline': 'action.approve',
    'v1/handoffs': 'task.read', 'v1/handoffs/<str:handoff_id>/answer': 'task.control',
    # -- the organization --------------------------------------------------------------------------------------------------------------------
    'v1/organization': 'member.read', 'v1/organization/members/<str:actor_id>/role': 'member.role', 'v1/organization/members/<str:actor_id>/remove': 'member.remove',
    'v1/organization/policy': {R: 'policy.read', W: 'policy.change'},
    # -- data lifecycle ----------------------------------------------------------------------------------------------------------------------
    'v1/retention': 'retention.read',
    'v1/exports': {R: 'data.export', W: 'data.export'}, 'v1/exports/<str:export_id>': 'data.export', 'v1/exports/<str:export_id>/ticket': 'data.export',
    'v1/account/offboarding': {R: 'account.read', W: 'data.delete'}, 'v1/account/offboarding/<str:action>': 'data.delete',
    # -- the customer's knowledge, commitments and memory correction (roadmap Phase 4); drafts and attachments (Phase 5) ----------------------------------
    'v1/knowledge': 'file.read', 'v1/knowledge/sources': 'file.write', 'v1/knowledge/sources/<str:source_id>/remove': 'file.write',
    'v1/knowledge/sources/<str:source_id>/reindex': 'file.write', 'v1/knowledge/sources/<str:source_id>/share': 'file.write',
    'v1/knowledge/sources/<str:source_id>/document': 'file.read', 'v1/knowledge/search': 'file.read', 'v1/knowledge/passages/<str:passage_id>': 'file.read',
    'v1/knowledge/compare': 'file.read',
    'v1/organization/groups': {R: 'member.read', W: 'group.manage'}, 'v1/organization/groups/<str:group_id>/members': 'group.manage',
    'v1/organization/groups/<str:group_id>/delete': 'group.manage',
    'v1/commitments': {R: 'task.read', W: 'task.run'}, 'v1/commitments/<str:item_id>': 'task.run',
    'v1/longterm-memory/<str:entry_id>/correct': 'memory.write', 'v1/longterm-memory/<str:entry_id>/history': 'memory.read',
    'v1/hub/drafts': {R: 'connection.read', W: 'connection.use'}, 'v1/hub/drafts/<str:draft_id>/discard': 'connection.use', 'v1/hub/drafts/<str:draft_id>/compose': 'connection.read',
    'v1/hub/mail/attachment': 'connection.use',
    # Phase 6: the customer's own change in the dashboard is their approval of it; reading free time and clashes is reading.
    'v1/hub/events/create': 'action.approve', 'v1/hub/events/cancel': 'action.approve', 'v1/hub/events/change': 'action.approve', 'v1/hub/events/respond': 'action.approve', 'v1/hub/actions/<str:action_id>/undo': 'action.approve',
    'v1/hub/actions/<str:action_id>/stop': 'action.approve', 'v1/hub/free': 'connection.read', 'v1/hub/conflicts': 'connection.read',
    'v1/hub/availability': {R: 'connection.read', W: 'connection.use'},
    # -- kept disabled on purpose (they answer "disabled" to anyone signed in) ---------------------------------------------------------------------
    **{f'v1/{kind}{tail}': 'account.read' for kind in ('streams', 'memory', 'schedules') for tail in ('', '/<str:object_id>', '/<str:object_id>/<str:action>')},
}


def action_for(route: str, method: str):
    """-> the action (or PUBLIC / OPERATOR / OWN_PROOF) this request needs, or None when the route has no row (the middleware then refuses everyone but an owner)."""
    entry = ROUTES.get(route)
    if isinstance(entry, dict):
        return entry.get('GET' if method in ('GET', 'HEAD') else 'POST')
    return entry
