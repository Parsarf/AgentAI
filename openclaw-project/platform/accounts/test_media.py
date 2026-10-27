import struct
from django.db import connection
from django.test import TestCase
from .tests import AccountBoundaryTests

PNG = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 400, 300) + b'\x08\x02\x00\x00\x00' + b'\0' * 20
IMAGE_ID = 'ab' * 16


class MediaChecks(TestCase):
    """Pictures on comparison cards: served only to the account that owns them, never runnable."""
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed

    def setUp(self):
        AccountBoundaryTests.setUp(self)
        with connection.cursor() as c:
            c.execute("INSERT INTO card_images(account_id,id,mime,width,height,source_host,body,created_epoch) VALUES ('a',%s,'image/png',400,300,'shop.test',%s,1)", [IMAGE_ID, PNG])

    def test_owner_gets_the_picture_with_locked_down_headers(self):
        r = self.signed('a').get(f'/v1/media/{IMAGE_ID}', secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PNG)
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertEqual(r['Content-Security-Policy'], "default-src 'none'; sandbox")
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertIn('private', r['Cache-Control']); self.assertIn('immutable', r['Cache-Control'])

    def test_other_accounts_picture_looks_like_one_that_does_not_exist(self):
        c = self.signed('b')
        other = c.get(f'/v1/media/{IMAGE_ID}', secure=True)
        missing = c.get('/v1/media/' + 'cd' * 16, secure=True)
        self.assertEqual(other.status_code, 404)
        self.assertEqual((other.status_code, other.json()), (missing.status_code, missing.json()))

    def test_malformed_ids_and_anonymous_requests_get_nothing(self):
        c = self.signed('a')
        for bad in ['short', 'AB' * 16, 'zz' * 16, 'ab' * 17, '..%2F..%2Fetc']:
            self.assertEqual(c.get(f'/v1/media/{bad}', secure=True).status_code, 404, bad)
        r = self.new_client().get(f'/v1/media/{IMAGE_ID}', secure=True)
        self.assertIn(r.status_code, (401, 403))
        self.assertNotEqual(r.content, PNG)

    def test_only_get_is_allowed(self):
        c = self.signed('a')
        self.assertEqual(self.post(c, f'/v1/media/{IMAGE_ID}', {}).status_code, 405)
