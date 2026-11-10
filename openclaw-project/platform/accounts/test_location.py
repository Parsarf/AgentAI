from unittest.mock import patch
from django.test import TestCase
from . import tests as boundary


class LocationHTTPChecks(TestCase):
    setUp = boundary.AccountBoundaryTests.setUp
    new_client = boundary.AccountBoundaryTests.new_client
    signed = boundary.AccountBoundaryTests.signed
    post = boundary.AccountBoundaryTests.post
    # Do not inherit the boundary suite itself; these tests exercise the new routes.
    def test_location_session_csrf_and_account_scope(self):
        with patch('accounts.location.service') as factory:
            factory.return_value.pending.return_value = None
            self.assertEqual(self.new_client().get('/v1/location', secure=True).status_code, 401)
            a = self.signed('a')
            self.assertEqual(a.get('/v1/location', secure=True).json(), {'request': None})
            factory.return_value.pending.assert_called_with('a')
            url = '/v1/location/loc1'
            self.assertEqual(a.post(url, '{}', content_type='application/json', secure=True).status_code, 403)
            factory.return_value.answer.return_value = {'accepted': True, 'status': 'denied'}
            data = {'action': 'respond', 'client_id': 'tab1', 'status': 'denied'}
            response = self.post(a, url, data)
            self.assertEqual(response.status_code, 200)
            factory.return_value.answer.assert_called_with('a', 'loc1', data)
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(self.post(a, url, {**data, 'account_id': 'b'}).status_code, 400)
