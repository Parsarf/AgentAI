import unittest
from agentai_platform import activity
from agentai_platform.events import normalize
from agentai_platform.gateway import NativeGateway

ROWS = [
    {'role': 'user', 'content': 'hi'},
    {'role': 'assistant', 'content': [
        {'type': 'text', 'text': 'Let me look.'},
        {'type': 'toolCall', 'id': 'call_1', 'name': 'web_search', 'arguments': {'query': 'carbon pickleball paddles'}},
        {'type': 'toolCall', 'id': 'call_2', 'name': 'exec', 'arguments': {'command': 'curl -H "Authorization: Bearer abcdefghijklmnop1234" x; API_KEY=hunter2hunter2 ls'}},
        {'type': 'toolCall', 'id': 'call_3', 'name': 'write', 'arguments': {'path': 'app/page.tsx', 'content': 'SECRET FILE BODY'}},
        {'type': 'toolCall', 'id': 'call_4', 'name': 'web_fetch', 'arguments': {'url': 'https://shop.example/p/123?token=abc'}}]},
    {'role': 'toolResult', 'toolCallId': 'call_1', 'content': [{'type': 'text', 'text': 'results...'}]},
    {'role': 'toolResult', 'toolCallId': 'call_2', 'content': [{'type': 'text', 'text': 'ok\nsk-abcdefghijklmnop'}], 'isError': False},
    {'role': 'toolResult', 'toolCallId': 'call_3', 'isError': True, 'content': 'permission denied'},
]


class ActivityChecks(unittest.TestCase):
    def test_extract_shapes_and_status(self):
        items = {i['ref']: i for i in activity.extract(ROWS)}
        self.assertEqual(items['call_1']['category'], 'search')
        self.assertEqual(items['call_1']['detail'], 'carbon pickleball paddles')
        self.assertEqual(items['call_1']['status'], 'done')
        self.assertEqual(items['call_4']['status'], 'running')
        self.assertEqual(items['call_4']['detail'], 'shop.example/p/123')           # no query string / token
        self.assertEqual(items['call_3']['status'], 'failed')
        self.assertEqual(items['call_3']['detail'], 'app/page.tsx')

    def test_secrets_and_file_bodies_never_surface(self):
        blob = repr(activity.extract(ROWS))
        for leak in ('abcdefghijklmnop1234', 'hunter2hunter2', 'sk-abcdefghijklmnop', 'SECRET FILE BODY', 'token=abc'):
            self.assertNotIn(leak, blob)

    def test_output_only_for_commands_or_failures(self):
        items = {i['ref']: i for i in activity.extract(ROWS)}
        self.assertEqual(items['call_1']['output'], '')
        self.assertIn('ok', items['call_2']['output'])
        self.assertEqual(items['call_3']['output'], 'permission denied')

    def test_wrapped_and_housekeeping_tools(self):
        rows = [{'role': 'assistant', 'content': [
            {'type': 'toolCall', 'id': 'a1', 'name': 'tool_search', 'arguments': {'query': 'web search'}},
            {'type': 'toolCall', 'id': 'a2', 'name': 'tool_call', 'arguments': {'id': 'openclaw:core:web_search', 'args': {'query': 'iceland'}}}]},
            {'role': 'toolResult', 'toolCallId': 'a2', 'content': 'x'}]
        items = activity.extract(rows)
        self.assertEqual([(i['ref'], i['category'], i['detail'], i['status']) for i in items], [('a2', 'search', 'iceland', 'done')])

    def test_workspace_paths_are_shortened(self):
        self.assertEqual(activity.describe('exec', {'command': 'cd /home/node/.openclaw/workspace && python3 -m unittest'})[2], 'python3 -m unittest')
        self.assertEqual(activity.describe('write', {'path': '/home/node/.openclaw/workspace/app/page.tsx'})[2], 'app/page.tsx')

    def test_garbage_is_ignored(self):
        self.assertEqual(activity.extract(None), [])
        self.assertEqual(activity.extract([1, 'x', {'role': 'assistant', 'content': [{'type': 'toolCall', 'id': '../x', 'name': 'exec'}]}]), [])

    def test_payload_passes_event_allowlist(self):
        for item in activity.extract(ROWS):
            normalize('activity', item)

    def test_native_gateway_exposes_activity_without_changing_rows(self):
        gw = NativeGateway(lambda m, p: {'hello': {}, 'protocol': 4, 'methods': ['chat.send', 'chat.history', 'chat.abort']} if m == 'hello' else
                           {'kind': 'tail', 'messages': ROWS, 'sessionInfo': {}})
        page = gw.history('abc', None)
        self.assertEqual(len(page['activity']), 4)
        self.assertEqual(page['messages'], [])        # rows without runtime ids are not transcript rows


if __name__ == '__main__':
    unittest.main()
