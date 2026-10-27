"""Composed answers (```lumina-doc): the server validates with the same schemas as the browser, stores one document per reply, and degrades anything unsafe to text."""
import json
import unittest
from pathlib import Path

from agentai_platform.genui import document as doc
from agentai_platform.genui.schema import SpecError
from tests.test_native_run import Base

FIX = json.loads((Path(__file__).parent / 'fixtures' / 'gen_parity.json').read_text())


def one(block, **extra):
    return {'version': '1.0', 'responseId': 'r1', 'blocks': [block], **extra}


class Parity(unittest.TestCase):
    """The browser's own fixtures (lumina/src/gen/fixtures.ts) go through the server validator."""

    def test_every_valid_browser_fixture_block_is_accepted_unchanged(self):
        for document in FIX['valid']:
            out = doc.validate_document(document)
            self.assertEqual([b['id'] for b in out['blocks']], [b['id'] for b in document['blocks']], document['responseId'])
            self.assertTrue(all(b['type'] != 'text' or b['id'] in {x['id'] for x in document['blocks'] if x['type'] == 'text'} for b in out['blocks']), 'a block was downgraded to text')

    def test_every_invalid_browser_case_is_refused_by_the_server_too(self):
        for case in FIX['invalid']:
            with self.assertRaises(SpecError, msg=case['name']):
                doc.validate_block(case['block'])

    def test_registry_file_matches_what_the_assistant_is_told(self):
        reg = doc.registry()
        self.assertNotIn('image', reg['offered']); self.assertNotIn('gallery', reg['offered']); self.assertNotIn('file.download', reg['actions'])
        for name in reg['offered']:
            self.assertIn(name + ':', reg['catalogCompact'])
        for forbidden in ('map', 'kanban', 'gantt', 'sankey', 'weather'):
            self.assertNotIn(forbidden + ':', reg['catalogCompact'])


class Validation(unittest.TestCase):
    def test_a_failed_block_becomes_its_text_fallback_and_the_rest_survives(self):
        out = doc.validate_document({'version': '1.0', 'responseId': 'r', 'blocks': [
            {'id': 'a', 'type': 'text', 'props': {'content': 'ok'}},
            {'id': 'b', 'type': 'line_chart', 'props': {'title': 'Sales by month', 'xKey': 'm', 'series': []}},
            {'id': 'c', 'type': 'bar_chart', 'fallback': 'Revenue 24,500', 'props': {'xKey': 'm', 'series': [{'key': 'v'}], 'rogue': 1}}]})
        self.assertEqual([(b['id'], b['type']) for b in out['blocks']], [('a', 'text'), ('b', 'text'), ('c', 'text')])
        self.assertEqual(out['blocks'][1]['props']['content'], 'Sales by month'); self.assertEqual(out['blocks'][2]['props']['content'], 'Revenue 24,500')

    def test_markup_scripts_and_unsafe_links_never_reach_storage(self):
        for bad in ({'id': 'a', 'type': 'text', 'props': {'content': '<img src=x onerror=alert(1)>'}},
                    {'id': 'a', 'type': 'citation_list', 'props': {'sources': [{'label': 'x', 'url': 'javascript:alert(1)'}]}},
                    {'id': 'a', 'type': 'citation_list', 'props': {'sources': [{'label': 'x', 'url': 'https://u:p@h.example/'}]}},
                    {'id': 'a', 'type': 'button_group', 'props': {'buttons': [{'id': 'b', 'label': 'Go', 'action': {'kind': 'navigate.internal', 'path': '/admin'}}]}},
                    {'id': 'a', 'type': 'button_group', 'props': {'buttons': [{'id': 'b', 'label': 'Go', 'action': {'kind': 'file.download', 'path': 'a.csv'}}]}},
                    {'id': 'a', 'type': 'button_group', 'props': {'buttons': [{'id': 'b', 'label': 'Go', 'action': {'kind': 'shell.run'}}]}},
                    {'id': 'a', 'type': 'text', 'style': 'position:fixed', 'props': {'content': 'x'}}):
            with self.assertRaises(SpecError, msg=json.dumps(bad)[:70]):
                doc.validate_block(bad)

    def test_code_may_contain_angle_brackets_but_prose_may_not(self):
        doc.validate_block({'id': 'c', 'type': 'code_block', 'props': {'code': 'if a < b and c > d: pass'}})
        with self.assertRaises(SpecError):
            doc.validate_block({'id': 'c', 'type': 'callout', 'props': {'content': 'use <b>this</b>'}})

    def test_only_offered_components_exist(self):
        for t in ('image', 'gallery', 'map', 'kanban', 'iframe', 'script'):
            with self.assertRaises(SpecError, msg=t):
                doc.validate_block({'id': 'x', 'type': t, 'props': {}})

    def test_datasets_are_shared_checked_and_pruned(self):
        ds = {'columns': [{'id': 'k', 'label': 'K'}, {'id': 'v', 'label': 'V', 'type': 'number'}], 'rows': [{'k': 'a', 'v': 1}]}
        out = doc.validate_document(one({'id': 't', 'type': 'table', 'dataRef': 'd1', 'props': {}}, datasets={'d1': ds, 'unused': ds}))
        self.assertEqual(list(out['datasets']), ['d1'])
        missing = doc.validate_document({'version': '1.0', 'responseId': 'r', 'blocks': [{'id': 't', 'type': 'table', 'dataRef': 'nope', 'fallback': 'No data.', 'props': {}}, {'id': 'z', 'type': 'divider', 'props': {}}]})
        self.assertEqual(missing['blocks'][0]['props']['content'], 'No data.')

    def test_bounds(self):
        with self.assertRaises(SpecError):
            doc.validate_document({'version': '1.0', 'responseId': 'r', 'blocks': [{'id': f'b{i}', 'type': 'divider', 'props': {}} for i in range(25)]})
        with self.assertRaises(SpecError):
            doc.validate_document({'version': '2.0', 'responseId': 'r', 'blocks': [{'id': 'a', 'type': 'divider', 'props': {}}]})
        leaf = {'id': 'l', 'type': 'text', 'props': {'content': 'x'}}
        deep = {'id': 's1', 'type': 'section', 'props': {'blocks': [{'id': 's2', 'type': 'section', 'props': {'blocks': [{'id': 's3', 'type': 'section', 'props': {'blocks': [leaf]}}]}}]}}
        with self.assertRaises(SpecError):
            doc.validate_block(deep)
        big = {'id': 'q', 'type': 'text', 'props': {'content': 'x' * 8000}}
        with self.assertRaises(SpecError):
            doc.validate_document({'version': '1.0', 'responseId': 'r', 'blocks': [dict(big, id=f'q{i}') for i in range(8)]})

    def test_stacked_charts_need_two_series_and_duplicate_ids_collapse(self):
        with self.assertRaises(SpecError):
            doc.validate_block({'id': 'c', 'type': 'bar_chart', 'variant': 'stacked', 'props': {'xKey': 'm', 'series': [{'key': 'v'}]}})
        out = doc.validate_document({'version': '1.0', 'responseId': 'r', 'blocks': [{'id': 'd', 'type': 'divider', 'props': {}}, {'id': 'd', 'type': 'divider', 'props': {}}]})
        self.assertEqual(len(out['blocks']), 1)

    def test_old_documents_without_a_version_are_lifted(self):
        self.assertEqual(doc.validate_document({'blocks': [{'id': 'a', 'type': 'divider', 'props': {}}]})['version'], '1.0')


class Extraction(unittest.TestCase):
    BLOCK = {'id': 'm', 'type': 'metric_card', 'props': {'label': 'Revenue', 'value': 24500}}

    def test_json_document_fence_is_removed_from_the_text_and_returned_validated(self):
        text = 'Revenue is up.\n```lumina-doc\n' + json.dumps(one(self.BLOCK)) + '\n```\nAnything else?'
        clean, docs = doc.extract_documents(text)
        self.assertEqual(clean, 'Revenue is up.\n\nAnything else?'); self.assertNotIn('lumina-doc', clean)
        self.assertEqual(docs[0]['type'], 'document'); self.assertEqual(docs[0]['blocks'][0]['id'], 'm')

    def test_json_lines_with_datasets_and_one_bad_line(self):
        body = '\n'.join([json.dumps({'responseId': 'r5'}), json.dumps({'dataset': 'd', 'columns': [{'id': 'k', 'label': 'K'}], 'rows': [{'k': 'a'}]}),
                          json.dumps({'id': 't', 'type': 'table', 'dataRef': 'd', 'props': {}}), 'garbage', json.dumps({'id': 'n', 'type': 'follow_up', 'props': {'suggestions': ['Go on']}})])
        _, docs = doc.extract_documents('Here.\n```lumina-doc\n' + body + '\n```')
        self.assertEqual([b['id'] for b in docs[0]['blocks']], ['t', 'n']); self.assertEqual(docs[0]['responseId'], 'r5'); self.assertIn('d', docs[0]['datasets'])

    def test_invalid_oversized_or_unfinished_fences_vanish_and_leave_the_prose(self):
        for text in ('Hi.\n```lumina-doc\nnot json at all\n```', 'Hi.\n```lumina-doc\n{"version":"1.0","blo', 'Hi.\n```lumina-doc\n' + '{"id":"a","type":"iframe","props":{}}\n```'):
            clean, docs = doc.extract_documents(text)
            self.assertEqual((clean, docs), ('Hi.', [])); 
        clean, docs = doc.extract_documents('x\n```lumina-doc\n' + 'y' * 200000 + '\n```')
        self.assertEqual(docs, [])

    def test_only_one_document_per_reply(self):
        two = '```lumina-doc\n' + json.dumps(one(self.BLOCK)) + '\n```\n```lumina-doc\n' + json.dumps(one(dict(self.BLOCK, id='m2'))) + '\n```'
        self.assertEqual(len(doc.extract_documents(two)[1]), 1)

    def test_plain_replies_are_untouched(self):
        self.assertEqual(doc.extract_documents('Just text, with `code`.'), ('Just text, with `code`.', []))


class PresentationPlan(unittest.TestCase):
    PLAN = {'advisory': True, 'blocks': [{'blockId': 'hint1', 'componentId': 'table', 'purpose': 'Compare options', 'dataRequirements': ['rows']}]}

    def test_valid_plan_passes_and_everything_else_is_refused(self):
        self.assertEqual(doc.validate_presentation_plan(self.PLAN), self.PLAN)
        for bad in (dict(self.PLAN, advisory=False), dict(self.PLAN, blocks=[]), {**self.PLAN, 'props': {}},
                    {'advisory': True, 'blocks': [{'blockId': 'h', 'componentId': 'kanban', 'purpose': 'x'}]},
                    {'advisory': True, 'blocks': [{'blockId': 'h', 'componentId': 'table', 'variant': 'stacked', 'purpose': 'x'}]},
                    {'advisory': True, 'blocks': [{'blockId': 'h', 'componentId': 'table', 'purpose': '<b>x</b>'}]}):
            with self.assertRaises(SpecError):
                doc.validate_presentation_plan(bad)

    def test_a_bad_plan_inside_a_document_is_dropped_not_fatal(self):
        out = doc.validate_document(one({'id': 'a', 'type': 'divider', 'props': {}}, presentationPlan={'advisory': False, 'blocks': []}))
        self.assertNotIn('presentationPlan', out)


class Stored(Base):
    """A composed reply is stored as one 'document' block anchored to the reply; the prose stays as the message."""

    def blocks(self):
        return self.rows("SELECT kind,spec_json,anchor_message_id FROM data_blocks ORDER BY position")

    def test_reply_with_a_document_is_stored_and_listed_and_the_words_remain(self):
        reply = 'Revenue grew 6%.\n```lumina-doc\n' + json.dumps(one({'id': 'm', 'type': 'metric_card', 'props': {'label': 'Revenue', 'value': 24500, 'format': 'currency'}})) + '\n```'
        self.run_message('how is revenue', replies=[reply])
        b = self.blocks(); self.assertEqual([x['kind'] for x in b], ['document'])
        spec = json.loads(b[0]['spec_json']); self.assertEqual(spec['blocks'][0]['id'], 'm')
        row = self.rows("SELECT content FROM chat_messages WHERE provenance='agent' ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual(row['content'], 'Revenue grew 6%.'); self.assertNotIn('lumina-doc', row['content'])
        listed = self.chat.blocks.list(self.a, 'c-a'); self.assertEqual([x['kind'] for x in listed], ['document']); self.assertEqual(listed[0]['status'], 'final')

    def test_an_unsafe_document_stores_nothing_and_the_text_still_shows(self):
        reply = 'Look.\n```lumina-doc\n' + json.dumps(one({'id': 'x', 'type': 'iframe', 'props': {'src': 'https://evil.example'}})) + '\n```'
        self.run_message('hi', replies=[reply])
        self.assertEqual(self.blocks(), [])
        self.assertEqual(self.rows("SELECT content FROM chat_messages WHERE provenance='agent' ORDER BY id DESC LIMIT 1")[0]['content'], 'Look.')

    def test_a_plain_reply_makes_no_block(self):
        self.run_message('hello', replies=['Hi there, how can I help?'])
        self.assertEqual(self.blocks(), [])

    def test_other_accounts_never_see_the_document(self):
        reply = 'Ok.\n```lumina-doc\n' + json.dumps(one({'id': 'd', 'type': 'divider', 'props': {}})) + '\n```'
        self.run_message('hi', replies=[reply])
        from agentai_platform.security import NotFound, Principal
        with self.assertRaises(NotFound):
            self.chat.blocks.list(Principal('b', 'actor-b', 'customer'), 'c-a')


class Rules(unittest.TestCase):
    def test_the_assistant_is_taught_only_what_exists_and_plain_text_stays_default(self):
        from agentai_platform.lifecycle.cell_config import WORKSPACE_RULES as rules
        section = rules[rules.index('## Composed answers (lumina-doc)'):]
        for must in ('JSON Lines', 'never invent', 'nothing else exists', 'metric_card', 'approval_request', 'Most answers are plain text'):
            self.assertIn(must, rules, must)
        for absent in ('map:', 'kanban:', 'gantt:', 'image:', 'gallery:', 'file.download'):
            self.assertNotIn(absent, section, absent)
        self.assertEqual(rules.count('## Composed answers (lumina-doc)'), 1)
        self.assertLess(len(section) // 4, 1400)          # the always-on cost, measured in characters / 4


if __name__ == '__main__':
    unittest.main()
