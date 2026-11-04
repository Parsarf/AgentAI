import json
import tempfile
import unittest
from pathlib import Path
from agentai_platform.store import Store
from agentai_platform.security import Principal, NotFound
from agentai_platform.model_keys import ModelKeyring
from agentai_platform.mcp_connections.service import ConnectionService, namespaced
from agentai_platform.mcp_connections.network import ConnectionError
from .mcp_fixture import Fixture, URL


class ConnectionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state'/'db.sqlite3'); self.store.initialize()
        self.fixture=Fixture(); self.addCleanup(self.fixture.close)
        with self.store.connect() as con:
            for account in ('a','b'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')",(account,))
                con.execute("INSERT INTO memberships(account_id,actor_id,role,status) VALUES (?,?,'customer','active')",(account,account))
        self.a=Principal('a','a','customer'); self.b=Principal('b','b','customer')
        self.service=ConnectionService(self.store,ModelKeyring.derived('s'*64),callback_url='https://lumina.mcp-demo.net/v1/account/mcp/callback',remote=self.fixture.remote())
    def connect(self, auth='none', token=''):
        cid=self.service.create(self.a,name='Fixture',url=URL,auth_method=auth,token=token)
        self.assertTrue(self.service.test(self.a,cid)['connected'])
        return cid
    def approve(self):
        pending=self.service.listing(self.a)['pending_calls']
        self.service.approve(self.a,pending[0]['id'],True)
    def test_real_sdk_initialization_paginated_discovery_and_session_cleanup(self):
        cid=self.connect()
        item=self.service.listing(self.a)['connections'][0]
        self.assertEqual(item['state'],'connected');self.assertEqual(len(item['tools']),3)
        self.assertGreater(self.fixture.sessions_closed,0)
        self.assertEqual(self.service.catalog('a'),[])
        self.service.update(self.a,cid,tools={'echo':True})
        spec=self.service.catalog('a')[0]
        self.assertEqual(spec['name'],namespaced(cid,'echo'))
        self.assertIn('Untrusted',spec['description'])
    def test_isolation_exact_approval_arguments_call_and_no_automatic_retry(self):
        cid=self.connect();self.service.update(self.a,cid,tools={'echo':True})
        with self.assertRaises(NotFound):self.service.update(self.b,cid,name='steal')
        with self.assertRaises(NotFound):self.service.test(self.b,cid)
        self.assertEqual(self.service.catalog('b'),[])
        name=namespaced(cid,'echo')
        pending=self.service.call('a',name,{'text':'hello'},'r1')
        self.assertTrue(pending['isError']);self.assertEqual(self.fixture.calls,[])
        call=self.service.listing(self.a)['pending_calls'][0]
        with self.assertRaises(NotFound):self.service.approve(self.b,call['id'],True)
        self.approve()
        result=self.service.call('a',name,{'text':'hello'},'r1')
        self.assertEqual(result['structuredContent'],{'text':'hello'})
        self.assertEqual(self.service.call('a',name,{'text':'hello'},'r1'),result)
        self.assertEqual(len(self.fixture.calls),1)
        with self.assertRaises(ConnectionError):self.service.call('a',name,{'unexpected':1},'r2')
    def test_disconnect_erases_secrets_and_choices(self):
        cid=self.connect('bearer','a-bearer-secret')
        with self.store.connect() as con:
            text=con.execute('SELECT secret_json FROM mcp_connections').fetchone()[0]
        self.assertNotIn('a-bearer-secret',text)
        self.assertNotIn('a-bearer-secret',json.dumps(self.service.listing(self.a)))
        result=self.service.disconnect(self.a,cid)
        self.assertTrue(result['credentials_deleted'])
        self.assertEqual(self.service.listing(self.a)['connections'],[])
        with self.store.connect() as con:self.assertFalse(con.execute('SELECT 1 FROM mcp_tool_choices').fetchone())
    def test_uncertain_write_cannot_be_automatically_repeated_even_when_annotation_claims_readonly(self):
        cid=self.connect();self.service.update(self.a,cid,tools={'write':True})
        name=namespaced(cid,'write')
        self.service.call('a',name,{'text':'write'},'r1');self.approve();self.fixture.fail_write=True
        with self.assertRaises(ConnectionError) as first:self.service.call('a',name,{'text':'write'},'r1')
        self.assertEqual(first.exception.code,'uncertain_result')
        with self.assertRaises(ConnectionError):self.service.call('a',name,{'text':'write'},'r2')
        self.assertEqual(len(self.fixture.calls),1)
    def test_run_without_asking_is_the_owners_per_tool_choice_and_resets_when_anything_changes(self):
        cid=self.connect();name=namespaced(cid,'echo')
        with self.assertRaises(ConnectionError):self.service.set_auto_approve(self.a,cid,{'echo':True})   # a tool must be enabled first
        self.service.update(self.a,cid,tools={'echo':True})
        self.assertFalse(self.service.listing(self.a)['connections'][0]['tools'][0]['auto_approve'])
        self.assertTrue(self.service.call('a',name,{'text':'x'},'r1')['isError'])                          # default is still to ask
        with self.assertRaises(NotFound):self.service.set_auto_approve(self.b,cid,{'echo':True})
        self.service.set_auto_approve(self.a,cid,{'echo':True})
        result=self.service.call('a',name,{'text':'hi'},'r2')
        self.assertEqual(result['structuredContent'],{'text':'hi'});self.assertEqual(len(self.fixture.calls),1)
        self.assertEqual(self.service.call('a',name,{'text':'hi'},'r2'),result)                            # same request is not run twice
        self.assertEqual(len(self.fixture.calls),1)
        self.service.call('a',name,{'text':'again'},'r3');self.assertEqual(len(self.fixture.calls),2)
        self.service.update(self.a,cid,tools={'echo':False})                                              # disabling clears it
        self.service.update(self.a,cid,tools={'echo':True})
        self.assertFalse(self.service.listing(self.a)['connections'][0]['tools'][0]['auto_approve'])
        self.service.set_auto_approve(self.a,cid,{'echo':True})
        self.fixture.tools[0]['description']='Changed definition';self.service.test(self.a,cid)           # a changed tool must be reviewed again
        self.service.update(self.a,cid,tools={'echo':True})
        self.assertFalse(self.service.listing(self.a)['connections'][0]['tools'][0]['auto_approve'])
        self.assertTrue(self.service.call('a',name,{'text':'z'},'r4')['isError'])
    def test_changed_tools_are_disabled_and_removed_without_deployment(self):
        cid=self.connect();self.service.update(self.a,cid,tools={'echo':True})
        self.fixture.tools[0]['description']='Changed definition'
        self.service.test(self.a,cid)
        self.assertEqual(self.service.catalog('a'),[])
        self.service.update(self.a,cid,tools={'echo':True})
        self.fixture.tools=self.fixture.tools[1:]
        self.service.test(self.a,cid)
        self.assertEqual(self.service.catalog('a'),[])

    def test_oauth_discovery_dcr_pkce_callback_state_refresh_and_revocation(self):
        from urllib.parse import urlsplit,parse_qs
        self.fixture.oauth=True
        cid=self.service.create(self.a,name='OAuth fixture',url=URL,auth_method='oauth')
        pending=self.service.test(self.a,cid,session='browser-a')
        self.assertFalse(pending['connected'])
        params=parse_qs(urlsplit(pending['authorize_url']).query)
        self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertEqual(self.service.listing(self.a)['connections'][0]['state'],'authentication_required')
        with self.assertRaises(ConnectionError):self.service.callback(self.a,params['state'][0],'code','wrong-browser')
        result=self.service.callback(self.a,params['state'][0],'fixture-code','browser-a')
        self.assertTrue(result['connected'])
        exchange=self.fixture.token_requests[-1]
        import hashlib,base64
        challenge=base64.urlsafe_b64encode(hashlib.sha256(exchange['code_verifier'][0].encode()).digest()).decode().rstrip('=')
        self.assertEqual(params['code_challenge'][0],challenge)
        with self.assertRaises(ConnectionError):self.service.callback(self.a,params['state'][0],'fixture-code','browser-a')
        with self.store.connect() as con:row=dict(con.execute('SELECT * FROM mcp_connections').fetchone())
        credentials=self.service.open(row);credentials['expires_at']=1
        with self.store.connect() as con:con.execute('UPDATE mcp_connections SET secret_json=?',(self.service.seal('a',cid,credentials),))
        self.service.test(self.a,cid)
        self.assertEqual(self.fixture.token_requests[-1]['grant_type'],['refresh_token'])
        self.assertNotIn('fixture-access-secret',json.dumps(self.service.listing(self.a)))
        self.assertEqual(self.service.disconnect(self.a,cid)['provider_revocation'],'accepted')

    def test_preserving_structured_image_and_error_results_and_scrubbing_saved_tokens(self):
        cid=self.connect('bearer','fixture-access-secret');self.service.update(self.a,cid,tools={'picture':True})
        self.service.call('a',namespaced(cid,'picture'),{},'r1');self.approve()
        result=self.service.call('a',namespaced(cid,'picture'),{},'r1')
        self.assertEqual(result['structuredContent'],{'ok':True})
        self.assertTrue(result['isError'])
        self.assertTrue(any(b['type']=='image' for b in result['content']))
        self.assertNotIn('fixture-access-secret',json.dumps(result))

    def test_pre_registered_oauth_credentials_bind_to_the_configured_issuer(self):
        from urllib.parse import urlsplit,parse_qs
        from .mcp_fixture import ISSUER
        self.fixture.oauth=True
        self.service.registrations={URL:{'issuer':ISSUER,'client_id':'operator-app','client_secret':'operator-secret'}}
        cid=self.service.create(self.a,name='Registered',url=URL,auth_method='oauth')
        result=self.service.test(self.a,cid,session='browser')
        query=parse_qs(urlsplit(result['authorize_url']).query)
        self.assertEqual(query['client_id'],['operator-app'])
        self.service.callback(self.a,query['state'][0],'fixture-code','browser')
        self.assertEqual(self.fixture.token_requests[-1]['client_secret'],['operator-secret'])

    def test_declining_an_exact_call_cannot_be_bypassed_in_the_same_task(self):
        cid=self.connect(); self.service.update(self.a,cid,tools={'echo':True})
        name=namespaced(cid,'echo'); args={'text':'declined'}
        self.service.call('a',name,args,'r1')
        call=self.service.listing(self.a)['pending_calls'][0]
        self.service.approve(self.a,call['id'],False)
        with self.assertRaises(ConnectionError) as error: self.service.call('a',name,args,'r1')
        self.assertEqual(error.exception.code,'approval_rejected'); self.assertEqual(self.fixture.calls,[])

    def test_authentication_challenge_after_dispatch_is_never_replayed(self):
        cid=self.connect(); self.service.update(self.a,cid,tools={'write':True})
        name=namespaced(cid,'write'); args={'text':'one attempt'}
        self.service.call('a',name,args,'r1'); self.approve(); self.fixture.reject_call=True
        with self.assertRaises(ConnectionError) as error: self.service.call('a',name,args,'r1')
        self.assertEqual(error.exception.code,'uncertain_result'); self.assertEqual(len(self.fixture.calls),1)
        self.assertEqual(self.service.listing(self.a)['connections'][0]['state'],'authentication_required')

    def test_connection_serializes_credentials_and_disable_cancels_in_flight_session(self):
        import asyncio, threading
        from concurrent.futures import ThreadPoolExecutor
        cid=self.connect(); started=threading.Event(); ended=threading.Event()
        class WaitingRemote:
            async def perform(remote,*args,**kwargs):
                started.set()
                try: await asyncio.sleep(20)
                finally: ended.set()
        self.service.remote=WaitingRemote()
        with ThreadPoolExecutor() as pool:
            future=pool.submit(self.service.test,self.a,cid)
            self.assertTrue(started.wait(2))
            with self.assertRaises(ConnectionError) as busy: self.service.test(self.a,cid)
            self.assertEqual(busy.exception.code,'busy')
            self.service.update(self.a,cid,enabled=False)
            with self.assertRaises(ConnectionError): future.result(timeout=3)
        self.assertTrue(ended.is_set())
        self.assertEqual(self.service.listing(self.a)['connections'][0]['state'],'disabled')

    def test_stopping_an_agent_call_closes_its_session_and_preserves_uncertainty(self):
        import asyncio, threading
        from concurrent.futures import ThreadPoolExecutor
        cid=self.connect(); self.service.update(self.a,cid,tools={'write':True})
        name=namespaced(cid,'write'); args={'text':'stop'}
        self.service.call('a',name,args,'r1'); self.approve()
        started=threading.Event(); stopped=threading.Event(); ended=threading.Event()
        class WaitingRemote:
            async def perform(remote,*args,**kwargs):
                started.set()
                try: await asyncio.sleep(20)
                finally: ended.set()
        self.service.remote=WaitingRemote()
        with ThreadPoolExecutor() as pool:
            future=pool.submit(self.service.call,'a',name,args,'r1',closed=stopped.is_set)
            self.assertTrue(started.wait(2)); stopped.set()
            with self.assertRaises(ConnectionError) as error: future.result(timeout=3)
        self.assertEqual(error.exception.code,'uncertain_result'); self.assertTrue(ended.is_set())
        self.assertEqual(self.service.listing(self.a)['pending_calls'][0]['state'],'uncertain')

    def test_rejected_credentials_do_not_report_connected_or_leak_tokens(self):
        self.fixture.oauth=True
        cid=self.service.create(self.a,name='Rejected',url=URL,auth_method='bearer',token='rejected-secret')
        with self.assertRaises(ConnectionError) as error: self.service.test(self.a,cid)
        self.assertEqual(error.exception.code,'authentication_required')
        public=self.service.listing(self.a)
        self.assertEqual(public['connections'][0]['state'],'authentication_required')
        self.assertNotIn('rejected-secret',json.dumps(public))
        with self.store.connect() as con: row=dict(con.execute('SELECT * FROM mcp_connections').fetchone())
        with self.assertRaises(ConnectionError): self.service.open({**row,'account_id':'b'})

    def test_expired_refresh_requires_new_authorization_not_false_success(self):
        from urllib.parse import urlsplit,parse_qs
        self.fixture.oauth=True
        cid=self.service.create(self.a,name='Expired',url=URL,auth_method='oauth')
        pending=self.service.test(self.a,cid,session='browser')
        state=parse_qs(urlsplit(pending['authorize_url']).query)['state'][0]
        self.service.callback(self.a,state,'fixture-code','browser')
        with self.store.connect() as con: row=dict(con.execute('SELECT * FROM mcp_connections').fetchone())
        credentials=self.service.open(row);credentials['expires_at']=1
        with self.store.connect() as con: con.execute('UPDATE mcp_connections SET secret_json=?',(self.service.seal('a',cid,credentials),))
        self.fixture.reject_refresh=True;self.fixture.tokens=[]
        result=self.service.test(self.a,cid,session='browser')
        self.assertFalse(result['connected']);self.assertTrue(result['authorize_url'])
        self.assertEqual(self.service.listing(self.a)['connections'][0]['state'],'authentication_required')

    def test_one_unusable_tool_never_fails_the_connection_and_the_rest_run(self):
        obj = lambda **props: {'type': 'object', 'properties': props}
        self.fixture.tools += [
            {'name': 'find', 'description': 'Asana-like: ids are validated by a pattern', 'inputSchema': {**obj(gid={'type': 'string', 'pattern': '^[0-9]+$'}), 'required': ['gid']}},
            {'name': 'ext', 'description': 'SECRET-DESCRIPTION', 'inputSchema': obj(a={'$ref': 'https://example.com/x.json'})},
            {'name': 'spoof', 'description': 'd', 'inputSchema': obj(_lumina_origin={'type': 'string'})},
            {'name': 'loop', 'description': 'd', 'inputSchema': {**obj(n={'$ref': '#/$defs/node'}), '$defs': {'node': {'type': 'object', 'properties': {'c': {'$ref': '#/$defs/node'}}}}}},
            {'name': 'echo', 'description': 'a duplicate name', 'inputSchema': obj()},
            {'name': 'bad name', 'description': 'd', 'inputSchema': obj()}]
        with self.assertLogs('agentai.mcp', 'WARNING') as logs:
            cid = self.connect()
        tools = {t['name']: t for t in self.service.listing(self.a)['connections'][0]['tools']}
        self.assertEqual(self.service.listing(self.a)['connections'][0]['state'], 'connected')
        self.assertEqual(set(tools), {'echo', 'write', 'picture', 'find', 'ext', 'spoof', 'loop'})     # the duplicate and the unusable name are dropped
        for ok in ('echo', 'write', 'picture', 'find'):
            self.assertIsNone(tools[ok]['unusable'], ok)
        self.assertIn('outside itself', tools['ext']['unusable']); self.assertIn('reserves', tools['spoof']['unusable']); self.assertIn('recursive', tools['loop']['unusable'])
        self.assertEqual(tools['ext']['inputSchema'], {})                                                # a refused tool keeps no schema, only its name and a short description
        self.service.update(self.a, cid, tools={'find': True})
        self.assertEqual([t['name'] for t in self.service.catalog('a')], [namespaced(cid, 'find')])
        with self.assertRaises(ConnectionError) as caught:
            self.service.update(self.a, cid, tools={'ext': True})
        self.assertEqual(caught.exception.code, 'tool_unusable')
        line = logs.output[0]
        self.assertIn('mcp_tools_refused', line); self.assertIn('refused=5', line); self.assertNotIn('SECRET-DESCRIPTION', line)

    def test_a_server_with_more_than_a_hundred_tools_keeps_the_first_hundred(self):
        self.fixture.tools = [{'name': f't{n}', 'description': 'd', 'inputSchema': {'type': 'object', 'properties': {}}} for n in range(120)]
        self.connect()
        item = self.service.listing(self.a)['connections'][0]
        self.assertEqual(item['state'], 'connected'); self.assertEqual(len(item['tools']), 100)

    # ---- the assistant's view: the most-used tools are direct, the rest are found on demand --------------------------------------------------------------
    def many_tools(self, count=40):
        self.fixture.tools = [{'name': f't{n}', 'description': f'Tool number {n} of the fixture', 'inputSchema': {'type': 'object', 'properties': {'x': {'type': 'string'}}}} for n in range(count)]
        cid = self.connect()
        self.service.update(self.a, cid, tools={t['name']: True for t in self.service.listing(self.a)['connections'][0]['tools']})
        return cid

    def use(self, cid, tool, times, age_days=0):
        import time, uuid
        now = int(time.time())
        with self.store.connect() as con:
            for _ in range(times):
                con.execute("INSERT INTO mcp_calls(account_id,id,connection_id,tool_name,payload_hash,schema_hash,request_id,arguments_json,state,expires_epoch,created_epoch) "
                            "VALUES ('a',?,?,?,'p','s','r','{}','completed',?,?)", (uuid.uuid4().hex, cid, tool, now, now - age_days * 86400))

    def test_the_caller_closed_check_never_runs_inside_the_event_loop(self):
        """closed() reads the database; Django refuses that inside async code, which dropped the relay connection on every re-check of a stale connection."""
        import asyncio
        cid = self.connect(); seen = []
        def closed():
            try: asyncio.get_running_loop()
            except RuntimeError: seen.append('thread'); return False
            seen.append('loop'); raise RuntimeError('database read inside the event loop')
        self.service.test(self.a, cid, closed=closed)
        self.assertTrue(seen); self.assertEqual(set(seen), {'thread'})

    def test_an_unexpected_failure_reaches_the_assistant_as_a_message_not_a_dropped_connection(self):
        from agentai_platform.mcp_connections.relay import RemoteTools, DISCOVER
        class Broken:
            def refresh_catalog(self, *a, **k): raise RuntimeError('boom')
        out = RemoteTools(Broken()).call('a', {}, lambda: False, name=DISCOVER['name'])
        self.assertTrue(out['isError']); self.assertIn('unexpectedly', out['content'][0]['text'])

    def test_a_few_enabled_tools_are_all_offered_directly(self):
        cid = self.connect()
        self.service.update(self.a, cid, tools={'echo': True, 'write': True, 'picture': True})
        self.assertEqual({t['name'] for t in self.service.catalog('a')}, {namespaced(cid, n) for n in ('echo', 'write', 'picture')})

    def test_many_tools_can_be_enabled_and_only_the_most_used_become_direct_tools(self):
        cid = self.many_tools(40)                                                           # more than the old limit of 32
        self.assertEqual(len(self.service.enabled_tools('a')), 40)
        self.assertEqual(self.service.catalog('a'), [])                                     # nothing used yet: nothing promoted
        for tool, times in (('t3', 5), ('t7', 3), ('t1', 1), ('t0', 1), ('t2', 1), ('t4', 1), ('t5', 1), ('t6', 1), ('t8', 1)):
            self.use(cid, tool, times)
        self.use(cid, 't39', 9, age_days=100)                                               # too old to count
        names = [t['name'] for t in self.service.catalog('a')]
        self.assertEqual(len(names), 8)
        self.assertEqual(names[:2], [namespaced(cid, 't3'), namespaced(cid, 't7')])
        self.assertNotIn(namespaced(cid, 't39'), names)

    def test_discover_is_compact_searchable_and_describes_one_tool_on_request(self):
        from agentai_platform.mcp_connections.relay import RemoteTools
        cid = self.many_tools(70); self.use(cid, 't3', 4)
        remote = RemoteTools(self.service)
        ask = lambda **arguments: remote.call('a', arguments, lambda: False, name='lumina_mcp_discover')
        listing = ask()['content'][0]['text']
        self.assertIn('70 enabled tool(s)', listing); self.assertIn('... 10 more', listing); self.assertNotIn('inputSchema', listing)
        direct = [l for l in ask(query='t3')['content'][0]['text'].splitlines() if l.startswith('- ' + namespaced(cid, 't3'))]
        self.assertEqual(len(direct), 1); self.assertIn('[direct]', direct[0])
        one = ask(query='t11')['content'][0]['text']
        self.assertIn('1 enabled tool(s)', one); self.assertNotIn('[direct]', one)
        detail = ask(tool='t11')['content'][0]['text']
        self.assertIn('"inputSchema"', detail); self.assertIn('"name_at_the_service": "t11"', detail)
        self.assertIn('No enabled tool has that name', ask(tool='nope')['content'][0]['text'])
        refused = ask(bogus='x')
        self.assertTrue(refused['isError'])

    def test_a_plain_tool_name_works_when_only_one_service_has_it(self):
        cid = self.connect()
        self.service.update(self.a, cid, tools={'echo': True})
        self.assertEqual(self.service.resolve('a', 'echo'), namespaced(cid, 'echo'))
        self.assertEqual(self.service.resolve('a', namespaced(cid, 'echo')), namespaced(cid, 'echo'))
        with self.assertRaises(ConnectionError) as caught: self.service.resolve('a', 'nope')
        self.assertEqual(caught.exception.code, 'tool_removed')
        cid2 = self.service.create(self.a, name='Second', url=URL, auth_method='none'); self.assertTrue(self.service.test(self.a, cid2)['connected'])
        self.service.update(self.a, cid2, tools={'echo': True})
        with self.assertRaises(ConnectionError) as caught: self.service.resolve('a', 'echo')
        self.assertEqual(caught.exception.code, 'ambiguous_tool')


class ToolVerdicts(unittest.TestCase):
    """What makes ONE tool unusable. Everything else about a server is allowed to just work."""
    def verdict(self, schema, name='t', seen=()):
        from agentai_platform.mcp_connections.service import tool_verdict
        tool = {'name': name, 'description': 'd'}
        if schema is not None: tool['inputSchema'] = schema
        return tool_verdict(tool, set(seen))

    def test_ordinary_schemas_are_usable_including_regexes_and_chained_local_references(self):
        self.assertIsNone(self.verdict({'type': 'object', 'required': ['gid'], 'properties': {'gid': {'type': 'string', 'pattern': '^[0-9]+$'}}, 'patternProperties': {'^x-': {'type': 'string'}}}))
        self.assertIsNone(self.verdict({'type': 'object', 'properties': {'pattern': {'type': 'string'}}}))                # a parameter merely NAMED pattern
        chained = {'type': 'object', 'properties': {'a': {'$ref': '#/$defs/a'}}, '$defs': {'a': {'type': 'object', 'properties': {'b': {'$ref': '#/$defs/b'}}}, 'b': {'type': 'string'}}}
        self.assertIsNone(self.verdict(chained))                                                                        # a definition may refer to another one; only a cycle is refused
        self.assertIsNone(self.verdict({'type': 'object', 'properties': {'a': {'$ref': '#/definitions/a'}}, 'definitions': {'a': {'type': 'string'}}}))

    def test_only_harmful_or_unusable_tools_are_refused_and_each_says_why(self):
        recursive = {'type': 'object', 'properties': {'a': {'$ref': '#/$defs/a'}}, '$defs': {'a': {'properties': {'x': {'$ref': '#/$defs/b'}}}, 'b': {'properties': {'y': {'$ref': '#/$defs/a'}}}}}
        cases = [({'type': 'object', 'properties': {'a': {'$ref': '#'}}}, 'recursive'), (recursive, 'recursive'),
                 ({'type': 'object', 'properties': {'a': {'$ref': 'https://example.com/s.json'}}}, 'outside'), ({'type': 'object', 'properties': {'a': {'$dynamicRef': '#x'}}}, 'outside'),
                 ({'type': 'object', 'properties': {'_lumina_origin': {}}}, 'reserves'), ({'type': 'object', 'required': ['_lumina_origin']}, 'reserves'),
                 ({'type': 'array'}, 'not an object'), ({'type': 'object', 'properties': 5}, 'not valid JSON Schema'), (None, 'no input schema'),
                 ({'type': 'object', 'properties': {'big': {'description': 'x' * 30000}}}, 'too large')]
        for schema, word in cases:
            phrase, keep_stub = self.verdict(schema)
            self.assertIn(word, phrase); self.assertTrue(keep_stub)

    def test_names_that_cannot_be_addressed_are_dropped_not_stubbed(self):
        schema = {'type': 'object', 'properties': {}}
        for name, seen in (('bad name', ()), ('', ()), ('x' * 200, ()), ('dup', ('dup',))):
            phrase, keep_stub = self.verdict(schema, name, seen)
            self.assertFalse(keep_stub, name)

    def test_the_operator_log_names_tools_and_reasons_never_schema_content(self):
        from agentai_platform.mcp_connections.service import log_schema_rejection
        secret = 'SECRET-DESCRIPTION-TEXT'
        tools = [{'name': 'good', 'description': 'd', 'inputSchema': {'type': 'object'}},
                 {'name': 'bad\nname', 'description': secret, 'inputSchema': {'type': 'object', 'properties': {'x': {'$dynamicRef': secret}}}},
                 {'name': 'ext', 'description': secret, 'inputSchema': {'type': 'object', 'properties': {'x': {'$dynamicRef': secret}}}}]
        with self.assertLogs('agentai.mcp', 'WARNING') as logs:
            log_schema_rejection('0123456789abcdef0123456789abcdef', tools)
        line = logs.output[0]
        self.assertIn('tools=3 refused=2', line); self.assertIn('bad?name', line); self.assertNotIn(secret, line); self.assertNotIn('\n', line)
        self.assertIn('connection=01234567 ', line); self.assertNotIn('0123456789abcdef0123', line)


class ArgumentChecks(unittest.TestCase):
    """Checking the model's arguments here is a convenience; the server that owns the tool is the authority."""
    PATTERNED = {'type': 'object', 'required': ['gid'], 'properties': {'gid': {'type': 'string', 'pattern': '^[0-9]+$'}, 'n': {'type': 'integer', 'maximum': 5}},
                 'patternProperties': {'^x-': {'type': 'string'}}}

    def test_patterns_are_the_servers_to_enforce_but_everything_else_is_checked_with_a_useful_message(self):
        from agentai_platform.mcp_connections.service import validate_arguments
        validate_arguments(self.PATTERNED, {'gid': 'not-digits'})
        for bad, where in (({}, 'the arguments'), ({'gid': 5}, 'gid'), ({'gid': 'a', 'n': 9}, 'n'), ({'gid': 'a', 'n': 'x'}, 'n')):
            with self.assertRaises(ConnectionError, msg=str(bad)) as caught:
                validate_arguments(self.PATTERNED, bad)
            self.assertEqual(caught.exception.code, 'invalid_arguments'); self.assertIn(where, caught.exception.message)

    def test_a_catastrophic_pattern_cannot_hang_validation(self):
        import time
        from agentai_platform.mcp_connections.service import validate_arguments
        started = time.monotonic()
        validate_arguments({'type': 'object', 'properties': {'v': {'type': 'string', 'pattern': '^(a+)+$'}}}, {'v': 'a' * 40 + '!'})
        self.assertLess(time.monotonic() - started, 1.0)

    def test_a_schema_that_cannot_be_interpreted_here_never_blocks_a_call(self):
        from agentai_platform.mcp_connections.service import validate_arguments
        validate_arguments({'type': 'object', 'properties': {'a': {'$ref': '#/$defs/missing'}}}, {'a': 1})
        with self.assertRaises(ConnectionError):
            validate_arguments({'type': 'object'}, ['not', 'an', 'object'])
        with self.assertRaises(ConnectionError):
            validate_arguments({'type': 'object'}, {'blob': 'x' * 20000})
