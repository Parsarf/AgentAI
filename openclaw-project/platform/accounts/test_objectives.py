from django.test import TestCase
from .tests import AccountBoundaryTests


class LongJobAndEstimateAPIChecks(TestCase):
    """Long jobs and estimates over HTTP: signed-in only, scoped to the account, validated."""
    setUp = AccountBoundaryTests.setUp
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed

    def test_an_account_sees_only_its_own_long_jobs_and_unknown_ones_are_not_found(self):
        a = self.signed('a')
        listing = a.get('/v1/objectives', secure=True)
        self.assertEqual((listing.status_code, listing.json()), (200, {'objectives': []}))
        self.assertEqual(a.get('/v1/objectives/' + 'f' * 32, secure=True).status_code, 404)
        self.assertEqual(self.post(a, '/v1/objectives/' + 'f' * 32, {'max_turns': '30'}).status_code, 404)
        self.assertEqual(self.post(a, '/v1/objectives/' + 'f' * 32 + '/cancel', {}).status_code, 404)
        self.assertEqual(self.new_client().get('/v1/objectives', secure=True).status_code, 401)

    def test_settings_are_validated_before_anything_is_looked_up(self):
        a = self.signed('a')
        for bad in ({'max_turns': '0'}, {'max_turns': 'many'}, {'max_hours': '9999'}, {'surprise': '1'}, {}):
            self.assertEqual(self.post(a, '/v1/objectives/' + 'f' * 32, bad).status_code, 400, bad)

    def test_an_estimate_is_null_without_history_and_an_unknown_kind_is_refused(self):
        a = self.signed('a')
        got = a.get('/v1/estimates/chat', secure=True)
        self.assertEqual((got.status_code, got.json()), (200, {'estimate': None}))
        self.assertEqual(a.get('/v1/estimates/everything', secure=True).status_code, 400)
        self.assertEqual(self.new_client().get('/v1/estimates/chat', secure=True).status_code, 401)
