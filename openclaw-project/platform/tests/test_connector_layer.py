"""The connector layer, proven against the synthetic connector: resource grants (#13), custody, refresh (#16), revocation (#17), the contract and its six error kinds (#22),
paging (#23), freshness (#24)."""
import json
import unittest

from agentai_platform import connector_kit, synthetic_connector
from agentai_platform.connector_kit import Caps, ConnectorFault, Declaration, McpAdapter, Page, ProviderError, Registry, WriteKind, paginate
from agentai_platform.connectors import ConnectorError, WriteDisabled
from agentai_platform.security import NotFound
from agentai_platform.synthetic_connector import SyntheticBench

from tests.connector_fixture import ConnectorBase


def kind_of(test, fn):
    with test.assertRaises(ConnectorFault) as caught:
        fn()
    return caught.exception.kind


class Grants(ConnectorBase):
    def test_a_new_connection_reaches_nothing_until_its_customer_chooses(self):
        connection = self.connect(grants=())
        self.bench.seed('a', 'inbox', 3)
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox')), 'not_found')
        self.assertEqual(self.client.search(self.a, connection, 'note')[0], [])
        self.assertEqual([r['id'] for r in self.client.resources(self.a, connection)], ['inbox', 'projects', 'archive'])      # the picker works before anything is granted
        self.assertIn('nothing yet', self.connectors.describe_scope(()))

    def test_a_connection_limited_to_two_folders_cannot_list_read_or_search_a_third(self):
        connection = self.connect(grants=(('folder', 'inbox', 'read'), ('folder', 'projects', 'read')))
        for folder in ('inbox', 'projects', 'archive'):
            self.bench.seed('a', folder, 2, prefix=folder + ' secret')
        self.assertEqual(len(self.client.list(self.a, connection, 'folder', 'inbox')[0]), 2)
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'archive')), 'not_found')       # at the boundary: list
        self.assertEqual(kind_of(self, lambda: self.client.read(self.a, connection, 'note', 'archive-0000')), 'not_found')    # read
        found, _ = self.client.search(self.a, connection, 'secret')
        self.assertEqual({r['container'][1] for r in found}, {'inbox', 'projects'})                                             # search
        from agentai_platform.connector_tools import ConnectorTools                                                           # and through the assistant's tool
        tools = ConnectorTools(self.store, self.connectors, self.client, self.actions, self.workflows, clock=lambda: self.now, enabled=lambda a: True)
        text, error = tools.call('a', {'connection': connection, 'resource_kind': 'folder', 'resource_id': 'archive'}, name='lumina_connector_list', request_id='req-a')
        self.assertTrue(error); self.assertNotIn('archive secret', text)
        text, error = tools.call('a', {'connection': connection, 'query': 'secret'}, name='lumina_connector_search', request_id='req-a')
        self.assertFalse(error); self.assertNotIn('archive secret', text); self.assertIn('inbox secret', text)
        text, error = tools.call('a', {'connection': connection, 'kind': 'note', 'id': 'archive-0000'}, name='lumina_connector_read', request_id='req-a')
        self.assertTrue(error); self.assertNotIn('archive secret', text)

    def test_everything_is_an_explicit_choice_and_the_sentence_comes_from_the_same_rows(self):
        connection = self.connect(grants=(('folder', '*', 'read'),))
        self.bench.seed('a', 'archive', 1)
        self.assertEqual(len(self.client.list(self.a, connection, 'folder', 'archive')[0]), 1)
        with self.store.connect() as con:
            self.assertEqual(self.connectors.describe_scope(self.connectors.scope(con, 'a', connection)), 'Can read: every folder. Cannot change anything.')
        self.connectors.set_grants(self.a, connection, [{'kind': 'folder', 'id': 'inbox', 'access': 'write'}, {'kind': 'folder', 'id': 'projects', 'access': 'read'}])
        with self.store.connect() as con:
            self.assertEqual(self.connectors.describe_scope(self.connectors.scope(con, 'a', connection)),
                             'Can read: 2 folders. Can change (each change still needs your approval): 1 folder.')

    def test_authorize_read_and_write_carry_the_scope_and_refuse_what_is_not_granted(self):
        connection = self.connect(grants=(('folder', 'inbox', 'read'),))
        grant = self.connectors.authorize_read(self.a, 'synthetic', 'inbox', resource_kind='folder')
        self.assertEqual((grant.connection_id, grant.scope), (connection, (('folder', 'inbox', 'read'),)))
        with self.assertRaises(NotFound):
            self.connectors.authorize_read(self.a, 'synthetic', 'archive', resource_kind='folder')
        with self.assertRaises(NotFound):
            self.connectors.authorize_write(self.a, 'synthetic', 'inbox', resource_kind='folder')                     # read is not write
        with self.assertRaises(NotFound):
            self.connectors.authorize_read(self.b, 'synthetic', 'inbox', resource_kind='folder')                      # another account has no such connection
        self.assertNotIn(grant.secret_ref, repr(grant))

    def test_another_account_cannot_see_use_or_change_a_connection(self):
        connection = self.connect()
        self.bench.seed('a', 'inbox', 1)
        self.assertEqual(kind_of(self, lambda: self.client.list(self.b, connection, 'folder', 'inbox')), 'not_found')
        with self.assertRaises(NotFound):
            self.connectors.set_grants(self.b, connection, [])
        with self.assertRaises(NotFound):
            self.connectors.revoke(self.b, connection)
        with self.assertRaises(ValueError):
            self.connectors.set_grants(self.a, connection, [{'kind': 'planet', 'id': 'mars'}])

    def test_a_viewer_and_a_forbidden_service_are_refused(self):
        connection = self.connect(self.b)
        self.orgs.add_member(self.a, 'b', 'actor-b', 'viewer')
        self.assertEqual(kind_of(self, lambda: self.client.list(self.b, connection, 'folder', 'inbox')), 'refused')
        self.orgs.set_role(self.a, 'actor-b', 'member')
        self.orgs.set_policy(self.a, 'connectors_allowed', ['calendar'])
        self.assertEqual(kind_of(self, lambda: self.client.list(self.b, connection, 'folder', 'inbox')), 'refused')
        with self.assertRaises(ConnectorError):
            self.connect(self.b)


class Custody(ConnectorBase):
    def test_tokens_are_sealed_bound_to_their_account_and_never_in_a_row_a_view_reads(self):
        tokens = SyntheticBench.tokens('a')
        connection = self.connect(tokens=tokens)
        row = self.rows('SELECT * FROM connector_connections WHERE id=?', (connection,))[0]
        dump = json.dumps(self.rows('SELECT * FROM connector_connections') + self.connectors.overview(self.a) + self.connectors.grants(self.a, connection))
        self.assertNotIn(tokens['access_token'], dump); self.assertNotIn(tokens['refresh_token'], dump)
        sealed = self.rows('SELECT ciphertext FROM connector_secrets WHERE ref=?', (row['secret_ref'],))[0]['ciphertext']
        self.assertNotIn(tokens['access_token'].encode(), bytes(sealed))
        self.assertEqual(json.loads(self.custody.get('a', row['secret_ref'])), tokens)
        with self.assertRaises(NotFound):
            self.custody.get('b', row['secret_ref'])                                                    # another account's reference opens nothing
        with self.store.connect() as con:
            con.execute("UPDATE connector_secrets SET account_id='b' WHERE ref=?", (row['secret_ref'],))
        with self.assertRaises(NotFound):
            self.custody.get('b', row['secret_ref'])                                                    # a row copied to another account does not open either


class Refresh(ConnectorBase):
    def test_a_token_is_renewed_before_it_ends_many_times_over(self):
        connection = self.connect(expires_in=600)
        self.bench.seed('a', 'inbox', 1)
        seen = set()
        for cycle in range(40):                                                                         # a soak: forty refresh cycles of a short-lived token
            self.now += 3300 if cycle else 60
            report = self.refresher.tick()
            self.assertEqual(report['refreshed'], 1, cycle)
            ref = self.rows('SELECT secret_ref FROM connector_connections WHERE id=?', (connection,))[0]['secret_ref']
            seen.add(json.loads(self.custody.get('a', ref))['access_token'])
            self.assertEqual(len(self.client.list(self.a, connection, 'folder', 'inbox')[0]), 1)       # and the connection keeps working
        self.assertEqual(len(seen), 40)
        self.assertEqual(self.custody.count('a'), 1)                                                    # old tokens do not pile up
        self.assertEqual(self.refresher.tick()['refreshed'], 0)                                         # nothing due: nothing done

    def test_two_workers_never_refresh_one_connection_at_once(self):
        connection = self.connect(expires_in=60)
        row = self.refresher.due()[0]
        calls = []
        def slow(tokens):
            calls.append(1)
            self.assertEqual(self.refresher.refresh(row), 'skipped')                                    # the second worker, while the first is still asking the provider
            return SyntheticBench.refresher(tokens)
        self.refresher.refreshers['synthetic'] = slow
        self.assertEqual(self.refresher.refresh(row), 'refreshed')
        self.assertEqual(len(calls), 1)

    def test_an_invalid_refresh_token_ends_in_needs_you_once_not_in_a_loop(self):
        connection = self.connect(expires_in=60, tokens={**SyntheticBench.tokens('a'), 'refresh_token': 'refresh-invalid'})
        for _ in range(5):
            self.refresher.tick(); self.now += 600
        row = self.rows('SELECT state,needs_reason,refresh_failures FROM connector_connections WHERE id=?', (connection,))[0]
        self.assertEqual((row['state'], row['needs_reason']), ('reconnect_required', 'reconnect'))
        self.assertEqual(self.notices, [('a', connection, 'reconnect')])                                # told once
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox')), 'needs_customer')

    def test_a_temporary_failure_backs_off_and_a_revoked_token_goes_through_revocation(self):
        busy = self.connect(expires_in=60, tokens={**SyntheticBench.tokens('a'), 'refresh_token': 'refresh-busy'})
        self.assertEqual(self.refresher.tick()['temporary'], 1)
        self.assertEqual(self.refresher.tick()['temporary'], 0)                                         # not asked again at once
        self.now += 61
        self.assertEqual(self.refresher.tick()['temporary'], 1)
        self.assertEqual(self.rows('SELECT state FROM connector_connections WHERE id=?', (busy,))[0]['state'], 'connected')
        gone = self.connect(self.b, expires_in=60, tokens={**SyntheticBench.tokens('b'), 'refresh_token': 'refresh-revoked'})
        self.assertEqual(self.refresher.tick()['revoked'], 1)
        self.assertEqual(self.rows('SELECT state,secret_ref FROM connector_connections WHERE id=?', (gone,))[0], {'state': 'revoked', 'secret_ref': None})
        self.assertEqual(self.rows('SELECT source FROM connector_revocations WHERE connection_id=?', (gone,))[0]['source'], 'provider')
        self.assertEqual(self.custody.count('b'), 0)


class Revocation(ConnectorBase):
    def test_removing_a_connection_stops_everything_and_says_what_was_stopped(self):
        connection = self.connect()
        self.bench.seed('a', 'inbox', 2)
        self.client.list(self.a, connection, 'folder', 'inbox')
        waiting = self.actions.propose(self.a, connection, 'note.create', {'folder': 'inbox', 'title': 'T', 'body': 'B'}, request_id='req-a')
        self.actions.set_auto(self.a, connection, 'note.update', True)
        with self.store.connect() as con:
            con.execute('''INSERT INTO schedules(account_id,project_id,id,name,timezone,hour_local,minute_local,timeout_seconds,task_budget_microusd,state,created_epoch,needs_connection_id)
                VALUES ('a','p-a','s1','Daily','UTC',8,0,300,0,'active',1,?)''', (connection,))
        receipt = self.connectors.revoke(self.a, connection)
        self.assertEqual(receipt['source'], 'customer')
        self.assertEqual({k: v for k, v in receipt['stopped'].items() if v}, {'grants_removed': 1, 'freshness_removed': 1, 'automatic_approvals_removed': 1, 'actions_ended': 1,
                                                                             'handoffs_ended': 1, 'schedules_paused': 1})
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox')), 'refused')      # from that moment, at the next call
        self.assertEqual(self.actions.get(self.a, waiting['id'])['state'], 'expired')
        self.assertEqual(self.actions.execute('a', waiting['id']), 'expired')                                             # and it can never run
        self.assertEqual(self.rows("SELECT state,pause_reason FROM schedules WHERE id='s1'")[0], {'state': 'paused', 'pause_reason': 'Its connection was removed.'})
        self.assertEqual(self.custody.count('a'), 0)                                                                      # the tokens left custody
        self.assertEqual(self.connectors.revoke(self.a, connection)['id'], receipt['id'])                                 # asking again changes nothing
        self.assertEqual(len(self.connectors.revocations(self.a)), 1)
        self.assertEqual(self.connectors.revocations(self.b), [])

    def test_the_provider_refusing_the_token_marks_the_connection_at_the_next_call(self):
        connection = self.connect()
        self.bench.fault('a', 'list', 'revoked')
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox')), 'needs_customer')
        self.assertEqual(self.rows('SELECT state FROM connector_connections WHERE id=?', (connection,))[0]['state'], 'reconnect_required')
        self.assertEqual(self.notices, [('a', connection, 'reconnect')])

    def test_a_running_action_stops_at_its_next_call_when_the_connection_is_removed(self):
        connection = self.connect()
        action = self.actions.propose(self.a, connection, 'note.create', {'folder': 'inbox', 'title': 'T', 'body': 'B'}, request_id='req-a')
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.connectors.revoke_by_system('a', connection, 'policy')
        self.assertIn(self.actions.execute('a', action['id']), ('expired', 'failed'))
        self.assertEqual(self.bench.rows('a'), [])                                                                        # nothing was written


class Contract(ConnectorBase):
    def test_every_provider_error_becomes_exactly_one_of_six_kinds(self):
        d = synthetic_connector.DECLARATION
        cases = [(ProviderError(429, retry_after=7), 'retry_later'), (ProviderError(503), 'retry_later'), (ProviderError(0), 'retry_later'), (ProviderError(401), 'needs_customer'),
                 (ProviderError(401, 'token_revoked'), 'needs_customer'), (ProviderError(403), 'refused'), (ProviderError(404), 'not_found'), (ProviderError(409), 'conflict'),
                 (ProviderError(412, 'version_mismatch'), 'conflict'), (ProviderError(400), 'invalid'), (ProviderError(418), 'invalid'), (ProviderError(200, 'quota'), 'retry_later')]
        for error, kind in cases:
            self.assertEqual(d.fault(error).kind, kind, (error.status, error.code))
        self.assertIsNotNone(d.fault(ProviderError(429, retry_after=7)).retry_at)
        self.assertEqual(set(connector_kit.FAULT_KINDS), set(connector_kit.FAULT_WORDS))
        with self.assertRaises(ValueError):
            ConnectorFault('exploded')

    def test_a_declaration_is_checked_when_it_is_registered(self):
        base = dict(provider='x', label='X', implementation='first_party', reason='because')
        registry = Registry()
        for bad in (dict(base, write_kinds=(WriteKind('a.do', 'Do'),)),                                             # neither an inverse nor a reason it cannot be undone
                    dict(base, write_kinds=(WriteKind('a.do', 'Do', undo='a.undo'),)),                              # an inverse that is not a write kind
                    dict(base, write_kinds=(WriteKind('a.do', 'Do', irreversible_reason='gone', compensations=('a.fix',)),)),
                    dict(base, reason=''), dict(base, paging='scroll'), dict(base, error_map={500: 'panic'})):
            with self.assertRaises(ValueError):
                registry.register(Declaration(**bad), lambda: None)
        registry.register(Declaration(**base, write_kinds=(WriteKind('a.do', 'Do', irreversible_reason='It is sent.'),)), lambda: None)
        with self.assertRaises(ValueError):
            registry.register(Declaration(**base), lambda: None)                                                    # twice

    def test_a_busy_provider_is_waited_for_once_together_and_then_left_to_the_caller(self):
        connection = self.connect()
        self.bench.fault('a', 'list', 'rate_limit')
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox')), 'retry_later')
        self.client.list(self.a, connection, 'folder', 'inbox')                                                    # the next call waits for the time the provider named, then asks
        self.assertEqual(len(self.slept), 1)
        self.assertTrue(0 < self.slept[0] <= 60)

    def test_the_connection_is_read_from_the_database_at_every_call(self):
        connection = self.connect()
        self.client.list(self.a, connection, 'folder', 'inbox')
        with self.store.connect() as con:
            con.execute("UPDATE connector_connections SET state='revoked' WHERE id=?", (connection,))
        self.assertEqual(kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox')), 'refused')

    def test_an_mcp_wrapper_sits_behind_the_same_contract(self):
        calls = []
        def call(account, connection, tool, arguments):
            calls.append((account, connection, tool))
            if tool == 'boards':
                return [{'id': 'b1', 'name': 'Board one'}]
            if tool == 'cards':
                return {'cards': [{'id': 'c1', 'board': arguments['container'][1], 'title': 'Card', 'rev': 4}], 'next': None}
            raise TimeoutError
        adapter = McpAdapter(call, {'resources': ('boards', lambda r: [{'kind': 'board', 'id': b['id'], 'name': b['name']} for b in r]),
                                    'list': ('cards', lambda r: Page([connector_kit.record('card', c['id'], container=('board', c['board']), version=c['rev'], title=c['title']) for c in r['cards']], r['next'])),
                                    'write': {'card.move': ('move', lambda r: r)}, 'container_of': lambda kind, payload: ('board', payload['board']), 'target_of': lambda kind, payload: None})
        registry = Registry()
        registry.register(Declaration(provider='boards', label='Boards', auth='mcp', resource_kinds=('board',), record_kinds=('card',), read_operations=('list',),
                                      write_kinds=(WriteKind('card.move', 'Move a card', irreversible_reason='Not registered yet.'),), implementation='mcp',
                                      reason='The provider runs an official remote MCP server that offers what the contract needs.'), lambda: adapter)
        from agentai_platform.connectors import ConnectorService
        connectors = ConnectorService(self.store, custody=self.custody, registry=registry, clock=lambda: self.now)
        client = connector_kit.ConnectorClient(self.store, connectors, registry, clock=lambda: self.now)
        connection = connectors.connect_declared(self.a, 'boards', 'a@boards', mcp_connection_id='m' * 32)
        self.assertEqual(client.resources(self.a, connection), [{'kind': 'board', 'id': 'b1', 'name': 'Board one'}])
        connectors.set_grants(self.a, connection, [{'kind': 'board', 'id': 'b1', 'access': 'write'}])
        items, page = client.list(self.a, connection, 'board', 'b1')
        self.assertEqual((items[0]['id'], items[0]['version'], page.complete), ('c1', '4', True))
        self.assertEqual(calls[-1], ('a', 'm' * 32, 'cards'))
        with self.assertRaises(connector_kit.Unanswered):
            client.write(self.a, connection, 'card.move', {'board': 'b1'}, idempotency_key='k')                 # a timeout is "no answer", never "failed"


class Paging(ConnectorBase):
    def pages(self, total, per_page, style='cursor'):
        def fetch(position, limit):
            start = position or 0
            items = [{'n': n} for n in range(start, min(total, start + min(per_page, limit)))]
            more = start + len(items) < total
            return Page(items, next=(start + len(items)) if more else None, total=total)
        return fetch

    def test_one_helper_for_cursor_page_token_and_offset_with_a_continuation(self):
        for style in ('cursor', 'page_token', 'offset'):
            got = paginate(self.pages(45, 10, style), style=style, caps=Caps(pages=3, items=500))
            self.assertEqual((got.count, got.complete, got.total_estimate, got.stopped_by), (30, False, 45, 'pages'), style)
            rest = paginate(self.pages(45, 10, style), style=style, caps=Caps(pages=3, items=500), continuation=got.continuation)
            self.assertEqual((rest.count, rest.complete, rest.continuation), (15, True, None), style)
            self.assertEqual([i['n'] for i in got.items + rest.items], list(range(45)), style)

    def test_every_cap_stops_it_and_says_which(self):
        self.assertEqual(paginate(self.pages(100, 10), caps=Caps(items=25)).stopped_by, 'items')
        self.assertEqual(paginate(self.pages(100, 10), caps=Caps(items=25)).count, 25)
        self.assertEqual(paginate(self.pages(100, 10), caps=Caps(bytes=60)).stopped_by, 'bytes')
        ticks = iter(range(0, 1000, 6))
        self.assertEqual(paginate(self.pages(100, 10), caps=Caps(seconds=10), clock=lambda: next(ticks)).stopped_by, 'seconds')
        with self.assertRaises(ConnectorFault):
            paginate(self.pages(10, 5), continuation='not a handle')
        with self.assertRaises(ConnectorFault):
            paginate(self.pages(10, 5), style='offset', continuation=json.dumps({'s': 'cursor', 't': 5}))            # a handle of another style

    def test_a_partial_result_is_always_said_to_be_partial(self):
        partial = paginate(self.pages(5000, 50), caps=Caps(pages=10, items=500))
        self.assertIn('PARTIAL RESULT: the first 500 of about 5000', partial.words())
        self.assertIn('Ask to continue', partial.words())
        self.assertFalse(partial.public()['complete'])
        whole = paginate(self.pages(7, 50))
        self.assertEqual(whole.words(), 'All 7 items are shown: this is complete.')
        self.assertNotIn('complete', partial.words().lower().replace('do not present this as everything', ''))

    def test_the_assistants_tool_states_a_partial_result_in_words_and_can_continue(self):
        from agentai_platform.connector_tools import ConnectorTools
        connection = self.connect()
        self.bench.seed('a', 'inbox', 70)
        tools = ConnectorTools(self.store, self.connectors, self.client, self.actions, self.workflows, clock=lambda: self.now, enabled=lambda a: True)
        text, error = tools.call('a', {'connection': connection, 'resource_kind': 'folder', 'resource_id': 'inbox'}, name='lumina_connector_list', request_id='req-a')
        first = json.loads(text)
        self.assertFalse(error)
        self.assertEqual((first['count'], first['complete'], first['total_estimate']), (50, False, 70))
        self.assertIn('PARTIAL RESULT: the first 50 of about 70', first['result'])
        text, _ = tools.call('a', {'connection': connection, 'resource_kind': 'folder', 'resource_id': 'inbox', 'continuation': first['continuation']}, name='lumina_connector_list', request_id='req-a')
        rest = json.loads(text)
        self.assertEqual((rest['count'], rest['complete']), (20, True))
        self.assertIn('this is complete', rest['result'])


class FreshnessChecks(ConnectorBase):
    def test_each_resource_keeps_when_it_was_read_and_read_completely(self):
        connection = self.connect(grants=(('folder', 'inbox', 'read'), ('folder', 'projects', 'read')))
        self.bench.seed('a', 'inbox', 70); self.bench.seed('a', 'projects', 3)
        self.client.list(self.a, connection, 'folder', 'inbox')                                          # partial: read, not a full sync
        self.now += 100
        items, _ = self.client.list(self.a, connection, 'folder', 'projects')
        with self.store.connect() as con:
            fresh = {f['resource_id']: f for f in self.client.freshness.listing(con, 'a', connection, synthetic_connector.DECLARATION)}
        self.assertEqual((fresh['inbox']['last_read_epoch'], fresh['inbox']['last_full_sync_epoch']), (self.now - 100, None))
        self.assertEqual((fresh['projects']['last_full_sync_epoch'], fresh['projects']['item_count']), (self.now, 3))
        self.assertEqual(self.client.as_of(self.a, connection, items)[0]['last_read_epoch'], self.now)   # "as of" for the source an answer used
        self.now += 1000
        with self.store.connect() as con:
            fresh = {f['resource_id']: f for f in self.client.freshness.listing(con, 'a', connection, synthetic_connector.DECLARATION)}
        self.assertTrue(fresh['projects']['stale'])                                                       # older than the kind's limit: still used, but flagged
        self.assertEqual(len(self.client.list(self.a, connection, 'folder', 'projects')[0]), 3)

    def test_the_last_error_is_kept_as_a_fixed_word(self):
        connection = self.connect()
        self.bench.fault('a', 'list', 'server_error')
        kind_of(self, lambda: self.client.list(self.a, connection, 'folder', 'inbox'))
        row = self.rows('SELECT last_error,last_error_epoch FROM connector_freshness WHERE connection_id=?', (connection,))[0]
        self.assertEqual(row, {'last_error': 'retry_later', 'last_error_epoch': self.now})


if __name__ == '__main__':
    unittest.main()


class FaultsAreLogged(unittest.TestCase):
    """A provider call that fails says why in the server's log: the provider's status and short code, or the type of an adapter's own error. Never its text (it could carry
    what was read). Added after a first mail fill on production stopped again and again with nothing to say why (2026-11-16)."""
    def test_a_failed_call_says_why_without_its_text(self):
        declaration = Declaration(provider='boards', label='Boards', auth='mcp', resource_kinds=('board',), record_kinds=('card',), read_operations=('list',), write_kinds=(),
                                  implementation='mcp', reason='The provider runs an official remote MCP server that offers what the contract needs.')
        client = connector_kit.ConnectorClient(None, None, None, sleep=lambda s: None)
        def refused():
            raise connector_kit.ProviderError(429, 'rateLimitExceeded')
        def broken():
            return {}['Re: private subject line']
        with self.assertLogs('agentai_platform.connector_kit', 'WARNING') as seen:
            with self.assertRaises(connector_kit.ConnectorFault):
                client.call('a', declaration, refused)
            with self.assertRaises(connector_kit.ConnectorFault):
                client.call('b', declaration, broken)
        self.assertIn('kind=retry_later status=429 code=rateLimitExceeded', seen.output[0])
        self.assertIn('type=KeyError', seen.output[1])
        self.assertNotIn('private', ' '.join(seen.output))
