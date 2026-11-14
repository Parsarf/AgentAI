"""The assistant's display tool: visuals are checked before the customer sees anything, belong to the task that asked, and follow the customer's answer style."""
import json
import unittest

from agentai_platform.genui.document import registry
from agentai_platform.genui.store import BlockStore
from agentai_platform.security import Principal
from agentai_platform.show_tool import CORE_COMPONENTS, MAX_PER_TASK, NAME, ShowTools
from agentai_platform.tool_relay import Relay
from tests.test_file_delivery import Base

DATA = {'sales': {'columns': [{'id': 'month', 'label': 'Month'}, {'id': 'revenue', 'label': 'Revenue', 'type': 'currency'}],
                  'rows': [{'month': m, 'revenue': v} for m, v in (('Jan', 1200), ('Feb', 1350), ('Mar', 1500), ('Apr', 1480), ('May', 1710))]}}
CHART = {'id': 'trend', 'type': 'line_chart', 'dataRef': 'sales', 'props': {'title': 'Revenue', 'xKey': 'month', 'series': [{'key': 'revenue', 'label': 'Revenue'}]}}
TABLE = {'id': 'rows', 'type': 'table', 'dataRef': 'sales', 'props': {'title': 'Sales'}}
BUTTONS = {'id': 'next', 'type': 'button_group', 'props': {'title': 'Next', 'buttons': [{'id': 'go', 'label': 'Show details', 'action': {'kind': 'agent.request', 'message': 'Show the details'}}]}}


class ShowToolChecks(Base):
    def setUp(self):
        super().setUp()
        self.tools = ShowTools(self.store, clock=lambda: 2000000000)
        self.style('interactive')

    def style(self, ui, account='a', mode=None):
        with self.store.connect() as con:
            con.execute('UPDATE customer_requests SET context_json=? WHERE account_id=?', (json.dumps({'ui': ui, **({'mode': mode} if mode else {})}) if ui else None, account))

    def show(self, blocks, datasets=None, account='a', request='t-a'):
        return self.tools.call(account, {'blocks': blocks, **({'datasets': datasets} if datasets is not None else {})}, name=NAME, request_id=request)

    def stored(self, account='a'):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute('SELECT conversation_id,anchor_message_id,kind,spec_json,source_request_id,position FROM data_blocks WHERE account_id=? ORDER BY position', (account,)).fetchall()]

    def test_a_valid_visual_is_stored_for_the_task_and_attached_to_the_reply_when_it_ends(self):
        text, bad = self.show([CHART, TABLE], DATA)
        self.assertFalse(bad); self.assertIn('line_chart, table', text)
        row = self.stored()[0]
        self.assertEqual((row['conversation_id'], row['kind'], row['source_request_id'], row['anchor_message_id']), ('c-a', 'document', 't-a', None))      # shown at once, at the end of the chat
        spec = json.loads(row['spec_json'])
        self.assertEqual((spec['type'], [b['id'] for b in spec['blocks']], list(spec['datasets'])), ('document', ['trend', 'rows'], ['sales']))
        self.assertEqual(self.stored('b'), [])
        with self.store.connect() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES ('a','c-a','t-a','agent','Revenue is rising.')")
            reply = con.execute("SELECT id FROM chat_messages WHERE account_id='a'").fetchone()[0]
        blocks = BlockStore(self.store, clock=lambda: 2000000000)
        self.assertEqual(blocks.anchor_shown('a', 'c-a', 't-a'), 1)
        self.assertEqual(self.stored()[0]['anchor_message_id'], reply)
        self.assertEqual(blocks.anchor_shown('a', 'c-a', 't-a'), 1)                         # safe to run again
        listed = blocks.list(Principal('a', 'actor-a', 'customer'), 'c-a')
        self.assertEqual([(b['kind'], b['anchor_message_id']) for b in listed], [('document', reply)])

    def test_a_wrong_block_shows_nothing_and_says_which_block_and_why(self):
        text, bad = self.show([CHART, {'id': 'rows', 'type': 'table', 'dataRef': 'missing', 'props': {'title': 'T'}}, {'id': 'x', 'type': 'iframe', 'props': {'src': 'https://evil.example'}},
                               {'id': 'trend', 'type': 'callout', 'props': {'content': 'again'}}, 'not a block'], DATA)
        self.assertTrue(bad)
        for must in ('Nothing was shown', 'block "rows" (table): dataRef "missing" does not exist', 'block "x" (iframe)', 'block "trend": this id is used twice', 'block 5', 'lumina-show skill'):
            self.assertIn(must, text)
        self.assertNotIn('block "trend" (line_chart)', text)                                # the correct block is not blamed
        self.assertEqual(self.stored(), [])
        text, bad = self.show([TABLE], {'sales': {'columns': [], 'rows': []}})
        self.assertTrue(bad); self.assertIn('dataset "sales"', text)
        for arguments in ({}, {'blocks': 'x'}, {'blocks': []}, {'blocks': [CHART], 'datasets': []}, {'blocks': [CHART], 'extra': 1}, 'x'):
            text, bad = self.tools.call('a', arguments, name=NAME, request_id='t-a')
            self.assertTrue(bad, arguments); self.assertIn('Nothing was shown', text)
        self.assertEqual(self.stored(), [])

    def test_the_customers_answer_style_decides_what_may_be_shown(self):
        for ui, mode in ((None, None), ('basic', None), ('interactive', 'text')):                   # plain answers, another surface, or Text mode
            self.style(ui, mode=mode)
            text, bad = self.show([CHART], DATA)
            self.assertTrue(bad); self.assertIn('plain answers', text); self.assertIn('as text', text)
        self.style('medium')
        text, bad = self.show([CHART, BUTTONS], DATA)
        self.assertTrue(bad); self.assertIn('block "next" (button_group): buttons and follow-ups need the interactive answer style', text)
        self.assertFalse(self.show([CHART], DATA)[1])
        self.style('interactive')
        self.assertFalse(self.show([BUTTONS])[1])
        self.assertEqual(len(self.stored()), 2)

    def test_it_only_acts_for_the_task_that_called_and_within_its_limits(self):
        self.assertTrue(self.tools.call('a', {'blocks': [CHART], 'datasets': DATA}, name=NAME, request_id=None)[1])
        self.assertTrue(self.show([CHART], DATA, request='t-b')[1])                         # another account's task
        self.assertTrue(self.tools.call('a', {'blocks': [CHART], 'datasets': DATA}, lambda: True, name=NAME, request_id='t-a')[1])
        self.assertTrue(ShowTools(self.store, enabled=lambda account: False).call('a', {'blocks': [CHART], 'datasets': DATA}, name=NAME, request_id='t-a')[1])
        self.assertEqual(self.stored(), [])
        for _ in range(MAX_PER_TASK):
            self.assertFalse(self.show([CHART], DATA)[1])
        text, bad = self.show([CHART], DATA)
        self.assertTrue(bad); self.assertIn('is the limit', text)
        self.assertEqual([r['position'] for r in self.stored()], list(range(MAX_PER_TASK)))
        big = {'id': 'big', 'type': 'text', 'props': {'content': 'x' * 3000}}
        self.style('interactive', account='b')
        text, bad = self.show([dict(big, id=f'b{i}') for i in range(20)], account='b', request='t-b')
        self.assertTrue(bad); self.assertIn('Nothing was shown', text)

    def test_every_core_component_example_is_accepted_and_the_relay_offers_the_tool(self):
        entries = registry()['entries']
        with self.store.connect() as con:                                                   # a fresh task per example, so the per-task limit is not what is tested
            for index, name in enumerate(CORE_COMPONENTS):
                con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p-a','c-a',?,'completed',0)", (f'e{index}',))
                con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,context_json)
                    VALUES ('a',?,'actor-a','p-a','c-a',?,'h','show','running',1,'{"ui":"interactive"}')''', (f'e{index}', f'k{index}'))
        for index, name in enumerate(CORE_COMPONENTS):
            text, bad = self.show([entries[name]['example']], entries[name].get('exampleDatasets') or {}, request=f'e{index}')
            self.assertFalse(bad, (name, text))

        class Browser:
            store = self.store
        relay = Relay(Browser(), show=ShowTools(self.store, enabled=lambda account: account == 'a'))
        listed = lambda account: {t['name']: t for t in relay.handle(account, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools']}
        self.assertIn(NAME, listed('a')); self.assertNotIn(NAME, listed('b'))
        spec = listed('a')[NAME]
        self.assertEqual(set(spec['inputSchema']['properties']), {'blocks', 'datasets', '_lumina_origin'})
        self.assertGreater(len(spec['description']), 600)                                   # a contract: what it shows, the shapes, the limits, what it returns
        self.assertNotIn('MUST', spec['description']); self.assertNotIn('NEVER', spec['description'])


if __name__ == '__main__':
    unittest.main()
