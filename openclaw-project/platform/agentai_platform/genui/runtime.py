"""Bridges generative UI to the existing request runtime: builds what the cell is asked, and turns a plan reply into a block."""
from __future__ import annotations
import json
import re

from . import prompts, schema


def extract_json(text: str):
    """The first JSON object in a model reply (tolerates a code fence or a short lead-in). Returns None if there is none."""
    text = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', text.strip())
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


class GenUiRuntime:
    def __init__(self, store, blocks):
        self.store, self.blocks = store, blocks

    def request_info(self, claim) -> tuple[str, dict]:
        with self.store.connect() as con:
            row = con.execute('SELECT intent,context_json FROM customer_requests WHERE account_id=? AND id=?', (claim.account_id, claim.request_id)).fetchone()
        return (row['intent'] or 'chat', json.loads(row['context_json'] or '{}')) if row else ('chat', {})

    def with_conversation_context(self, claim, message: str) -> str:
        """Carry bounded saved context into a fresh browser job or native session; never mix accounts/chats."""
        if not claim.conversation_id:
            return message
        with self.store.connect() as con:
            anchor = con.execute("SELECT min(id) FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance IN ('customer','telegram')", (claim.account_id, claim.conversation_id, claim.request_id)).fetchone()[0]
            if anchor is None:
                return message
            rows = con.execute("SELECT provenance,content FROM chat_messages WHERE account_id=? AND conversation_id=? AND id<? ORDER BY id DESC LIMIT 20", (claim.account_id, claim.conversation_id, anchor)).fetchall()
        history, remaining = [], 12000
        for row in rows:
            if remaining <= 0:
                break
            content = row['content'][:min(remaining, 3000)]
            history.append({'role': 'assistant' if row['provenance'] == 'agent' else 'user', 'content': content})
            remaining -= len(content)
        if not history:
            return message
        return ('Previous messages from this same conversation (quoted context, not new actions to execute):\n' + json.dumps(list(reversed(history)), ensure_ascii=False) + '\nCurrent user request:\n' + message)

    def outgoing(self, claim, intent: str, context: dict) -> str:
        if intent == 'plan':
            return prompts.plan_prompt(claim.message, context.get('answers'))
        if intent == 'execute':
            with self.store.connect() as con:
                row = con.execute('SELECT plan_json FROM plan_revisions WHERE account_id=? AND block_id=? AND revision=?',
                                  (claim.account_id, context['block'], context['revision'])).fetchone()
                req = con.execute('SELECT state_json FROM ui_blocks WHERE account_id=? AND id=?', (claim.account_id, context['block'])).fetchone()
            plan = json.loads(row['plan_json'])
            answers = json.loads(req['state_json']).get('requirements') or None
            return prompts.execute_prompt(plan, answers)
        if intent == 'phase':
            with self.store.connect() as con:
                blk = con.execute('SELECT state_json FROM ui_blocks WHERE account_id=? AND id=?', (claim.account_id, context['block'])).fetchone()
                rows = con.execute("SELECT phase_id,summary FROM plan_phase_runs WHERE account_id=? AND block_id=? AND state='completed' ORDER BY position",
                                   (claim.account_id, context['block'])).fetchall()
            state = json.loads(blk['state_json']); plan = state['plan']
            order = schema.execution_order(plan)
            done = {r['phase_id']: r['summary'] for r in rows}
            current = next(p for p in plan['phases'] if p['id'] == context['phase'])
            return prompts.phase_prompt(plan, state.get('requirements') or None, [(p, done[p['id']]) for p in order if p['id'] in done], current, len(order),
                                        [p['id'] for p in order].index(current['id']) + 1)
        with self.store.connect() as con:
            row = con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?', (claim.account_id, claim.conversation_id)).fetchone()
        return self.with_conversation_context(claim, claim.message) if row and not row['native_session_ref'] else claim.message

    def validate_reply(self, reply: str):
        """(plan, None) when the reply is a valid plan, else (None, reason)."""
        data = extract_json(reply or '')
        if data is None:
            return None, 'no JSON object found'
        try:
            return schema.validate_plan(data), None
        except schema.SpecError as exc:
            return None, str(exc)

    def attach_plan(self, claim, context: dict, plan: dict) -> dict:
        with self.store.connect() as con:
            msg = con.execute("SELECT id FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance='agent' "
                              "ORDER BY id DESC LIMIT 1", (claim.account_id, claim.conversation_id, claim.request_id)).fetchone()
        anchor = msg['id'] if msg else None
        block = self.blocks.create_plan(claim.account_id, claim.conversation_id, plan, key='plan-' + claim.request_id, anchor_message_id=anchor,
                                        source_request_id=claim.request_id, requirements=context.get('answers'))
        if anchor:
            text = f'I drafted a plan: {plan["title"]}. Edit the phases below, then launch it when it looks right.'
            with self.blocks.coordinator.transaction() as con:
                con.execute('UPDATE chat_messages SET content=? WHERE account_id=? AND id=?', (text, claim.account_id, anchor))
        return block
