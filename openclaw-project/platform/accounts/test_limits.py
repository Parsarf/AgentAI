"""The outer request limits must not undercut what a route itself allows (14 November 2026)."""
import json
from django.test import TestCase
from .tests import AccountBoundaryTests


class OuterLimitChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def test_take_over_input_is_not_cut_off_at_thirty_a_minute(self):
        a = self.signed()
        statuses = {self.post(a, '/v1/browse/' + 'a' * 32 + '/control', {'action': 'scroll', 'text': 'down'}).status_code for _ in range(40)}
        self.assertNotIn(429, statuses)                                   # (404: this task has no browser; the point is that the general 30-a-minute limit is not what answers)

    def test_other_writes_keep_the_general_limit(self):
        a = self.signed()
        statuses = [self.post(a, '/v1/browse/' + 'a' * 32 + '/release').status_code for _ in range(35)]
        self.assertIn(429, statuses)

    def test_structured_state_larger_than_8_kb_reaches_its_route(self):
        a = self.signed()
        body = json.dumps({'version': 1, 'state': {'answers': {'note': 'x' * 20000}}})
        big = a.post('/v1/blocks/' + 'b' * 32 + '/state', body, content_type='application/json', secure=True, HTTP_X_CSRFTOKEN=a.cookies['csrftoken'].value if 'csrftoken' in a.cookies else '')
        self.assertNotEqual(big.status_code, 413)
        over = a.post('/v1/account/mcp', json.dumps({'name': 'x' * 9000}), content_type='application/json', secure=True)
        self.assertEqual(over.status_code, 413)                           # everything else keeps the 8 KB ceiling
