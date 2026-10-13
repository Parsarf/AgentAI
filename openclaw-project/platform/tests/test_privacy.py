import unittest
from agentai_platform.privacy import scrub
from agentai_platform.routing.classifier import sanitize


class ScrubChecks(unittest.TestCase):
    def test_personal_and_credential_data_removed(self):
        text = ('Email jane.doe@example.com or call +1 (415) 555-0142 / 020 7946 0958. Card 4111 1111 1111 1111, SSN 123-45-6789, '
                'IBAN DE89370400440532013000. Ship to 221 Baker Street. Server 10.1.2.3. https://user:hunter2@host.example/x '
                'Authorization: Bearer abcdefghijklmnop1234 sk-abcdefghijklmnopqrstuv api_key=SECRETVALUE '
                'token ' + 'a1' * 30)
        out = scrub(text)
        for leak in ('jane.doe', '555-0142', '7946 0958', '4111', '123-45-6789', 'DE8937', 'Baker', '10.1.2.3', 'hunter2', 'abcdefghijklmnop1234',
                     'sk-abcdef', 'SECRETVALUE', 'a1a1a1a1a1a1a1a1'):
            self.assertNotIn(leak, out, leak)

    def test_ordinary_requests_survive(self):
        text = 'Find the cheapest carbon pickleball paddle under $120 and compare 3 options in 2026.'
        self.assertEqual(scrub(text), text)

    def test_classifier_uses_the_same_scrubber(self):
        self.assertNotIn('jane@example.com', sanitize('mail jane@example.com 4111 1111 1111 1111'))
        self.assertLessEqual(len(sanitize('x ' * 5000)), 2000)


if __name__ == '__main__':
    unittest.main()
