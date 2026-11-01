import contextlib
import io
import time
import uuid
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from .services import token_for, consume
from .tests import AccountBoundaryTests, PASSWORD
from .lifecycle import AccountStore
from agentai_platform.model_keys import ModelKeyring
from agentai_platform.mcp_connections.service import ConnectionService

URL='https://service.example.com/mcp'

class InstantRemote:
    async def perform(self,row,credentials,callback_url,**kwargs):
        if row['auth_method']=='oauth' and not kwargs.get('resume'):
            credentials['pending']={'state':'s'*40,'verifier':'v'*64,'issuer':'https://auth.example.com','expires':int(time.time())+600}
            return {'authorize_url':'https://auth.example.com/authorize?state='+'s'*40},credentials
        return {'tools':[{'name':'echo','description':'Untrusted <script> text','inputSchema':{'type':'object','properties':{}}}]},credentials

class McpHTTPChecks(TestCase):
    new_client=AccountBoundaryTests.new_client
    post=AccountBoundaryTests.post
    def setUp(self):
        self.output=io.StringIO();redirect=contextlib.redirect_stdout(self.output);redirect.__enter__();self.addCleanup(redirect.__exit__,None,None,None)
        self.clients=[]
        for email in ['mcp-one@example.invalid','mcp-two@example.invalid']:
            call_command('onboard_trial',email=email,stdout=self.output)
            user=User.objects.get(email=email);consume(token_for(user,'onboarding'),'onboarding',PASSWORD,uuid.uuid4())
            client=self.new_client();self.assertEqual(self.post(client,'/auth/login',{'email':email,'password':PASSWORD}).status_code,200);self.clients.append(client)
        def factory(store=None):
            return ConnectionService(store or AccountStore(connection.settings_dict['NAME']),ModelKeyring.derived('s'*64),callback_url='https://localhost/v1/account/mcp/callback',remote=InstantRemote())
        p=patch('accounts.mcp_connections.service',factory);p.start();self.addCleanup(p.stop)
    def create(self,auth='none',token=''):
        r=self.post(self.clients[0],'/v1/account/mcp',{'name':'Fixture','url':URL,'auth_method':auth,'token':token})
        self.assertEqual(r.status_code,201,r.content);return r.json()['id']
    def test_customer_scope_secrets_csrf_and_tool_controls(self):
        a,b=self.clients;cid=self.create('bearer','fixture-secret-token')
        self.assertEqual(self.post(a,f'/v1/account/mcp/{cid}/test',{}).status_code,200)
        result=a.get('/v1/account/mcp',secure=True);self.assertEqual(result.status_code,200)
        self.assertNotIn('fixture-secret-token',result.content.decode())
        self.assertNotIn('secret_json',result.content.decode())
        self.assertEqual(b.get('/v1/account/mcp',secure=True).json()['connections'],[])
        for action in ['test','disconnect','update','reconnect']:
            self.assertEqual(self.post(b,f'/v1/account/mcp/{cid}/{action}',{}).status_code,404)
        self.assertEqual(self.post(a,f'/v1/account/mcp/{cid}/update',{'tools':{'echo':True}}).status_code,200)
        self.assertEqual(self.post(a,f'/v1/account/mcp/{cid}/update',{'enabled':False}).status_code,200)
        self.assertEqual(a.get('/v1/account/mcp',secure=True).json()['connections'][0]['state'],'disabled')
        self.assertEqual(a.post('/v1/account/mcp',data='{}',content_type='application/json',secure=True).status_code,403)
        self.assertNotIn('fixture-secret-token',self.output.getvalue())
    def test_callback_works_without_strict_session_cookie_but_requires_one_use_browser_binding(self):
        a=self.clients[0];cid=self.create('oauth')
        start=self.post(a,f'/v1/account/mcp/{cid}/test',{})
        self.assertEqual(start.status_code,200,start.content)
        cookie=start.cookies['__Host-lumina_mcp_oauth'];self.assertTrue(cookie['secure']);self.assertTrue(cookie['httponly']);self.assertEqual(cookie['samesite'],'Lax')
        callback='/v1/account/mcp/callback?state='+'s'*40+'&code=fixture-code'
        other=Client();self.assertIn('authorization_failed',other.get(callback,secure=True)['Location'])
        browser=Client();browser.cookies['__Host-lumina_mcp_oauth']=cookie.value
        completed=browser.get(callback,secure=True)
        self.assertEqual(completed['Location'],'/app/integrations?mcp=connected')
        self.assertEqual(completed['Referrer-Policy'],'no-referrer')
        replay=browser.get(callback,secure=True);self.assertIn('authorization_failed',replay['Location'])
    def test_revoked_login_cannot_complete_oauth_using_the_callback_cookie(self):
        a=self.clients[0];cid=self.create('oauth');start=self.post(a,f'/v1/account/mcp/{cid}/test',{})
        cookie=start.cookies['__Host-lumina_mcp_oauth'].value
        self.post(a,'/auth/logout',{})
        browser=Client();browser.cookies['__Host-lumina_mcp_oauth']=cookie
        response=browser.get('/v1/account/mcp/callback?state='+'s'*40+'&code=fixture-code',secure=True)
        self.assertIn('authorization_failed',response['Location'])
    def test_disconnect_removes_credentials_and_reports_revocation_support(self):
        a=self.clients[0];cid=self.create('bearer','fixture-secret-token')
        result=self.post(a,f'/v1/account/mcp/{cid}/disconnect',{})
        self.assertTrue(result.json()['credentials_deleted'])
        self.assertEqual(result.json()['provider_revocation'],'not_supported')
        self.assertEqual(a.get('/v1/account/mcp',secure=True).json()['connections'],[])
