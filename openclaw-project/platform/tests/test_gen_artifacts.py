"""Complete request -> artifact -> user event -> request -> same artifact, with durable state."""
import json
from agentai_platform.genui.artifacts import ArtifactStore, strict_document
from agentai_platform.genui.schema import SpecError
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal
from tests.test_native_run import Base

FORM = {'id': 'choices', 'type': 'form', 'props': {'fields': [{'id': 'quantity', 'type': 'number', 'label': 'Quantity', 'min': 1, 'max': 20, 'required': True}], 'submit': {'label': 'Calculate', 'action': {'kind': 'agent.request', 'message': 'Calculate the total'}}}}

def doc(blocks=None, **kw):
    return dict(version='1.0', responseId='result', blocks=blocks or [FORM], **kw)

def reply(value):
    return 'Choose the quantity.\n```lumina-doc\n' + json.dumps(value) + '\n```'


class ArtifactLoop(Base):
    def create(self):
        self.run_message('Build a form', [reply(doc())], ui='interactive')
        artifact = self.chat.blocks.list(self.a, 'c-a')[0]
        return artifact, ArtifactStore(self.store, clock=lambda: self.now)

    def event(self, artifact, **kw):
        return dict(id='event-1', node_id='choices', action_id='submit', version=artifact['version'], values={'quantity': 4}, **kw)

    def test_submission_updates_the_same_artifact_and_preserves_values_after_reopening(self):
        artifact, store = self.create()
        # No autosave: submitting must atomically preserve these values before a fast update.
        sent = store.event(self.a, artifact['id'], self.event(artifact), self.chat)
        updated = doc([FORM, {'id': 'total', 'type': 'metric_card', 'props': {'label': 'Total', 'value': 40}}], artifactId=artifact['id'], baseVersion=1)
        self.gateway.script = lambda *_: {'text': reply(updated)}
        self.worker.tick()
        reopened = self.chat.blocks.list(self.a, 'c-a')
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0]['id'], artifact['id'])
        self.assertEqual(reopened[0]['version'], 2)
        self.assertEqual(reopened[0]['state']['choices']['values'], {'quantity': 4})
        self.assertEqual(reopened[0]['spec']['blocks'][-1]['props']['value'], 40)
        recorded = self.rows('SELECT * FROM gen_artifact_events')[0]
        self.assertEqual(recorded['status'], 'success')
        self.assertEqual(recorded['actor_id'], self.a.actor_id)
        context = json.loads(self.request(sent['id'])['context_json'])
        self.assertEqual(context['ui_artifact']['artifact_id'], artifact['id'])
        self.assertEqual(context['ui_artifact']['values'], {'quantity': 4})
        self.assertIn('Quantity: 4', self.request(sent['id'])['message'])

    def test_duplicate_event_is_one_request_and_stale_or_tampered_events_are_refused(self):
        artifact, store = self.create()
        first = store.event(self.a, artifact['id'], self.event(artifact), self.chat)
        again = store.event(self.a, artifact['id'], self.event(artifact), self.chat)
        self.assertEqual(first, again)
        self.assertEqual(len(self.rows('SELECT * FROM gen_artifact_events')), 1)
        event = self.event(artifact); event['values'] = {'quantity': 7}
        with self.assertRaises(Conflict): store.event(self.a, artifact['id'], event, self.chat)
        event['id'] = 'event-2'; event['version'] = 2
        with self.assertRaises(Conflict): store.event(self.a, artifact['id'], event, self.chat)
        event['version'] = 1; event['values'] = {'quantity': 100}
        with self.assertRaises(SpecError): store.event(self.a, artifact['id'], event, self.chat)
        event['values'] = {'quantity': 2}; event['action_id'] = 'forged'
        with self.assertRaises(SpecError): store.event(self.a, artifact['id'], event, self.chat)
        with self.assertRaises(NotFound): store.event(Principal('b', 'actor-b', 'customer'), artifact['id'], self.event(artifact), self.chat)

    def test_state_uses_compare_and_swap_and_updates_drop_incompatible_state(self):
        artifact, store = self.create()
        store.state(self.a, artifact['id'], 1, 1, {'choices': {'values': {'quantity': 4}}})
        with self.assertRaises(Conflict): store.state(self.a, artifact['id'], 1, 1, {})
        with self.assertRaises(SpecError): store.state(self.a, artifact['id'], 1, 2, {'alien': {}})
        store.update(self.a, artifact['id'], 1, doc([{'id': 'choices', 'type': 'text', 'props': {'content': 'Finished'}}]))
        self.assertEqual(self.chat.blocks.list(self.a, 'c-a')[0]['state'], {})
        with self.assertRaises(Conflict): store.update(self.a, artifact['id'], 1, doc())

    def test_strict_validation_rejects_nested_duplicate_ids_and_unknown_bindings(self):
        for raw in (doc([FORM, FORM]), doc([{'id': 'x', 'type': 'iframe', 'props': {}}]), doc([FORM], code='alert(1)')):
            with self.assertRaises(SpecError): strict_document(raw)

    def test_approval_artifact_waits_for_valid_user_event_and_uses_native_gate(self):
        from tests.test_genui import plan, phase
        artifact, store = self.create()
        gated = self.chat.blocks.create_plan('a', 'c-a', plan(phase('publish', requiresApproval=True)), key='gated-plan')
        self.chat.launch_plan(self.a, gated['id'], 1)
        self.assertEqual(self.chat.blocks.get(self.a, gated['id'])['run']['publish']['state'], 'awaiting_approval')
        approval = {'id': 'approval', 'type': 'approval_request', 'props': {'planBlockId': gated['id'], 'phaseId': 'publish'}}
        store.update(self.a, artifact['id'], 1, doc([approval]))
        self.assertIsNone(self.chat.blocks.get(self.a, gated['id'])['launched_request_id'])
        event = {'id': 'approval-event', 'node_id': 'approval', 'action_id': 'approve', 'version': 2, 'values': {}}
        with self.assertRaises(NotFound): store.event(Principal('b', 'actor-b', 'customer'), artifact['id'], event, self.chat)
        self.assertEqual(self.chat.blocks.get(self.a, gated['id'])['run']['publish']['state'], 'awaiting_approval')
        result = store.event(self.a, artifact['id'], event, self.chat)
        self.assertIn(result['block']['run']['publish']['state'], ('pending', 'running'))
        self.assertEqual(store.event(self.a, artifact['id'], event, self.chat), result)
        self.assertEqual(self.rows("SELECT count(*) FROM gen_artifact_events WHERE action_id='approve'")[0][0], 1)

    def test_usage_is_from_receipts_and_reservation_fallbacks_are_labelled_estimates(self):
        artifact, store = self.create()
        task = self.rows('SELECT id FROM customer_requests')[0][0]
        self.chat.ledger.receipt(account='a', task=task, provider='fixture', request='estimated-receipt', amount_microusd=123,
                                 observed_epoch=self.now, price_version='reservation-upper-bound-v1', payload_hash='a' * 64)
        usage = self.chat.task(self.a, task)['usage']
        self.assertIsNone(usage['tokens'])
        self.assertTrue(usage['estimated'])
        self.assertGreaterEqual(usage['cost_microusd'], 123)
        with self.assertRaises(NotFound): self.chat.task(Principal('b', 'actor-b', 'customer'), task)

    def test_server_validates_dates_ranges_steps_and_defaults_without_side_effects(self):
        from agentai_platform.genui.artifacts import answers, FieldErrors
        for kind, value, options in [('number', 1.5, {'step': 1}), ('date', '2026-02-30', {}), ('time', '25:01', {}), ('range', [2, 1], {}), ('date-range', ['2026-02-30', '2026-03-01'], {}), ('color', 'red', {})]:
            node = {'type': 'form', 'props': {'fields': [{'id': 'value', 'label': 'Value', 'type': kind, **options}]}}
            with self.subTest(kind=kind), self.assertRaises(FieldErrors) as caught:
                answers(node, {'value': value})
            self.assertEqual(set(caught.exception.errors), {'value'})
        node = {'type': 'form', 'props': {'fields': [{'id': 'show', 'label': 'Show', 'type': 'toggle', 'default': True}, {'id': 'detail', 'label': 'Detail', 'type': 'text', 'required': True, 'showIf': {'field': 'show', 'equals': True}}]}}
        with self.assertRaises(FieldErrors): answers(node, {})
        self.assertEqual(answers(node, {'show': False})[0], {'show': False})

    def test_a_location_answer_is_a_short_plain_text_and_a_required_one_cannot_be_left_empty(self):
        from agentai_platform.genui.artifacts import answers, FieldErrors
        node = {'type': 'location_request', 'props': {'fields': [{'id': 'where', 'label': 'Your location', 'type': 'location', 'required': True}]}}
        out, lines = answers(node, {'where': '94110'})
        self.assertEqual((out, lines), ({'where': '94110'}, ['- Your location: 94110']))
        out, _ = answers(node, {'where': 'Shared from my device, approximate (about 1 km): 37.77, -122.42'})
        self.assertIn('37.77', out['where'])
        for bad in ('', 'x' * 501, 'a\x00b'):
            with self.subTest(bad=bad[:5]), self.assertRaises(FieldErrors) as caught:
                answers(node, {'where': bad})
            self.assertEqual(set(caught.exception.errors), {'where'})

    def test_an_answer_given_in_a_component_reaches_the_assistant_but_is_not_a_chat_bubble_and_the_component_stays_locked(self):
        artifact, store = self.create()
        sent = store.event(self.a, artifact['id'], self.event(artifact), self.chat)
        self.assertIn('Quantity: 4', self.request(sent['id'])['message'])                                    # the assistant gets it
        rows = self.chat.messages(self.a, 'c-a')['messages']
        answer = next(m for m in rows if m['request_id'] == sent['id'] and m['provenance'] == 'customer')
        self.assertTrue(answer['ui_answer']); self.assertIn('Quantity: 4', answer['content'])                # kept, but marked so the chat does not show it
        self.assertFalse(any(m['ui_answer'] for m in rows if m['provenance'] == 'agent'))
        listed = self.chat.conversations(self.a)
        self.assertTrue(all('Quantity: 4' not in (c.get('preview') or '') for c in listed))                  # nor the preview line of the chat list
        state = self.chat.blocks.list(self.a, 'c-a')[0]['state']['choices']
        self.assertEqual((state['values'], state['chosen']), ({'quantity': 4}, 'submit')); self.assertTrue(state['answered'])
        again = dict(self.event(artifact), id='event-2', values={'quantity': 9})
        with self.assertRaises(Conflict): store.event(self.a, artifact['id'], again, self.chat)              # final: a second answer is refused
        self.assertEqual(store.event(self.a, artifact['id'], self.event(artifact), self.chat), sent)         # the same event replayed is the same result, not a conflict

    def test_choosing_a_button_locks_the_group_and_remembers_which_one(self):
        buttons = {'id': 'next', 'type': 'button_group', 'props': {'buttons': [{'id': 'go', 'label': 'Show details', 'action': {'kind': 'agent.request', 'message': 'Show the details'}},
                                                                               {'id': 'skip', 'label': 'Skip', 'action': {'kind': 'agent.request', 'message': 'Skip it'}}]}}
        self.run_message('Offer choices', [reply(doc([buttons]))], ui='interactive')
        artifact = self.chat.blocks.list(self.a, 'c-a')[0]; store = ArtifactStore(self.store, clock=lambda: self.now)
        sent = store.event(self.a, artifact['id'], dict(id='event-1', node_id='next', action_id='go', version=artifact['version'], values={}), self.chat)
        state = self.chat.blocks.list(self.a, 'c-a')[0]['state']['next']
        self.assertEqual(state['chosen'], 'go'); self.assertTrue(state['answered'])
        with self.assertRaises(Conflict): store.event(self.a, artifact['id'], dict(id='event-2', node_id='next', action_id='skip', version=artifact['version'], values={}), self.chat)
        self.assertTrue(next(m for m in self.chat.messages(self.a, 'c-a')['messages'] if m['request_id'] == sent['id'] and m['provenance'] == 'customer')['ui_answer'])

    def test_failed_admission_can_retry_same_event_without_a_duplicate_request(self):
        from unittest.mock import patch
        from agentai_platform.budget import BudgetDenied
        artifact, store = self.create()
        before = len(self.rows('SELECT id FROM customer_requests'))
        with patch.object(self.chat, 'send', side_effect=BudgetDenied('queue full')):
            with self.assertRaises(BudgetDenied): store.event(self.a, artifact['id'], self.event(artifact), self.chat)
        self.assertEqual(self.rows('SELECT status FROM gen_artifact_events')[0][0], 'failed')
        first = store.event(self.a, artifact['id'], self.event(artifact), self.chat)
        self.assertEqual(store.event(self.a, artifact['id'], self.event(artifact), self.chat), first)
        self.assertEqual(len(self.rows('SELECT id FROM customer_requests')), before + 1)

    def test_invalid_only_document_has_a_readable_fallback_and_sanitized_diagnostic(self):
        from agentai_platform.genui.document import extract_documents
        with self.assertLogs('agentai.genui', level='WARNING') as logged:
            text, docs = extract_documents('```lumina-doc\n{"blocks":[{"type":"script","secret":"private input"}]}\n```')
        self.assertTrue(text); self.assertFalse(docs)
        self.assertNotIn('private', ''.join(logged.output))
