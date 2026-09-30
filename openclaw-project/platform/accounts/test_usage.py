from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from .tests import AccountBoundaryTests

class UsageAPIChecks(TestCase):
    setUp=AccountBoundaryTests.setUp
    new_client=AccountBoundaryTests.new_client
    post=AccountBoundaryTests.post
    signed=AccountBoundaryTests.signed
    def test_scoped_trial_usage_and_no_renewal_reset(self):
        call_command('seed_trial',account='a',stdout=self.output)
        a,b=self.signed('a'),self.signed('b')
        result=a.get('/v1/costs',secure=True)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['period_remaining_microusd'],1000000)
        self.assertIsNone(result.json()['estimated_microusd'])
        self.assertFalse(result.json()['live_provider_accounting_verified'])
        self.assertEqual(b.get('/v1/costs',secure=True).status_code,503)
        self.assertEqual(a.get('/account/usage/',secure=True).status_code,200)
        with self.assertRaises(CommandError):call_command('seed_trial',account='a',stdout=self.output)
        with connection.cursor() as c:
            c.execute("SELECT count(*) FROM entitlements WHERE account_id='a'");self.assertEqual(c.fetchone()[0],1)
    def test_usage_is_read_only_and_routing_override_rejected(self):
        a=self.signed('a')
        self.assertEqual(self.post(a,'/v1/costs',{}).status_code,405)
        self.assertEqual(a.get('/v1/costs?account_id=b',secure=True).status_code,400)
