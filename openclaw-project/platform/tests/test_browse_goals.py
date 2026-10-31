import json
import tempfile
import unittest
from agentai_platform.browse.goals import HISTORY_HEADER, CURRENT_MARKER, goal_parts, instruction_text
from agentai_platform.browse.ladder import render, JevChooser
from agentai_platform.browse.service import BrowseService, BrowseError, Job
from agentai_platform.browse.loop import Policy


def wrapped(current):
    return HISTORY_HEADER + json.dumps([{'role': 'assistant', 'content': 'Old chat interface https://old.example/ ' + 'history ' * 600}]) + CURRENT_MARKER + current


class GoalChecks(unittest.TestCase):
    def test_current_request_is_complete_and_precedes_quoted_context(self):
        current = 'x' * 1400 + '\nUse DoorDash and let me sign in myself.'
        text = instruction_text(wrapped(current))
        self.assertIn(current, text)
        self.assertLess(text.index('Use DoorDash'), text.index('Quoted previous'))
        self.assertIn(current, render(wrapped(current), [], {}, []))

    def test_markers_inside_the_current_request_do_not_split_it(self):
        current = 'Explain this literal delimiter:' + CURRENT_MARKER + 'Keep all of this.'
        self.assertEqual(goal_parts(wrapped(current))[0], current)
        self.assertEqual(goal_parts('plain goal'), ('plain goal', []))
        malformed = HISTORY_HEADER + 'not valid history' + CURRENT_MARKER + 'current'
        self.assertEqual(goal_parts(malformed), (malformed, []))

    def test_jev_receives_the_current_request_even_after_long_chat_history(self):
        current = 'Search DoorDash for spicy food ' + 'extra detail ' * 60 + ' and let me sign in myself'
        def transport(endpoint, body, credential, deadline):
            self.assertIn(current, body['state'])
            self.assertLess(body['state'].index('Search DoorDash'), body['state'].index('Old chat interface'))
            options = list(body['questions']['operation']['criteria'])
            return {'model': 'test', 'answers': {'operation': {'type': 'choice', 'choice': 'done', 'probabilities': {o: 1.0 if o == 'done' else 0.0 for o in options}}}}
        self.assertEqual(JevChooser('unused', 'test', 'unused', transport).choose(wrapped(current), '', []).operation, 'done')

    def test_start_page_uses_current_urls_not_history_urls(self):
        with tempfile.TemporaryDirectory() as root:
            service = BrowseService(spawn=None, root=root)
            job = Job('a', 'a' * 32, wrapped('Use https://www.doordash.com/'), None, 100000, 25, 600)
            self.assertEqual(service._pick_start(job), 'https://www.doordash.com/')
            named = Job('a', 'b' * 32, wrapped('Use DoorDash'), 'https://www.doordash.com/', 100000, 25, 600)       # the tool always names the site
            self.assertEqual(service._pick_start(named), 'https://www.doordash.com/')

    def test_a_task_that_names_no_site_is_refused_instead_of_guessing_one(self):
        with tempfile.TemporaryDirectory() as root:
            service = BrowseService(spawn=None, root=root)
            job = Job('a', 'a' * 32, wrapped('Use DoorDash, not the earlier website https://old.example/'), None, 100000, 25, 600)
            self.assertEqual(service._pick_start(job), 'https://old.example/')                                       # only the current request's own address counts, never one from history
            plain = Job('a', 'b' * 32, 'Use DoorDash', None, 100000, 25, 600)
            with self.assertRaises(BrowseError):
                service._pick_start(plain)

    def test_url_policy_checks_the_actual_host_and_rejects_embedded_credentials(self):
        policy = Policy()
        for url in ['https://user@paypal.com/', 'https://paypal.com./', 'https://www.paypal.com/', 'https://user:pass@example.com/', 'https://example.com:bad/', 'https://example.com/\nnext']:
            self.assertFalse(policy.url_ok(url), url)
        self.assertTrue(policy.url_ok('https://www.doordash.com/'))
