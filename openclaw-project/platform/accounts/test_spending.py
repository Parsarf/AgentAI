from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from .tests import AccountBoundaryTests


class SpendingLimitAPIChecks(TestCase):
    """Settings > Usage: a customer's own spending limits. Lumina has none; an empty field means no limit; one account never sees or changes another's."""
    setUp = AccountBoundaryTests.setUp
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    NONE = {'task_microusd': None, 'daily_microusd': None, 'period_microusd': None}

    def test_no_limit_by_default_and_each_account_sets_only_its_own(self):
        a, b = self.signed('a'), self.signed('b')
        first = a.get('/v1/spending-limits', secure=True)
        self.assertEqual(first.status_code, 200)
        self.assertEqual((first.json()['limits'], first.json()['chosen']), (self.NONE, False))
        saved = self.post(a, '/v1/spending-limits', {'task': '2.50', 'daily': '', 'period': '$40'})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['limits'], {'task_microusd': 2_500_000, 'daily_microusd': None, 'period_microusd': 40_000_000})
        self.assertTrue(a.get('/v1/spending-limits', secure=True).json()['chosen'])
        self.assertEqual(b.get('/v1/spending-limits', secure=True).json()['limits'], self.NONE)       # b is untouched
        cleared = self.post(a, '/v1/spending-limits', {'task': '', 'daily': '', 'period': ''})
        self.assertEqual((cleared.json()['limits'], cleared.json()['chosen']), (self.NONE, True))       # "no limit" is a choice of its own
        with connection.cursor() as c:
            c.execute("SELECT count(*) FROM accounts_audit WHERE action='spending.limits_change' AND account_id='a'")
            self.assertEqual(c.fetchone()[0], 2)

    def test_only_dollar_amounts_are_accepted(self):
        a = self.signed('a')
        for bad in [{'task': '0', 'daily': '', 'period': ''}, {'task': '-5', 'daily': '', 'period': ''}, {'task': 'lots', 'daily': '', 'period': ''},
                    {'task': '1.234', 'daily': '', 'period': ''}, {'task': '1e9', 'daily': '', 'period': ''}, {'task': '5'}, {'task': '5', 'daily': '', 'period': '', 'account_id': 'b'}]:
            self.assertEqual(self.post(a, '/v1/spending-limits', bad).status_code, 400, bad)
        self.assertEqual(a.get('/v1/spending-limits', secure=True).json()['limits'], self.NONE)
        self.assertEqual(self.new_client().get('/v1/spending-limits', secure=True).status_code, 401)

    def test_the_owner_default_shows_until_the_customer_chooses(self):
        call_command('spend_limits', 'set', daily='15', stdout=self.output)
        a = self.signed('a')
        view = a.get('/v1/spending-limits', secure=True).json()
        self.assertEqual((view['limits']['daily_microusd'], view['chosen']), (15_000_000, False))
        self.post(a, '/v1/spending-limits', {'task': '', 'daily': '', 'period': ''})
        self.assertEqual(a.get('/v1/spending-limits', secure=True).json()['limits'], self.NONE)
        call_command('spend_limits', 'clear', stdout=self.output)
        self.assertIn('No default', self.output.getvalue())
