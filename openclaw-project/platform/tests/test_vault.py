import base64
import os
import sqlite3
import tempfile
import unittest

from agentai_platform import vault

SCHEMA = open(os.path.join(os.path.dirname(__file__), '..', 'migrations', '0024_vault.sql')).read()
NOW = 1_800_000_000          # January 2027
CARD = {'number': '4242 4242 4242 4242', 'exp_month': 12, 'exp_year': 2030, 'name': 'A Customer'}
LOGIN = {'username': 'ada@example.com', 'password': 'correct horse battery'}


def ring():
    return vault.Keyring({'k1': bytes(range(32))}, 'k1')


class Store(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:'); self.con.row_factory = sqlite3.Row; self.con.executescript(SCHEMA)

    def test_a_card_round_trips_and_the_database_holds_no_readable_number(self):
        item = vault.add(self.con, ring(), 'acct', 'card', CARD, accepted=True, now=NOW)
        self.assertEqual((item['label'], item['hint']), ('Visa ending 4242', 'Visa ending 4242'))
        dump = b''.join(bytes(v) if isinstance(v, (bytes, bytearray)) else str(v).encode() for r in self.con.execute('SELECT * FROM vault_items') for v in r)
        for leaked in (b'4242424242424242', b'A Customer', b'4242 4242'):
            self.assertNotIn(leaked, dump)
        kind, secret = vault.open_item(self.con, ring(), 'acct', item['id'], now=NOW)
        self.assertEqual((kind, secret['number'], secret['exp_year']), ('card', '4242424242424242', 2030))
        self.assertNotIn('cvv', secret)

    def test_the_security_code_is_refused_not_dropped(self):
        for key in ('cvv', 'CVC', 'security_code'):
            with self.assertRaises(vault.VaultError):
                vault.add(self.con, ring(), 'acct', 'card', {**CARD, key: '123'}, accepted=True, now=NOW)
        self.assertEqual(self.con.execute('SELECT count(*) FROM vault_items').fetchone()[0], 0)

    def test_bad_cards_and_a_missing_notice_are_refused(self):
        for bad in ({**CARD, 'number': '4242424242424241'}, {**CARD, 'number': '123'}, {**CARD, 'exp_month': 13}, {**CARD, 'exp_year': 2020}, {**CARD, 'exp_year': 2090}):
            with self.assertRaises(vault.VaultError, msg=bad):
                vault.add(self.con, ring(), 'acct', 'card', bad, accepted=True, now=NOW)
        with self.assertRaises(vault.VaultError):
            vault.add(self.con, ring(), 'acct', 'card', CARD, accepted=False, now=NOW)
        with self.assertRaises(vault.VaultError):
            vault.add(self.con, ring(), 'acct', 'card', CARD, accepted='yes', now=NOW)

    def test_an_item_opens_only_for_its_owner_and_only_as_stored(self):
        item = vault.add(self.con, ring(), 'acct', 'login', LOGIN, site='https://www.Example.com/signin?x=1', accepted=True, now=NOW)
        self.assertEqual((item['site'], item['hint']), ('example.com', 'ad***@example.com'))
        with self.assertRaises(vault.VaultError):
            vault.open_item(self.con, ring(), 'someone-else', item['id'])
        other = vault.add(self.con, ring(), 'other', 'login', {'username': 'x', 'password': 'y'}, site='example.com', accepted=True, now=NOW)
        row = self.con.execute('SELECT nonce,ciphertext FROM vault_items WHERE id=?', (other['id'],)).fetchone()
        self.con.execute('UPDATE vault_items SET nonce=?,ciphertext=? WHERE id=?', (row['nonce'], row['ciphertext'], item['id']))        # swap another row's sealed data in
        with self.assertRaises(vault.VaultError):
            vault.open_item(self.con, ring(), 'acct', item['id'])
        self.con.execute('UPDATE vault_items SET kind=? WHERE id=?', ('card', other['id']))                                              # change what the row says it is
        with self.assertRaises(vault.VaultError):
            vault.open_item(self.con, ring(), 'other', other['id'])

    def test_a_different_key_cannot_open_and_an_old_key_still_can(self):
        item = vault.add(self.con, ring(), 'acct', 'login', LOGIN, site='example.com', accepted=True, now=NOW)
        with self.assertRaises(vault.VaultError):
            vault.open_item(self.con, vault.Keyring({'k1': bytes(32)}, 'k1'), 'acct', item['id'])
        rotated = vault.Keyring({'k2': bytes([7]) * 32, 'k1': bytes(range(32))}, 'k2')
        self.assertEqual(vault.open_item(self.con, rotated, 'acct', item['id'])[1]['password'], LOGIN['password'])
        self.assertEqual(vault.add(self.con, rotated, 'acct', 'login', LOGIN, site='b.example.com', accepted=True, now=NOW)['id'] != item['id'], True)
        self.assertEqual({r[0] for r in self.con.execute('SELECT kid FROM vault_items')}, {'k1', 'k2'})

    def test_listing_shows_no_secrets_and_logins_are_found_by_site(self):
        vault.add(self.con, ring(), 'acct', 'login', LOGIN, site='shop.example.com', accepted=True, now=NOW)
        vault.add(self.con, ring(), 'acct', 'card', CARD, accepted=True, now=NOW)
        listed = vault.list_items(self.con, 'acct')
        self.assertEqual({k for item in listed for k in item}, {'id', 'kind', 'label', 'site', 'hint', 'last_used_epoch'})
        self.assertEqual(len(vault.logins_for(self.con, 'acct', 'https://www.shop.example.com/cart')), 1); self.assertEqual(vault.logins_for(self.con, 'acct', 'other.example.com'), [])
        self.assertEqual(vault.list_items(self.con, 'nobody'), [])
        vault.delete(self.con, 'acct', listed[0]['id']); self.assertEqual(len(vault.list_items(self.con, 'acct')), 1)

    def test_a_login_needs_a_real_site_and_both_fields(self):
        for kw in ({'site': ''}, {'site': 'localhost'}, {'site': 'not a site'}):
            with self.assertRaises(vault.VaultError, msg=kw):
                vault.add(self.con, ring(), 'acct', 'login', LOGIN, accepted=True, now=NOW, **kw)
        with self.assertRaises(vault.VaultError):
            vault.add(self.con, ring(), 'acct', 'login', {'username': 'a', 'password': ''}, site='example.com', accepted=True, now=NOW)


class KeyFile(unittest.TestCase):
    def write(self, text, mode=0o600):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        path = os.path.join(d.name, 'vault.key'); open(path, 'w').write(text); os.chmod(path, mode); return path

    def test_a_generated_key_loads_and_a_loose_or_bad_file_turns_the_vault_off(self):
        self.assertEqual(vault.Keyring.from_file(self.write(vault.Keyring.generate() + '\n')).current, 'k1')
        for text, mode in ((vault.Keyring.generate(), 0o644), ('k1:short', 0o600), ('', 0o600), ('BAD KID:' + 'A' * 43, 0o600)):
            with self.assertRaises(vault.VaultOff, msg=text):
                vault.Keyring.from_file(self.write(text, mode))
        with self.assertRaises(vault.VaultOff):
            vault.Keyring.from_file('/nonexistent/vault.key')
        with self.assertRaises(vault.VaultOff):
            vault.Keyring.from_file('')


if __name__ == '__main__':
    unittest.main()
