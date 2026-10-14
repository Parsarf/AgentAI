import json
import tempfile
import unittest
from unittest.mock import Mock
from agentai_platform.browse.goals import HISTORY_HEADER, CURRENT_MARKER, goal_parts, instruction_text
from agentai_platform.browse.ladder import render, JevChooser, Refused
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
            return {'model': 'test', 'answers': {'action': {'type': 'choice', 'choice': 'stop', 'probabilities': {'stop': 1, 'escalate': 0, 'no_valid_action': 0}}}}
        JevChooser('unused', 'test', 'unused', transport).choose(wrapped(current), '', [])

    def test_start_page_uses_current_urls_not_history_urls(self):
        with tempfile.TemporaryDirectory() as root:
            service = BrowseService(spawn=None, llm_for=None, root=root)
            model = Mock(side_effect=AssertionError('No model call should be needed'))
            job = Job('a', 'a' * 32, wrapped('Use https://www.doordash.com/'), None, 100000, 25, 600)
            self.assertEqual(service._pick_start(job, model), 'https://www.doordash.com/')
            model.assert_not_called()

    def test_named_site_and_long_request_reach_start_picker_and_are_budgeted(self):
        with tempfile.TemporaryDirectory() as root:
            service = BrowseService(spawn=None, llm_for=None, root=root)
            current = 'x' * 800 + ' Use DoorDash, not the earlier website.'
            def model(tier, system, text):
                self.assertIn(current, text)
                return {'text': 'https://www.doordash.com/', 'cost_microusd': 1000}
            job = Job('a', 'a' * 32, wrapped(current), None, 100000, 25, 600)
            self.assertEqual(service._pick_start(job, model), 'https://www.doordash.com/')
            self.assertEqual(job.calls, 1); self.assertEqual(job.cost, 1000)
            limited = Job('a', 'b' * 32, 'Use DoorDash', None, 0, 25, 600)
            with self.assertRaises(Refused): service._pick_start(limited, model)

    def test_failed_start_picker_does_not_silently_open_bing(self):
        with tempfile.TemporaryDirectory() as root:
            service = BrowseService(spawn=None, llm_for=None, root=root)
            job = Job('a', 'a' * 32, 'Use DoorDash', None, 100000, 25, 600)
            with self.assertRaises(BrowseError):
                service._pick_start(job, lambda *args: {'text': 'No suitable URL', 'cost_microusd': 1000})

    def test_url_policy_checks_the_actual_host_and_rejects_embedded_credentials(self):
        policy = Policy()
        for url in ['https://user@paypal.com/', 'https://paypal.com./', 'https://www.paypal.com/', 'https://user:pass@example.com/', 'https://example.com:bad/', 'https://example.com/\nnext']:
            self.assertFalse(policy.url_ok(url), url)
        self.assertTrue(policy.url_ok('https://www.doordash.com/'))
