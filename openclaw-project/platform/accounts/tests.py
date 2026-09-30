import contextlib
import hashlib
import io
import json
import re
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection, transaction, DatabaseError, IntegrityError
from django.test import TestCase, Client
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from .models import Identity, ActionToken, Audit, OperatorGrant, EmailJob
from .services import create_invite, token_for, consume, Denied, audit
PASSWORD='synthetic-local-Passphrase-943!'

class AccountBoundaryTests(TestCase):
    def setUp(self):
        self.output=io.StringIO(); self.redirect=contextlib.redirect_stdout(self.output);self.redirect.__enter__(); self.addCleanup(self.redirect.__exit__,None,None,None)
        with connection.cursor() as c:
            for a in ['a','b']:
                c.execute("INSERT INTO accounts(id,status) VALUES (%s,'active')",[a])
                c.execute("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,%s)",[a,'project-'+a,'Project '+a])
                c.execute("INSERT INTO deployments(account_id,id,generation,state,secret_binding_id) VALUES (%s,%s,1,'pending',%s)",[a,'deployment-'+a,'CANARY_SECRET_BINDING'])
                c.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (%s,%s,%s,%s)",[a,'project-'+a,'conversation-'+a,'deployment-'+a])
                c.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES (%s,%s,%s,%s,'queued',0)",[a,'project-'+a,'conversation-'+a,'task-'+a])
                c.execute("INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,media_type,size_bytes,sha256,storage_ref) VALUES (%s,%s,%s,%s,1,'out.txt','text/plain',0,%s,%s)",[a,'project-'+a,'task-'+a,'artifact-'+a,'0'*64,'CANARY_STORAGE_SECRET'])
        self.users={}
        for a in ['a','b']:
            user=User.objects.create_user(username='user-'+a,email=a+'@example.invalid',password=PASSWORD)
            Identity.objects.create(user=user,account_id=a,role='customer',verified=True)
            with connection.cursor() as c: c.execute("INSERT INTO memberships(account_id,actor_id,role,status) VALUES (%s,%s,'customer','active')",[a,str(user.pk)])
            self.users[a]=user

    def new_client(self): return Client(enforce_csrf_checks=True)
    def post(self,c,path,data=None,**extra):
        page=c.get('/account/login/',secure=True)
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',page.content.decode()).group(1)
        return c.post(path,json.dumps(data or {}),content_type='application/json',secure=True,HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='https://localhost',**extra)
    def signed(self,a='a'):
        c=self.new_client(); r=self.post(c,'/auth/login',{'email':a+'@example.invalid','password':PASSWORD});self.assertEqual(r.status_code,200); return c
    def operator(self,verified=True,account='a',action='suspend'):
        u=User.objects.create_user(username='operator',email='operator@example.invalid',password=PASSWORD)
        Identity.objects.create(user=u,role='operator',verified=True)
        dev=TOTPDevice.objects.create(user=u,name='op',confirmed=True)
        OperatorGrant.objects.create(user=u,account_id=account,action=action,expires_at=timezone.now()+timedelta(hours=1))
        c=self.new_client(); self.assertEqual(self.post(c,'/auth/login',{'email':u.email,'password':PASSWORD}).status_code,200)
        if verified:
            code=str(totp(dev.bin_key,dev.step,dev.t0,dev.digits,dev.drift)).zfill(dev.digits)
            self.assertEqual(self.post(c,'/auth/mfa',{'code':code}).status_code,200)
        return c,u,dev

    def test_two_accounts_direct_api_and_no_secret_projection(self):
        a,b=self.signed('a'),self.signed('b')
        self.assertEqual(a.get('/v1/projects',secure=True).json()['projects'][0]['id'],'project-a')
        self.assertEqual(b.get('/v1/projects',secure=True).json()['projects'][0]['id'],'project-b')
        for c,other in [(a,'b'),(b,'a')]:
            for route,obj in [('projects','project'),('streams','task'),('tasks','task'),('artifacts','artifact'),('conversations','conversation')]:
                r=c.get(f'/v1/{route}/{obj}-{other}',secure=True); self.assertEqual(r.status_code,404)
                self.assertEqual(r.json(),c.get(f'/v1/{route}/missing',secure=True).json())
            self.assertEqual(c.get('/v1/streams/task-'+('a' if other=='b' else 'b'),secure=True).status_code,503)
        self.assertNotIn('CANARY',a.get('/account/',secure=True).content.decode())

    def test_all_sensitive_routes_gate_identity_and_execution(self):
        c=self.new_client(); a=self.signed()
        for route in ['exports','memory','schedules','integrations','controls','artifacts','tasks','streams','conversations']:
            self.assertEqual(c.get('/v1/'+route,secure=True).status_code,401)
            self.assertEqual(a.get('/v1/'+route,secure=True).status_code,503)
        self.assertEqual(self.post(a,'/v1/tasks',{'account_id':'b'}).status_code,400)

    def test_client_routing_overrides_rejected(self):
        c=self.signed()
        self.assertEqual(c.get('/v1/projects?account_id=b',secure=True).status_code,400)
        self.assertEqual(c.get('/v1/projects',secure=True,HTTP_X_TENANT_ID='b').status_code,400)
        self.assertEqual(self.new_client().get('/v1/me',secure=True,HTTP_X_CUSTOMER_ID='a').status_code,401)

    def test_csrf_origin_method_host_body(self):
        c=self.signed()
        self.assertEqual(c.post('/auth/logout',{},secure=True).status_code,403)
        page=c.get('/account/login/',secure=True); token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',page.content.decode()).group(1)
        self.assertEqual(c.post('/auth/logout','{}',content_type='application/json',secure=True,HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='https://evil.invalid').status_code,403)
        self.assertEqual(c.get('/auth/logout',secure=True).status_code,405)
        self.assertEqual(c.get('/v1/me',secure=True,HTTP_HOST='evil.invalid').status_code,400)
        self.assertEqual(c.post('/auth/login','x'*9000,content_type='application/json',secure=True).status_code,413)

    def test_secure_cookie_rotation_logout_and_expiry(self):
        c=self.signed(); cookie=c.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie['secure']);self.assertTrue(cookie['httponly']);self.assertEqual(cookie['samesite'],'Strict')
        old=cookie.value
        self.assertEqual(self.post(c,'/auth/login',{'email':'a@example.invalid','password':PASSWORD}).status_code,200)
        # Explicit login rotates even when the same identity signs in again.
        self.assertNotEqual(c.cookies[settings.SESSION_COOKIE_NAME].value,old)
        self.assertEqual(self.post(c,'/auth/logout').status_code,200)
        replay=self.new_client();replay.cookies[settings.SESSION_COOKIE_NAME]=old
        self.assertEqual(replay.get('/v1/me',secure=True).status_code,401)
        c=self.signed(); from django.contrib.sessions.models import Session
        Session.objects.filter(session_key=c.cookies[settings.SESSION_COOKIE_NAME].value).update(expire_date=timezone.now()-timedelta(seconds=1))
        self.assertEqual(c.get('/v1/me',secure=True).status_code,401)

    def test_all_device_revocation(self):
        a,b=self.signed(),self.signed()
        self.assertEqual(self.post(a,'/auth/revoke-sessions').status_code,200)
        self.assertEqual(b.get('/v1/me',secure=True).status_code,401)
        self.assertEqual(b.get('/v1/streams/task-a',secure=True).status_code,401)

    def test_membership_role_status_rechecked(self):
        c=self.signed()
        with connection.cursor() as cur: cur.execute("UPDATE memberships SET role='account_admin' WHERE account_id='a'")
        self.assertEqual(c.get('/v1/projects',secure=True).status_code,401)

    def test_suspend_revokes_only_target_account(self):
        a,b=self.signed('a'),self.signed('b');op,_,_=self.operator()
        self.assertEqual(self.post(op,'/internal/accounts/a/suspend').status_code,200)
        self.assertEqual(a.get('/v1/me',secure=True).status_code,401)
        self.assertEqual(b.get('/v1/me',secure=True).status_code,200)
        self.assertEqual(self.post(op,'/internal/accounts/b/suspend').status_code,404)

    def test_operator_requires_mfa_and_scoped_grant(self):
        c,_,dev=self.operator(verified=False)
        self.assertEqual(self.post(c,'/internal/accounts/a/suspend').status_code,404)
        self.assertEqual(c.get('/v1/projects',secure=True).status_code,404)
        self.assertEqual(c.get('/internal/accounts/a/export',secure=True).status_code,403)
        self.assertEqual(c.get('/internal/accounts/a/impersonate',secure=True).status_code,403)
        code=str(totp(dev.bin_key,dev.step,dev.t0,dev.digits,dev.drift)).zfill(dev.digits)
        self.assertEqual(self.post(c,'/auth/mfa',{'code':code}).status_code,200)
        self.assertEqual(self.post(c,'/auth/mfa',{'code':code}).status_code,401)
        self.assertEqual(self.post(c,'/internal/accounts/b/suspend').status_code,404)
        TOTPDevice.objects.filter(pk=dev.pk).update(confirmed=False)
        self.assertEqual(self.post(c,'/internal/accounts/a/suspend').status_code,404)

    def test_operator_membership_revoke_is_scoped(self):
        a,b=self.signed('a'),self.signed('b');op,_,_=self.operator(action='revoke')
        self.assertEqual(self.post(op,'/internal/accounts/a/revoke',{'actor_id':str(self.users['b'].pk)}).status_code,404)
        self.assertEqual(b.get('/v1/me',secure=True).status_code,200)
        self.assertEqual(self.post(op,'/internal/accounts/a/revoke',{'actor_id':str(self.users['a'].pk)}).status_code,200)
        self.assertEqual(a.get('/v1/me',secure=True).status_code,401)

    def test_onboarding_hashed_purpose_bound_single_use(self):
        user,raw=create_invite('new@example.invalid','a','fixture',uuid.uuid4())
        token=ActionToken.objects.get(user=user)
        self.assertNotEqual(token.digest,raw);self.assertEqual(token.digest,hashlib.sha256(raw.encode()).hexdigest())
        c=self.new_client()
        self.assertEqual(self.post(c,'/auth/login',{'email':user.email,'password':PASSWORD}).status_code,401)
        self.assertEqual(self.post(c,'/auth/reset',{'code':raw,'password':PASSWORD}).status_code,404)
        self.assertEqual(self.post(c,'/auth/activate',{'code':raw,'password':PASSWORD}).status_code,200)
        self.assertEqual(self.post(c,'/auth/activate',{'code':raw,'password':PASSWORD}).status_code,404)
        self.assertEqual(self.post(c,'/auth/login',{'email':user.email,'password':PASSWORD}).status_code,200)

    def test_recovery_expiry_replay_and_session_revocation(self):
        c=self.signed(); raw=token_for(self.users['a'],'recovery')
        self.assertEqual(self.post(self.new_client(),'/auth/reset',{'code':raw,'password':PASSWORD+'new'}).status_code,200)
        self.assertEqual(c.get('/v1/me',secure=True).status_code,401)
        self.assertEqual(self.post(self.new_client(),'/auth/reset',{'code':raw,'password':PASSWORD}).status_code,404)
        raw=token_for(self.users['a'],'recovery')
        ActionToken.objects.filter(user=self.users['a']).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post(self.new_client(),'/auth/reset',{'code':raw,'password':PASSWORD}).status_code,404)

    def test_recovery_response_no_enumeration_no_token_delivery_inline(self):
        c=self.new_client()
        known=self.post(c,'/auth/recovery',{'email':'a@example.invalid'})
        missing=self.post(c,'/auth/recovery',{'email':'missing@example.invalid'})
        self.assertEqual(known.status_code,202);self.assertEqual(known.content,missing.content)
        self.assertEqual(EmailJob.objects.count(),1);self.assertEqual(ActionToken.objects.count(),0)
        self.assertNotIn('example.invalid',known.content.decode())

    def test_rate_limit(self):
        c=self.new_client()
        for _ in range(5): self.assertEqual(self.post(c,'/auth/login',{'email':'missing@example.invalid','password':'wrong'}).status_code,401)
        self.assertEqual(self.post(c,'/auth/login',{'email':'missing@example.invalid','password':'wrong'}).status_code,429)

    def test_audit_failure_denies_mutation_and_token_consumption(self):
        c=self.signed(); raw=token_for(self.users['a'],'recovery')
        with patch('accounts.services.Audit.objects.create',side_effect=DatabaseError('CANARY_SECRET_ERROR')):
            self.assertEqual(self.post(c,'/auth/revoke-sessions').status_code,503)
            self.assertEqual(self.post(self.new_client(),'/auth/reset',{'code':raw,'password':PASSWORD+'new'}).status_code,503)
            fresh=self.new_client()
            self.assertEqual(self.post(fresh,'/auth/login',{'email':'a@example.invalid','password':PASSWORD}).status_code,503)
            self.assertEqual(fresh.get('/v1/me',secure=True).status_code,401)
        self.assertEqual(c.get('/v1/me',secure=True).status_code,200)
        self.assertIsNone(ActionToken.objects.get(digest=hashlib.sha256(raw.encode()).hexdigest()).consumed_at)
        self.assertNotIn('CANARY_SECRET_ERROR',self.output.getvalue())

    def test_append_only_audit_and_binding_integrity(self):
        a=audit('fixture','a','object','fixture','completed',uuid.uuid4())
        for action in [lambda:Audit.objects.filter(pk=a.pk).update(action='changed'),lambda:Audit.objects.filter(pk=a.pk).delete()]:
            with self.assertRaises(DatabaseError),transaction.atomic(): action()
        with self.assertRaises(DatabaseError),transaction.atomic(): Identity.objects.filter(user=self.users['a']).update(account_id='unknown')
        with self.assertRaises(IntegrityError),transaction.atomic(): User.objects.create(username='duplicate',email='A@EXAMPLE.INVALID')

    def test_service_identity_cannot_signin(self):
        u=User.objects.create_user(username='service',email='service@example.invalid',password=PASSWORD)
        Identity.objects.create(user=u,role='service',verified=True)
        self.assertEqual(self.post(self.new_client(),'/auth/login',{'email':u.email,'password':PASSWORD}).status_code,401)

    def test_unsafe_render_and_logs(self):
        c=self.signed();self.users['a'].email='<script>CANARY_BODY</script>';self.users['a'].save(update_fields=['email'])
        page=c.get('/account/',secure=True).content.decode()
        self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)
        self.assertNotIn(PASSWORD,self.output.getvalue());self.assertNotIn('CANARY_BODY',self.output.getvalue())
        self.assertNotIn(c.cookies[settings.SESSION_COOKIE_NAME].value,self.output.getvalue())

    def test_truthful_readiness_and_form_flow(self):
        c=self.new_client(); page=c.get('/account/login/',secure=True)
        self.assertEqual(page.status_code,200)
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',page.content.decode()).group(1)
        from urllib.parse import urlencode
        r=c.post('/auth/login',urlencode({'email':'a@example.invalid','password':PASSWORD,'csrfmiddlewaretoken':token}),content_type='application/x-www-form-urlencoded',secure=True,HTTP_ORIGIN='https://localhost')
        self.assertEqual(r.status_code,302);self.assertEqual(r['Location'],'/account/')
        self.assertIn('pending',c.get('/account/',secure=True).content.decode())
        ready=c.get('/readyz',secure=True).json();self.assertFalse(ready['customer_ready']);self.assertTrue(ready['identity_ready'])

    def test_retention_preserves_new_audit_and_restores_guards(self):
        old=timezone.now()-timedelta(days=181)
        # Historical fixture inserted directly with old timestamp, never update audit.
        with connection.cursor() as cur:
            cur.execute('INSERT INTO accounts_audit(id,operation_id,actor,account_id,object_id,action,outcome,request_id,native_operation_id,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s)',[uuid.uuid4().hex,uuid.uuid4().hex,'fixture','a','old','fixture','completed',uuid.uuid4().hex,old])
        with connection.cursor() as cur:
            cur.execute('UPDATE conversations SET created_at=%s,native_session_ref=%s WHERE account_id=%s AND id=%s',[(timezone.now()-timedelta(days=91)).strftime('%Y-%m-%dT%H:%M:%SZ'),'PRIVATE_NATIVE_ROUTE','a','conversation-a'])
            cur.execute("INSERT INTO events(account_id,task_id,id,sequence,kind,public_payload) VALUES ('a','task-a','old-event',1,'progress','{}')")
        call_command('retention_accounts',stdout=io.StringIO())
        from .models import Tombstone
        self.assertTrue(Tombstone.objects.filter(account_id='a',object_id='conversation-a').exists())
        self.assertFalse(Tombstone.objects.filter(account_id='b').exists())
        with connection.cursor() as cur:
            cur.execute('SELECT count(*) FROM events WHERE account_id=%s',['a']);self.assertEqual(cur.fetchone()[0],0)
            cur.execute('SELECT native_session_ref FROM conversations WHERE account_id=%s',['a']);self.assertEqual(cur.fetchone()[0],'PRIVATE_NATIVE_ROUTE')
        self.assertFalse(Audit.objects.filter(action='fixture').exists())
        row=Audit.objects.first()
        with self.assertRaises(DatabaseError),transaction.atomic(): Audit.objects.filter(pk=row.pk).delete()

    def test_completed_audit_failure_cannot_resave_login_or_suspend(self):
        from django.contrib.sessions.models import Session
        original=Audit.objects.create
        def fail_completion(**kw):
            if kw['outcome']=='completed' and kw['action'] in ['identity.login','account.suspend']:
                raise DatabaseError('synthetic completed audit failure')
            return original(**kw)
        c=self.new_client()
        with patch('accounts.services.Audit.objects.create',side_effect=fail_completion):
            self.assertEqual(self.post(c,'/auth/login',{'email':'a@example.invalid','password':PASSWORD}).status_code,503)
        self.assertEqual(c.get('/v1/me',secure=True).status_code,401)
        self.assertEqual(Session.objects.count(),0)
        self.assertFalse(Audit.objects.filter(action='identity.login').exists())
        a=self.signed();op,_,_=self.operator()
        with patch('accounts.services.Audit.objects.create',side_effect=fail_completion):
            self.assertEqual(self.post(op,'/internal/accounts/a/suspend').status_code,503)
        self.assertEqual(a.get('/v1/me',secure=True).status_code,200)
        self.assertFalse(Audit.objects.filter(action='account.suspend').exists())

    def test_expired_grant_and_api_read_limit(self):
        op,_,_=self.operator()
        OperatorGrant.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post(op,'/internal/accounts/a/suspend').status_code,404)
        a=self.signed()
        for _ in range(60): self.assertEqual(a.get('/v1/me',secure=True).status_code,200)
        self.assertEqual(a.get('/v1/me',secure=True).status_code,429)

    def test_host_role_change_revokes_access_and_grants(self):
        a=self.signed()
        call_command('account_admin','role-change',email='a@example.invalid',role='service',stdout=io.StringIO())
        self.assertEqual(a.get('/v1/me',secure=True).status_code,401)
        self.assertEqual(self.post(self.new_client(),'/auth/login',{'email':'a@example.invalid','password':PASSWORD}).status_code,401)

    def test_mail_queue_never_retries_uncertain_job_or_stores_raw_code(self):
        from django.test import override_settings
        job=EmailJob.objects.create(user=self.users['a'],purpose='recovery')
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'),patch('accounts.management.commands.deliver_account_mail.deliver',return_value=False) as delivery:
            call_command('deliver_account_mail',stdout=io.StringIO())
            job.refresh_from_db();self.assertEqual(job.state,'uncertain')
            call_command('deliver_account_mail',stdout=io.StringIO())
            self.assertEqual(delivery.call_count,1)
        token=ActionToken.objects.get(user=self.users['a'])
        self.assertEqual(len(token.digest),64)
        self.assertNotIn('raw',[f.name for f in EmailJob._meta.fields])

    def test_mail_worker_rechecks_revoked_onboarding_membership(self):
        from django.test import override_settings
        user,raw=create_invite('queued@example.invalid','a','fixture',uuid.uuid4())
        job=EmailJob.objects.create(user=user,purpose='onboarding')
        with connection.cursor() as c:c.execute("UPDATE memberships SET status='revoked' WHERE actor_id=%s",[str(user.pk)])
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'),patch('accounts.management.commands.deliver_account_mail.deliver') as delivery:
            call_command('deliver_account_mail',stdout=io.StringIO());delivery.assert_not_called()
        job.refresh_from_db();self.assertEqual(job.state,'failed')
