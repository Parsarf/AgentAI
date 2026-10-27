import json
import socket
import struct
import time
import unittest

from agentai_platform.genui import data as cards, images
from agentai_platform.genui.images import FetchError, Response
from tests.test_genui import CardFlowChecks, COMPARE


def png(w=400, h=300, animated=False):
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', w, h) + b'\x08\x02\x00\x00\x00' + (b'acTL' if animated else b'') + b'\0' * 20


def jpeg(w=400, h=300):
    return b'\xff\xd8\xff\xe0' + struct.pack('>H', 16) + b'JFIF\0' + b'\0' * 9 + b'\xff\xc0' + struct.pack('>HBHHB', 11, 8, h, w, 3) + b'\0' * 10


def webp_vp8(w=400, h=300):
    return b'RIFF' + b'\0' * 4 + b'WEBP' + b'VP8 ' + b'\0' * 4 + b'\0' * 3 + b'\x9d\x01\x2a' + struct.pack('<HH', w, h) + b'\0' * 8


def webp_vp8l(w=400, h=300):
    return b'RIFF' + b'\0' * 4 + b'WEBP' + b'VP8L' + b'\0' * 4 + b'\x2f' + ((w - 1) | ((h - 1) << 14)).to_bytes(4, 'little') + b'\0' * 8


def webp_vp8x(w=400, h=300, animated=False):
    return b'RIFF' + b'\0' * 4 + b'WEBP' + b'VP8X' + b'\0' * 4 + bytes([0x02 if animated else 0]) + b'\0' * 3 + (w - 1).to_bytes(3, 'little') + (h - 1).to_bytes(3, 'little') + b'\0' * 8


PUBLIC = '93.184.216.34'


def resolver_for(table):
    def resolve(host, port, type=None):
        if host not in table:
            raise OSError('nxdomain')
        return [(2, 1, 6, '', (ip, port)) for ip in table[host]]
    return resolve


def page(*meta):
    return '<html><head>' + ''.join(meta) + '</head><body></body></html>'


class Web:
    """A fake transport: url -> Response, with a record of what was requested."""
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url, ip, *, max_bytes, timeout, headers, deadline):
        self.calls.append((url, ip))
        r = self.pages.get(url)
        if r is None:
            return Response(404, {}, b'')
        return r if isinstance(r, Response) else Response(200, {'content-type': 'text/html'}, r if isinstance(r, bytes) else r.encode())


class ResolveChecks(unittest.TestCase):
    def test_private_and_special_addresses_are_refused(self):
        for ip in ['10.0.0.5', '192.168.1.1', '127.0.0.1', '169.254.169.254', '100.64.0.1', '172.16.0.1', '0.0.0.0', '::1', 'fe80::1', 'fc00::1', '::ffff:10.0.0.1', '::ffff:127.0.0.1']:
            with self.assertRaises(FetchError, msg=ip):
                images.resolve_public('x.test', 443, resolver_for({'x.test': [ip]}))

    def test_public_address_is_returned_and_mixed_answers_are_refused(self):
        self.assertEqual(images.resolve_public('x.test', 443, resolver_for({'x.test': [PUBLIC]})), PUBLIC)
        self.assertEqual(images.resolve_public('x.test', 443, resolver_for({'x.test': ['::ffff:93.184.216.34']})), PUBLIC)
        with self.assertRaises(FetchError):
            images.resolve_public('x.test', 443, resolver_for({'x.test': [PUBLIC, '10.0.0.1']}))     # rebinding-style mixed answer
        with self.assertRaises(FetchError):
            images.resolve_public('missing.test', 443, resolver_for({}))
        with self.assertRaises(FetchError):
            images.resolve_public('', 443, resolver_for({}))


class FetcherChecks(unittest.TestCase):
    def fetcher(self, pages, table=None):
        web = Web(pages)
        table = table or {'shop.test': [PUBLIC], 'cdn.test': [PUBLIC], 'internal.test': ['10.0.0.9']}
        return images.SafeFetcher(resolver_for(table), web), web

    def get(self, f, url):
        return f.get(url, accept='text/html', max_bytes=1000, deadline=time.monotonic() + 5)

    def test_success_returns_final_url_type_and_body(self):
        f, web = self.fetcher({'https://shop.test/p': '<html></html>'})
        final, kind, body, truncated = self.get(f, 'https://shop.test/p')
        self.assertEqual((final, kind, body, truncated), ('https://shop.test/p', 'text/html', b'<html></html>', False))
        self.assertEqual(web.calls, [('https://shop.test/p', PUBLIC)])                  # connected to the address that was checked

    def test_unacceptable_urls_are_refused_before_any_request(self):
        f, web = self.fetcher({})
        for url in ['ftp://shop.test/x', 'file:///etc/passwd', 'https://user:pw@shop.test/', 'https://shop.test:8443/', 'http://shop.test:22/', 'https://shop.test:abc/',
                    'https://internal.test/', 'http://127.0.0.1/', 'http://[::1]/', 'http://169.254.169.254/latest/meta-data/', 'https:///nohost']:
            with self.assertRaises(FetchError, msg=url):
                self.get(f, url)
        self.assertEqual(web.calls, [])

    def test_redirects_are_followed_and_every_hop_is_rechecked(self):
        f, web = self.fetcher({'https://shop.test/a': Response(302, {'location': '/b'}, b''), 'https://shop.test/b': 'ok'})
        self.assertEqual(self.get(f, 'https://shop.test/a')[2], b'ok')
        f, web = self.fetcher({'https://shop.test/a': Response(302, {'location': 'http://internal.test/secret'}, b'')})
        with self.assertRaises(FetchError):
            self.get(f, 'https://shop.test/a')
        self.assertEqual(len(web.calls), 1)
        f, web = self.fetcher({'https://shop.test/a': Response(302, {'location': 'http://169.254.169.254/'}, b'')})
        with self.assertRaises(FetchError):
            self.get(f, 'https://shop.test/a')

    def test_redirect_loops_and_error_statuses(self):
        f, _ = self.fetcher({'https://shop.test/a': Response(302, {'location': '/a'}, b'')})
        with self.assertRaises(FetchError):
            self.get(f, 'https://shop.test/a')
        f, _ = self.fetcher({'https://shop.test/a': Response(500, {}, b'')})
        with self.assertRaises(FetchError):
            self.get(f, 'https://shop.test/a')
        f, _ = self.fetcher({})
        with self.assertRaises(FetchError):
            self.get(f, 'https://shop.test/missing')

    def test_deadline_already_passed(self):
        f, web = self.fetcher({'https://shop.test/a': 'ok'})
        with self.assertRaises(FetchError):
            f.get('https://shop.test/a', accept='*/*', max_bytes=10, deadline=time.monotonic() - 1)
        self.assertEqual(web.calls, [])


class ImageChecks(unittest.TestCase):
    def test_formats_and_sizes_are_read_from_the_bytes(self):
        self.assertEqual(images.image_info(png(400, 300)), ('image/png', 400, 300))
        self.assertEqual(images.image_info(jpeg(640, 480)), ('image/jpeg', 640, 480))
        self.assertEqual(images.image_info(webp_vp8(500, 400)), ('image/webp', 500, 400))
        self.assertEqual(images.image_info(webp_vp8l(500, 400)), ('image/webp', 500, 400))
        self.assertEqual(images.image_info(webp_vp8x(500, 400)), ('image/webp', 500, 400))

    def test_animated_and_foreign_files_are_rejected(self):
        for data in [png(animated=True), webp_vp8x(animated=True), b'GIF89a' + b'\0' * 40, b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', b'<html>no</html>', b'', b'\xff\xd8\xff', b'\x89PNG']:
            self.assertIsNone(images.image_info(data), data[:12])

    def test_usable_rejects_icons_banners_and_giants(self):
        self.assertTrue(images.usable(('image/png', 400, 300)))
        self.assertFalse(images.usable(None))
        self.assertFalse(images.usable(('image/png', 16, 16)))                    # icon or tracking pixel
        self.assertFalse(images.usable(('image/png', 149, 400)))
        self.assertFalse(images.usable(('image/png', 1600, 200)))                 # thin banner
        self.assertFalse(images.usable(('image/png', 7000, 6000)))                # absurdly large
        self.assertTrue(images.usable(('image/png', 150, 150)))


class CandidateChecks(unittest.TestCase):
    def test_order_prefers_secure_og_then_og_then_product_then_twitter(self):
        html = page('<meta property="og:image" content="/img/og.jpg">', '<meta property="og:image:secure_url" content="https://cdn.test/secure.jpg">',
                    '<meta name="twitter:image" content="https://cdn.test/tw.jpg">',
                    '<script type="application/ld+json">{"@type":"Product","image":"https://cdn.test/ld.jpg"}</script>')
        self.assertEqual(images.candidate_images(html, 'https://shop.test/p/1'),
                         ['https://cdn.test/secure.jpg', 'https://shop.test/img/og.jpg', 'https://cdn.test/ld.jpg'])         # capped at three

    def test_json_ld_shapes(self):
        for blob in ['{"@graph":[{"@type":"Product","image":["https://c.test/a.jpg"]}]}', '[{"@type":["Thing","Product"],"image":{"url":"https://c.test/a.jpg"}}]',
                     '{"@type":"Product","image":[{"url":"https://c.test/a.jpg"}]}']:
            html = page('<script type="application/ld+json">' + blob + '</script>')
            self.assertEqual(images.candidate_images(html, 'https://shop.test/'), ['https://c.test/a.jpg'], blob)
        self.assertEqual(images.candidate_images(page('<script type="application/ld+json">{"@type":"Organization","image":"https://c.test/x.jpg"}</script>'), 'https://shop.test/'), [])
        self.assertEqual(images.candidate_images(page('<script type="application/ld+json">{not json</script>'), 'https://shop.test/'), [])

    def test_twitter_and_image_src_fallbacks(self):
        self.assertEqual(images.candidate_images(page('<meta name="twitter:image" content="https://c.test/t.jpg">'), 'https://shop.test/'), ['https://c.test/t.jpg'])
        self.assertEqual(images.candidate_images(page('<link rel="image_src" href="/i.jpg">'), 'https://shop.test/x'), ['https://shop.test/i.jpg'])

    def test_generic_unsafe_and_duplicate_pictures_are_filtered(self):
        html = page('<meta property="og:image" content="https://c.test/logo.png">', '<meta property="og:image:secure_url" content="https://c.test/a.svg">',
                    '<meta name="twitter:image" content="https://c.test/a.gif">', '<meta name="twitter:image:src" content="javascript:alert(1)">',
                    '<link rel="image_src" href="https://c.test/ok.jpg">', '<link rel="image_src" href="https://c.test/ok.jpg">')
        self.assertEqual(images.candidate_images(html, 'https://shop.test/'), ['https://c.test/ok.jpg'])

    def test_garbage_html_gives_nothing(self):
        self.assertEqual(images.candidate_images('', 'https://shop.test/'), [])
        self.assertEqual(images.candidate_images('<<<>>><meta', 'https://shop.test/'), [])


class MatchChecks(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(images.matches('Selkirk Vanguard Power Air', 'Selkirk Vanguard Power Air Invikta pickleball paddle'))
        self.assertFalse(images.matches('Selkirk Vanguard Power Air', 'Garden hose reel'))
        self.assertFalse(images.matches('', 'anything'))
        self.assertFalse(images.matches('The New Pro', 'the new pro'))               # only stop words: nothing to match on


class BraveChecks(unittest.TestCase):
    def brave(self, payload, key='k'):
        calls = []

        def transport(url, headers, timeout):
            calls.append((url, headers))
            if isinstance(payload, Exception):
                raise payload
            return payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return images.BraveImages(lambda: key, transport), calls

    def test_no_key_means_no_request(self):
        b, calls = self.brave({'results': []}, key='')
        self.assertEqual(b.search('x'), [])
        self.assertEqual(calls, [])

    def test_parses_dict_and_string_thumbnails_and_drops_unsafe_ones(self):
        b, calls = self.brave({'results': [{'title': 'A', 'url': 'https://s.test/a', 'thumbnail': {'src': 'https://t.test/a.jpg'}},
                                           {'title': 'B', 'url': 'https://s.test/b', 'thumbnail': 'https://t.test/b.jpg'},
                                           {'title': 'C', 'thumbnail': {'src': 'http://t.test/c.jpg'}}, {'title': 'D'}, 'junk', {'thumbnail': {'src': 5}}]})
        got = b.search('paddle')
        self.assertEqual([(c.url, c.title, c.page) for c in got], [('https://t.test/a.jpg', 'A', 'https://s.test/a'), ('https://t.test/b.jpg', 'B', 'https://s.test/b')])
        self.assertEqual(calls[0][1]['X-Subscription-Token'], 'k')
        self.assertIn('safesearch=strict', calls[0][0])

    def test_failures_give_nothing(self):
        for payload in [OSError('down'), b'not json', {'results': 'oops'}, [1, 2]]:
            self.assertEqual(self.brave(payload)[0].search('x'), [])

    def test_key_from_file(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'key')
            with open(p, 'w') as handle:
                handle.write(' secret \n')
            self.assertEqual(images.key_from_file(p)(), 'secret')
            self.assertEqual(images.key_from_file(os.path.join(d, 'none'))(), '')


class EnrichChecks(CardFlowChecks):
    """Reuses the genui flow fixture (a real Store with two accounts)."""

    def web(self, pages):
        web = Web(pages)
        table = {h: [PUBLIC] for h in ('shop.test', 'cdn.test', 'example.com', 'search.test', 't.test')}
        return web, images.SafeFetcher(resolver_for(table), web)

    def card_images(self, pages, brave=None, **kw):
        web, fetcher = self.web(pages)
        return web, images.CardImages(self.store, fetcher=fetcher, brave=brave, clock=lambda: self.now, **kw)

    def spec(self, *items):
        return {'schemaVersion': '1.0', 'type': 'comparison', 'title': 'Pick', 'items': list(items), 'bestIndex': 0}

    def test_image_store_is_scoped_and_idempotent(self):
        s = images.ImageStore(self.store, clock=lambda: self.now)
        one = s.put('a', png(), 'image/png', 400, 300, 'shop.test')
        self.assertEqual(one, s.put('a', png(), 'image/png', 400, 300, 'shop.test'))
        self.assertRegex(one, r'^[a-f0-9]{32}$')
        self.assertEqual(s.read('a', one)['mime'], 'image/png')
        self.assertIsNone(s.read('b', one))                                    # another account cannot see it
        self.assertEqual(len(self.rows('SELECT 1 FROM card_images')), 1)

    def test_page_picture_is_found_stored_and_referenced(self):
        web, ci = self.card_images({'https://shop.test/p': page('<meta property="og:image" content="https://cdn.test/p.png">'), 'https://cdn.test/p.png': Response(200, {'content-type': 'image/png'}, png(800, 600))})
        spec = self.spec({'name': 'Paddle', 'link': 'https://shop.test/p'}, {'name': 'No link'})
        before = json.loads(json.dumps(spec))
        out = ci.enrich('a', spec)
        self.assertEqual(spec, before)                                           # the validated spec is not mutated
        img = out['items'][0]['image']
        self.assertEqual((img['w'], img['h'], img['source']), (800, 600, 'shop.test'))
        self.assertNotIn('image', out['items'][1])
        self.assertEqual(images.ImageStore(self.store).read('a', img['id'])['mime'], 'image/png')

    def test_places_and_products_get_pictures_too_but_other_cards_are_left_alone(self):
        pic = {'https://shop.test/p': page('<meta property="og:image" content="https://cdn.test/p.png">'), 'https://cdn.test/p.png': Response(200, {'content-type': 'image/png'}, png(800, 600))}
        for kind in ('places', 'products'):
            _, ci = self.card_images(dict(pic))
            out = ci.enrich('a', {'schemaVersion': '1.0', 'type': kind, 'title': 't', 'items': [{'name': 'A', 'link': 'https://shop.test/p'}, {'name': 'B'}]})
            self.assertIn('image', out['items'][0], kind); self.assertNotIn('image', out['items'][1])
        web, ci = self.card_images(dict(pic))
        steps = {'schemaVersion': '1.0', 'type': 'steps', 'title': 't', 'items': [{'title': 'x'}]}
        self.assertEqual(ci.enrich('a', steps), steps); self.assertEqual(web.calls, [])                    # nothing fetched for a card without pictures

    def test_failures_are_per_option_and_never_raise(self):
        pages = {'https://shop.test/ok': page('<meta property="og:image" content="https://cdn.test/ok.jpg">'), 'https://cdn.test/ok.jpg': Response(200, {}, jpeg()),
                 'https://shop.test/tiny': page('<meta property="og:image" content="https://cdn.test/tiny.png">'), 'https://cdn.test/tiny.png': Response(200, {}, png(20, 20)),
                 'https://shop.test/gif': page('<meta property="og:image" content="https://cdn.test/a.png">'), 'https://cdn.test/a.png': Response(200, {}, b'GIF89a' + b'\0' * 50)}
        web, ci = self.card_images(pages)
        spec = self.spec({'name': 'A', 'link': 'https://shop.test/ok'}, {'name': 'B', 'link': 'https://shop.test/tiny'}, {'name': 'C', 'link': 'https://shop.test/gif'},
                         {'name': 'D', 'link': 'http://127.0.0.1/admin'}, {'name': 'E', 'link': 'https://shop.test/404'})
        out = ci.enrich('a', spec)
        self.assertEqual([('image' in i) for i in out['items']], [True, False, False, False, False])
        self.assertNotIn(('http://127.0.0.1/admin', PUBLIC), web.calls)

    def test_oversized_image_is_rejected(self):
        big = Response(200, {}, png(), truncated=True)
        _, ci = self.card_images({'https://shop.test/p': page('<meta property="og:image" content="https://cdn.test/p.png">'), 'https://cdn.test/p.png': big})
        self.assertNotIn('image', ci.enrich('a', self.spec({'name': 'A', 'link': 'https://shop.test/p'}, {'name': 'B'}))['items'][0])

    def test_brave_fallback_only_for_matching_results(self):
        payload = {'results': [{'title': 'Garden hose', 'url': 'https://search.test/1', 'thumbnail': {'src': 'https://t.test/wrong.png'}},
                               {'title': 'Selkirk Vanguard paddle review', 'url': 'https://search.test/2', 'thumbnail': {'src': 'https://t.test/right.png'}}]}
        brave = images.BraveImages(lambda: 'k', lambda url, headers, timeout: json.dumps(payload).encode())
        web, ci = self.card_images({'https://t.test/wrong.png': Response(200, {}, png(300, 300)), 'https://t.test/right.png': Response(200, {}, png(500, 500))}, brave=brave)
        out = ci.enrich('a', self.spec({'name': 'Selkirk Vanguard'}, {'name': 'Zzz Qqq Product'}))
        self.assertEqual(out['items'][0]['image']['w'], 500)
        self.assertEqual(out['items'][0]['image']['source'], 'search.test')
        self.assertNotIn('image', out['items'][1])
        self.assertNotIn('https://t.test/wrong.png', [c[0] for c in web.calls])

    def test_no_key_means_no_search_fallback(self):
        brave = images.BraveImages(lambda: '', lambda *a: self.fail('must not be called'))
        _, ci = self.card_images({}, brave=brave)
        self.assertNotIn('image', ci.enrich('a', self.spec({'name': 'Selkirk Vanguard'}, {'name': 'B'}))['items'][0])

    def test_other_card_types_are_untouched_and_budget_is_respected(self):
        _, ci = self.card_images({})
        table = {'type': 'table', 'x': 1}
        self.assertIs(ci.enrich('a', table), table)

        class Slow:
            def get(self, *a, **k):
                time.sleep(1.5)
                raise FetchError('slow')
        ci = images.CardImages(self.store, fetcher=Slow(), budget=0.2)
        t = time.monotonic()
        out = ci.enrich('a', self.spec({'name': 'A', 'link': 'https://shop.test/p'}, {'name': 'B'}))
        self.assertLess(time.monotonic() - t, 1.0)
        self.assertNotIn('image', out['items'][0])

    def test_model_cannot_supply_an_image(self):
        spec = json.loads(json.dumps(COMPARE))
        spec['items'][0]['image'] = {'id': 'a' * 32, 'w': 1, 'h': 1, 'source': 'x'}
        with self.assertRaises(Exception):
            cards.validate_data(spec)
        fence = '```lumina\n' + json.dumps(spec) + '\n```'
        self.assertEqual(cards.extract('hi\n' + fence)[1], [])

    def test_from_environment_is_off_by_default(self):
        self.assertIsNone(images.from_environment(self.store, env={}))
        self.assertIsNone(images.from_environment(self.store, env={'AGENTAI_CARD_IMAGES': '0'}))
        on = images.from_environment(self.store, env={'AGENTAI_CARD_IMAGES': '1'})
        self.assertIsNone(on.brave)
        self.assertIsNotNone(images.from_environment(self.store, env={'AGENTAI_CARD_IMAGES': '1', 'AGENTAI_BRAVE_IMAGE_KEY_FILE': '/nope'}).brave)

    # -- through the real answer flow ---------------------------------------------------------------------------
    def answer(self, spec):
        self.chat.send(self.a, conversation_id='c-a', message='Best pickleball rackets please', key='t1', mode='text')
        self.gw.replies = ['Here you go.\n```lumina\n' + json.dumps(spec) + '\n```']
        self.assertEqual(self.worker().tick(), {'ran': 1, 'finished': True})
        return [b for b in self.chat.blocks.list(self.a, 'c-a') if b['kind'] == 'comparison']

    def test_flow_attaches_a_stored_picture_to_the_saved_card(self):
        _, ci = self.card_images({'https://example.com': page('<meta property="og:image" content="https://cdn.test/p.png">'), 'https://cdn.test/p.png': Response(200, {}, png())})
        self.chat.blocks.images = ci
        (card,) = self.answer(COMPARE)
        self.assertNotIn('image', card['spec']['items'][0])
        img = card['spec']['items'][1]['image']
        self.assertIsNotNone(images.ImageStore(self.store).read('a', img['id']))
        self.assertIsNone(images.ImageStore(self.store).read('b', img['id']))

    def test_flow_without_pictures_still_gives_a_clean_card(self):
        for ci in (None, self.card_images({})[1]):
            self.chat.blocks.images = ci
            (card,) = self.answer(COMPARE)
            self.assertTrue(all('image' not in i for i in card['spec']['items']))
            agent = [m for m in self.chat.messages(self.a, 'c-a')['messages'] if m['provenance'] == 'agent'][-1]
            self.assertEqual(agent['content'], 'Here you go.')
            break

    def test_fetching_happens_with_no_write_transaction_open(self):
        outer = self

        class Probe:
            def enrich(self, account_id, spec):
                with outer.store.connect() as con:                              # would block (database is locked) if attach_cards held a write lock
                    con.execute('BEGIN IMMEDIATE')
                    con.execute('ROLLBACK')
                return spec
        self.chat.blocks.images = Probe()
        self.assertEqual(len(self.answer(COMPARE)), 1)

    def test_message_changed_while_fetching_inserts_nothing(self):
        outer = self

        class Editor:
            def enrich(self, account_id, spec):
                with outer.store.connect() as con:
                    con.execute("UPDATE chat_messages SET content='edited' WHERE provenance='agent'")
                return spec
        self.chat.blocks.images = Editor()
        self.assertEqual(self.answer(COMPARE), [])


# EnrichChecks inherits CardFlowChecks' own tests; run only this class's own checks plus the inherited fixture
for _name in [n for n in dir(CardFlowChecks) if n.startswith('test_')]:
    setattr(EnrichChecks, _name, None)

class PreferIpv4(unittest.TestCase):
    def test_an_ipv4_address_is_chosen_when_the_name_has_both_kinds(self):
        both = lambda host, port, type=None: [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2606:4700::6812:182e', 443, 0, 0)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('104.18.24.46', 443))]
        self.assertEqual(images.resolve_public('shop.example', 443, resolver=both), '104.18.24.46')
        only6 = lambda host, port, type=None: [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2606:4700::6812:182e', 443, 0, 0))]
        self.assertEqual(images.resolve_public('shop.example', 443, resolver=only6), '2606:4700::6812:182e')
        private = lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('104.18.24.46', 443)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 443))]
        with self.assertRaises(images.FetchError): images.resolve_public('shop.example', 443, resolver=private)          # one private address still refuses the whole name


if __name__ == '__main__':
    unittest.main()
