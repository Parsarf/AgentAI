import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from agentai_platform.lifecycle.coordinator import Coordinator
from agentai_platform.lifecycle.types import DisabledDriver
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.capacity import CapacityResult
from .tests import AccountBoundaryTests
from .models import OperatorGrant
from .lifecycle import coordinator

class LifecycleAPIChecks(TestCase):
    setUp=AccountBoundaryTests.setUp
    new_client=AccountBoundaryTests.new_client
    post=AccountBoundaryTests.post
    signed=AccountBoundaryTests.signed
    operator=AccountBoundaryTests.operator
    def provision(self,client,account='a',**kw):
        return self.post(client,f'/internal/accounts/{account}/deployment/operations',
                         {'kind':'create','key':'create-1',**kw})
    def operator_grant(self):
        client,user,device=self.operator()
        OperatorGrant.objects.create(user=user,account_id='a',action='lifecycle_create',expires_at=timezone.now()+timedelta(hours=1))
        return client,user,device
    def test_account_bound_operator_queue_and_customer_projection(self):
        op,user,_=self.operator_grant();response=self.provision(op)
        self.assertEqual(response.status_code,202,response.content)
        self.assertFalse(response.json()['runtime_enabled'])
        item=response.json()['operation'];self.assertEqual(item['state'],'pending')
        self.assertEqual(self.provision(op).json()['operation']['id'],item['id'])
        OperatorGrant.objects.create(user=user,account_id='a',action='audit',expires_at=timezone.now()+timedelta(hours=1))
        audit_read=op.get('/internal/accounts/a/audit',secure=True)
        self.assertEqual(audit_read.status_code,200)
        self.assertTrue(any(x['object_id']==item['id'] for x in audit_read.json()['lifecycle_events']))
        self.assertEqual(op.get('/internal/accounts/b/audit',secure=True).status_code,404)
        a,b=self.signed('a'),self.signed('b')
        self.assertEqual(a.get('/v1/operations/'+item['id'],secure=True).status_code,200)
        denied=b.get('/v1/operations/'+item['id'],secure=True)
        self.assertEqual(denied.status_code,404)
        self.assertEqual(denied.json(),b.get('/v1/operations/missing',secure=True).json())
        data=a.get('/v1/operations',secure=True).json()
        for name in ['tenant_ref','secret','lease_owner','backup_ref','deployment_id']:
            self.assertNotIn(name,json.dumps(data))
    def test_mfa_scoped_grant_and_customer_denials(self):
        op,user,_=self.operator(verified=False)
        OperatorGrant.objects.create(user=user,account_id='a',action='lifecycle_create',expires_at=timezone.now()+timedelta(hours=1))
        self.assertEqual(self.provision(op).status_code,404)
        self.assertEqual(self.provision(self.signed('a')).status_code,404)
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM lifecycle_cells');self.assertEqual(c.fetchone()[0],0)
    def test_scope_expiry_and_idempotency_payload_change(self):
        op,user,_=self.operator_grant()
        self.assertEqual(self.provision(op,account='b').status_code,404)
        self.assertEqual(self.provision(op).status_code,202)
        self.assertEqual(self.provision(op,kind='start',generation='1').status_code,404)
        self.assertEqual(self.provision(op,generation='1').status_code,400)
        OperatorGrant.objects.filter(user=user).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.provision(op,key='different').status_code,404)
    def test_reject_routing_shell_path_and_secret_fields(self):
        op,_,_=self.operator_grant()
        for field in ['account_id','command','path','image','token','tenant_ref','environment']:
            self.assertEqual(self.provision(op,**{field:'synthetic'}).status_code,400)
    def test_customer_cannot_mutate_operations_and_csrf_required(self):
        client=self.signed('a')
        self.assertEqual(self.post(client,'/v1/operations',{}).status_code,405)
        op,_,_=self.operator_grant()
        self.assertEqual(op.post('/internal/accounts/a/deployment/operations',data='{}',content_type='application/json',secure=True).status_code,403)
    def test_native_gate_stays_disabled_after_queue(self):
        op,_,_=self.operator_grant();response=self.provision(op);item=response.json()['operation']
        with self.assertRaises(CapabilityUnavailable):
            coordinator().run(DisabledDriver(),'a',item['id'],capacity=CapacityResult(1,1,1,1,1,()))
        self.assertFalse(self.signed('a').get('/readyz',secure=True).json()['execution_enabled'])
    def test_revocation_removes_operation_access(self):
        op,_,_=self.operator_grant();item=self.provision(op).json()['operation'];client=self.signed('a')
        with connection.cursor() as c:c.execute("UPDATE memberships SET status='revoked' WHERE account_id='a'")
        self.assertEqual(client.get('/v1/operations/'+item['id'],secure=True).status_code,401)
