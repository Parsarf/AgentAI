import contextlib,io,uuid
from django.test import TestCase
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth.models import User
from django.db import connection
from .models import EmailJob
from .services import token_for,consume
from .tests import AccountBoundaryTests,PASSWORD
class RequestAPIChecks(TestCase):
    new_client=AccountBoundaryTests.new_client
    post=AccountBoundaryTests.post
    def setUp(self):
        self.output=io.StringIO();redirect=contextlib.redirect_stdout(self.output);redirect.__enter__();self.addCleanup(redirect.__exit__,None,None,None)
        self.clients=[]
        for email in ['first@example.invalid','second@example.invalid']:
            call_command('onboard_trial',email=email,stdout=self.output)
            user=User.objects.get(email=email);code=token_for(user,'onboarding');consume(code,'onboarding',PASSWORD,uuid.uuid4())
            client=self.new_client();self.assertEqual(self.post(client,'/auth/login',{'email':email,'password':PASSWORD}).status_code,200);self.clients.append(client)
    def test_onboarding_two_accounts_and_queued_email_only(self):
        self.assertEqual(EmailJob.objects.count(),2)
        with self.assertRaises(CommandError):call_command('onboard_trial',email='third@example.invalid',stdout=self.output)
        self.assertNotEqual(self.clients[0].get('/v1/me',secure=True).json()['account_id'],self.clients[1].get('/v1/me',secure=True).json()['account_id'])
    def test_submit_scope_refresh_cancel_and_escaping(self):
        a,b=self.clients
        response=self.post(a,'/v1/requests',{'message':'<script>private</script>','key':'fixed'})
        self.assertEqual(response.status_code,202,response.content);item=response.json()['request']
        self.assertEqual(self.post(a,'/v1/requests',{'message':'<script>private</script>','key':'fixed'}).json()['request']['id'],item['id'])
        self.assertEqual(b.get('/v1/requests/'+item['id'],secure=True).status_code,404)
        self.assertEqual(self.post(b,'/v1/requests/'+item['id']+'/cancel').status_code,404)
        page=a.get('/account/requests/',secure=True);self.assertContains(page,'&lt;script&gt;private&lt;/script&gt;')
        self.assertEqual(self.post(a,'/v1/requests/'+item['id']+'/cancel').json()['request']['state'],'cancelled')
    def test_long_messages_and_untrusted_fields(self):
        a=self.clients[0]
        self.assertEqual(self.post(a,'/v1/requests',{'message':'x'*16000,'key':'long'}).status_code,202)
        self.assertEqual(self.post(a,'/v1/requests',{'message':'x'*16001,'key':'oversize'}).status_code,400)
        self.assertEqual(self.post(a,'/v1/requests',{'message':'test','key':'spoof','account_id':'other'}).status_code,400)
        self.assertEqual(a.post('/v1/requests',data='{}',content_type='application/json',secure=True).status_code,403)
