"""The assistant's display tool: show the customer a table, chart, cards, a timeline, a form or buttons under its reply.

This replaces writing a fenced `lumina-doc` block by hand. The assistant calls `lumina_show` with blocks; they are checked against the same component
registry the app renders from (genui/document.py), and a block that is wrong comes back as a tool error naming the block and the problem, so the
assistant corrects it in the same turn instead of the customer seeing a broken or missing visual.

What is stored is exactly what the fenced protocol stored (a `document` row in data_blocks), so the app shows it with no change. It appears at the end
of the conversation at once and is attached to the assistant's reply when the task ends (BlockStore.anchor_shown).

Rules that hold whatever the assistant sends:
  - the document belongs to the task that made the call, in that task's own conversation;
  - the customer's answer style decides what is allowed: plain answers allow nothing, the middle style allows no buttons or follow-ups;
  - contents are data for fixed components: no HTML, no scripts, no remote resources (the registry's own checks).
"""
from __future__ import annotations
import copy
import json
import time
import uuid

from .genui import document
from .genui.schema import SpecError
from .lifecycle.coordinator import Coordinator

NAME = 'lumina_show'
MAX_PER_TASK = 3
# The components worth knowing by heart. Everything else in the registry still works, but is looked up when needed (lumina-ui/components/<type>.json).
CORE_COMPONENTS = ('text', 'heading', 'list', 'callout', 'info_card', 'metric_card', 'card_grid', 'table', 'line_chart', 'area_chart', 'bar_chart', 'pie_chart',
                   'scatter_chart', 'timeline', 'progress', 'citation_list', 'code_block', 'mermaid', 'form', 'button_group', 'follow_up')
INTERACTIVE_ONLY = ('button_group', 'follow_up')

TOOL = {'name': NAME, 'description': (
    'Show the customer a visual under your reply: a table, a chart, cards, a timeline, a form or buttons. Use it when the answer is clearer seen than read '
    '(several options with several attributes, a trend over time, a schedule, a choice they need to make); a short answer stays plain text. '
    'Pass "blocks", shown in order. Each block is {"id", "type", "props"} and, for tables and charts, "dataRef" naming an entry of "datasets". '
    'Common types: table, line_chart, bar_chart, pie_chart, info_card, card_grid, metric_card, timeline, callout, list, form, button_group, follow_up. '
    'A dataset is {"columns":[{"id":"month","label":"Month","type":"text|number|currency|percent|rating|link|status"}],"rows":[{"month":"Jan","revenue":1200}]} '
    '(rows are objects keyed by column id; at most 12 columns and 500 rows). The lumina-show skill has one accepted example of every common type. '
    'The call is checked before anything is shown: if a block is wrong you get the block id and the reason, nothing is shown, and you can correct it and call again. '
    'Keep one call under about 12,000 characters; for more data than that, deliver a spreadsheet file instead. Up to 3 visuals per task. '
    'Not available when the customer chose plain answers or is not in the Lumina app (the tool says so); buttons and follow-ups need the interactive answer style. '
    'Returns a short confirmation; it does not return the rendered picture.'),
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['blocks'], 'properties': {
        'blocks': {'type': 'array', 'minItems': 1, 'maxItems': 24, 'description': 'The components to show, in order.', 'items': {
            'type': 'object', 'required': ['id', 'type', 'props'], 'properties': {
                'id': {'type': 'string', 'description': 'A short name for this block, unique in the call: lowercase letters, digits, - or _, starting with a letter.'},
                'type': {'type': 'string', 'description': 'The component, for example "table" or "line_chart".'},
                'variant': {'type': 'string', 'description': 'An optional look the component offers, for example "striped" for a table.'},
                'dataRef': {'type': 'string', 'description': 'For tables and charts: the name of the dataset in "datasets" this block shows.'},
                'props': {'type': 'object', 'description': 'The component\'s own settings (title, columns to plot, card facts, form fields...). Plain text only.'}}}},
        'datasets': {'type': 'object', 'description': 'Named tables of real values that blocks refer to with "dataRef".', 'additionalProperties': {'type': 'object'}}}}}


class ShowTools:
    """What `tool_relay.Relay` calls. Same shape as the other tools: `call(account, arguments, closed, *, name, request_id)` -> (text, is_error)."""
    names = frozenset({NAME})

    def __init__(self, store, *, clock=time.time, enabled=lambda account: True):
        self.store, self.clock, self._enabled = store, clock, enabled
        self.coordinator = Coordinator(store, clock=clock)

    def enabled(self, account):
        try:
            return bool(self._enabled(account))
        except Exception:
            return False

    @staticmethod
    def specs():
        return [copy.deepcopy(TOOL)]

    def _request(self, account, request_id):
        with self.store.connect() as con:
            row = con.execute('SELECT conversation_id,context_json FROM customer_requests WHERE account_id=? AND id=?', (account, request_id)).fetchone()
        if row is None or not row['conversation_id']:
            return None, None
        try:
            context = json.loads(row['context_json'] or '{}')
        except ValueError:
            context = {}
        tier = context.get('ui') if isinstance(context, dict) and context.get('mode') != 'text' else 'basic'
        return row['conversation_id'], tier if tier in document.TIERS else document.DEFAULT_TIER

    def call(self, account, arguments, closed=lambda: False, *, name, request_id=None):
        try:
            if name != NAME or not self.enabled(account):
                return 'Showing visuals is not available.', True
            if not request_id:
                return 'This call does not belong to a running task. Nothing was shown.', True
            if not isinstance(arguments, dict) or not set(arguments) <= {'blocks', 'datasets'} or not isinstance(arguments.get('blocks'), list):
                return 'Give "blocks" (a list of {"id", "type", "props"}) and optionally "datasets". Nothing was shown.', True
            conversation, tier = self._request(account, request_id)
            if conversation is None:
                return 'This call does not belong to a running task. Nothing was shown.', True
            if tier == 'basic':
                return ('The customer chose plain answers (or is not in the Lumina app), so visuals are not shown here. Nothing was shown. '
                        'Give the same information in your reply as text; a small table in Markdown is fine.'), True
            blocks, datasets = arguments['blocks'], arguments.get('datasets') or {}
            if not isinstance(datasets, dict):
                return '"datasets" is an object: {"name": {"columns": [...], "rows": [...]}}. Nothing was shown.', True
            limits = document.registry()['limits']
            if not 1 <= len(blocks) <= limits['blocks']:
                return f'Give 1 to {limits["blocks"]} blocks. Nothing was shown.', True
            # Every problem at once, by block: the lenient path (a bad block quietly becoming text) is for old stored answers, not for a live call.
            problems, seen = [], set()
            for key, value in datasets.items():
                try:
                    document._check(document.registry()['datasetSchema'], value, document.registry()['datasetSchema'])
                except SpecError as error:
                    problems.append(f'dataset "{str(key)[:40]}": {str(error)[:200]}')
            for index, block in enumerate(blocks, start=1):
                label = f'block "{block["id"]}"' if isinstance(block, dict) and isinstance(block.get('id'), str) else f'block {index}'
                if isinstance(block, dict) and block.get('id') in seen:
                    problems.append(f'{label}: this id is used twice')
                    continue
                try:
                    document.validate_block(block, datasets, tier)
                    seen.add(block.get('id'))
                except SpecError as error:
                    reason = str(error)[:200]
                    if reason == 'this component is not available' and isinstance(block, dict) and block.get('type') in INTERACTIVE_ONLY:
                        reason = 'buttons and follow-ups need the interactive answer style, which the customer has not chosen; leave this block out'
                    problems.append(f'{label} ({str(block.get("type"))[:40] if isinstance(block, dict) else "?"}): {reason}')
                except (TypeError, KeyError, ValueError, AttributeError):
                    problems.append(f'{label}: not a valid block; a block is {{"id", "type", "props"}}')
            if problems:
                return ('Nothing was shown. Fix these and call again:\n- ' + '\n- '.join(problems[:12]) +
                        '\nThe lumina-show skill has an accepted example of each common component; lumina-ui/components/<type>.json has the others.'), True
            try:
                doc = document.validate_document({'responseId': 'show-' + uuid.uuid4().hex[:12], 'blocks': blocks, 'datasets': datasets}, tier)
            except SpecError as error:
                return f'Nothing was shown: {str(error)[:200]}. Show less in one call, or deliver the data as a file.', True
            if closed():
                return 'The connection closed; nothing was shown.', True
            with self.coordinator.transaction() as con:
                made = con.execute("SELECT count(*) FROM data_blocks WHERE account_id=? AND source_request_id=? AND kind='document'", (account, request_id)).fetchone()[0]
                if made >= MAX_PER_TASK:
                    return f'This task already shows {MAX_PER_TASK} visuals, which is the limit. Nothing more was shown.', True
                position = con.execute('SELECT coalesce(max(position),-1)+1 FROM data_blocks WHERE account_id=? AND source_request_id=?', (account, request_id)).fetchone()[0]
                con.execute('INSERT INTO data_blocks(account_id,id,conversation_id,anchor_message_id,kind,spec_json,source_request_id,position,created_epoch) VALUES (?,?,?,?,?,?,?,?,?)',
                            (account, uuid.uuid4().hex, conversation, None, 'document', json.dumps(dict(doc, type='document')), request_id, position, int(self.clock())))
            kinds = ', '.join(dict.fromkeys(b['type'] for b in doc['blocks']))
            return (f'Shown to the customer under your reply: {kinds}. Do not repeat its contents in your text; say in a sentence or two what it shows and what you conclude.'), False
        except Exception:
            return 'Something went wrong. Nothing was shown.', True
