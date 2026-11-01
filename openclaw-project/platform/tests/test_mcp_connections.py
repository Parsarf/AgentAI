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
