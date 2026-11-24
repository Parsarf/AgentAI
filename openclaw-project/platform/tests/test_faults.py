"""One way to say why something did not finish (reliability plan, Part 1): the registry, the fault, what may be kept in its detail, the model relay's record of each
call, and the reason every ending that is not clean now leaves behind."""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform import faults, model_calls, model_keys, retention
from agentai_platform.chat_driver import ALLOWANCE_FAILURE, BUSY_FAILURE, MODEL_FAILURE, SELECTION_FAILURE, failure_message
from agentai_platform.connector_kit import FAULT_KINDS
from agentai_platform.faults_registry import REASONS
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.outcome import Verdict
from tests.test_native_run import OK, Base
from tests.test_rate_limits import Connection, Response


class Registry(unittest.TestCase):
    def test_every_reason_is_complete_and_from_the_closed_lists(self):
        for code, reason in REASONS.items():
            with self.subTest(code):
                self.assertRegex(code, r'^[a-z]+\.[a-z_]+$')
                self.assertIn(reason.kind, faults.KINDS)
                self.assertIn(reason.actor, faults.ACTORS)
                self.assertIn(reason.effect, faults.EFFECTS)
                self.assertTrue(reason.customer.strip().endswith('.'))
                self.assertLessEqual(len(reason.customer), 300)
                if reason.kind == 'needs_owner':
                    self.assertTrue(reason.alert, 'something only the owner can fix must reach the owner')
                if reason.kind == 'needs_customer':
                    self.assertEqual(reason.actor, 'customer')

    def test_the_connector_contract_is_part_of_it_unchanged(self):
        self.assertTrue(set(FAULT_KINDS) <= set(faults.KINDS))
        for kind in FAULT_KINDS:
            self.assertEqual(REASONS['connector.' + kind].kind, kind)

    def test_no_sentence_names_a_provider_or_shows_a_code(self):
        for code, reason in REASONS.items():
            for words in (reason.customer, reason.assistant):
                self.assertNotRegex(words, r'(?i)anthropic|openai|litellm|openclaw|\b[45]\d\d\b|traceback|exception', code)

    def test_a_reason_that_is_not_registered_cannot_be_made(self):
        with self.assertRaises(ValueError):
            faults.Fault('browser.something_new')
        with self.assertRaises(ValueError):
            faults.Fault('run.timeout', effect='half')


class Detail(unittest.TestCase):
    def test_only_facts_are_kept(self):
        kept = faults.Fault('browser.failed', {
            'status': 503, 'exception': 'TimeoutError', 'state': 'error', 'seconds': 12.34567, 'attempt': 2,
            'url': 'https://shop.example/cart?item=4', 'note': 'the page said Welcome back Dana', 'tool': 'lumina_browser',
            'code': 'someone@example.com', 'provider_error': 'a sentence with spaces', 'route': 'https://x/y', 'steps': None}).detail
        self.assertEqual(kept, {'status': 503, 'exception': 'TimeoutError', 'state': 'error', 'seconds': 12.346, 'attempt': 2, 'tool': 'lumina_browser'})

    def test_page_text_in_a_browser_reason_never_reaches_the_record(self):
        fault = faults.of_browser_job('stopped', 'The size and colour choices have no clickable controls on this page, and the page shows "Restocks on Nov 24"')
        self.assertEqual((fault.reason, fault.detail), ('browser.stopped', {'state': 'stopped'}))
        self.assertEqual(faults.of_browser_job('error', 'the browser run failed (TimeoutError)').detail, {'state': 'error', 'exception': 'TimeoutError'})

    def test_what_is_not_a_failure_is_not_a_fault(self):
        self.assertIsNone(faults.of_browser_job('done', 'Found it'))
        self.assertIsNone(faults.of_browser_job('stopped', faults.RELEASED_REASON))      # the assistant answered and went on: the page was simply no longer needed
        self.assertIsNone(faults.of_model_status(200))
        self.assertIsNone(faults.of_finished_run('completed', jobs=[{'state': 'error'}]))
        self.assertIsNone(faults.of_finished_run('partial', goal={'status': 'active'}, continuing=True))


class Mapping(unittest.TestCase):
    def test_a_model_status_has_one_reason_and_the_right_person(self):
        cases = [((429, '', False), 'model.rate_limited', 'nobody'), ((529, '', False), 'model.rate_limited', 'nobody'), ((500, '', False), 'model.provider_error', 'nobody'),
                 ((404, '', False), 'model.not_offered', 'customer'), ((401, '', False), 'model.lumina_key_refused', 'owner'), ((403, '', False), 'model.lumina_key_refused', 'owner'),
                 ((401, '', True), 'model.own_key_refused', 'customer'), ((402, 'budget_exhausted', False), 'model.allowance_exhausted', 'customer'),
                 ((409, 'admission_mismatch', False), 'model.selection_changed', 'customer'), ((502, 'upstream_unreachable', False), 'model.unreachable', 'owner'),
                 ((429, 'too_many_at_once', False), 'model.too_many_calls', 'nobody'), ((400, 'bad_request', False), 'model.bad_request', 'owner'),
                 ((418, '', False), 'internal.unclassified', 'owner')]
        for (status, code, own), reason, actor in cases:
            with self.subTest(status=status, code=code, own=own):
                fault = faults.of_model_status(status, code, own=own)
                self.assertEqual((fault.reason, fault.actor), (reason, actor))
        self.assertEqual(faults.of_model_status(429).retry, 'later')
        self.assertEqual(faults.of_model_status(404).retry, 'never')
        self.assertTrue(faults.of_model_status(402, 'budget_exhausted').expected)

    def test_the_reason_for_a_runtime_error_agrees_with_the_sentence_the_customer_is_shown(self):
        for text, sentence in (('budget_exhausted', ALLOWANCE_FAILURE), ('The model request was rate-limited.', BUSY_FAILURE), ('HTTP 429', BUSY_FAILURE),
                               ('The configured model is unavailable from the provider', MODEL_FAILURE), ('admission_mismatch', SELECTION_FAILURE),
                               ('agent run timeout', failure_message('timeout'))):
            with self.subTest(text):
                self.assertEqual(failure_message(text), sentence)
                self.assertEqual(faults.of_runtime_error(text).customer_words, sentence)

    def test_an_error_nobody_classified_is_counted_as_that_and_reaches_the_owner(self):
        fault = faults.of_runtime_error('Agent failed before reply: Inline API key for provider "selection" is temporarily disabled after a provider auth/billing failure.')
        self.assertEqual((fault.reason, fault.alert, fault.detail), ('run.unclassified', True, {'kind': 'runtime_text'}))       # the text itself is never kept


class Relay(unittest.TestCase):
    """The model relay tells its recorder about every call once: refused here, or when its reply has fully passed."""
    def relay(self, responses, **kw):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.noted, self.sent, self.ticks = [], [], iter(range(0, 10_000, 2))
        relay = model_keys.ModelRelay(model_keys.ModelKeyStore(str(Path(tmp.name) / 'keys.json')), lambda account: False, selection=lambda account: 'lumina-default',
                                      sleep=lambda s: None, jitter=lambda: 0.0, clock=lambda: next(self.ticks), record=lambda account, call: self.noted.append((account, call)), **kw)
        queue = list(responses)
        relay._lumina_connection = lambda: Connection(queue.pop(0), self.sent)
        from agentai_platform.model_catalog import models
        relay.selection = lambda account: models()[0]['id'] if 'id' in models()[0] else 'lumina-default'
        return relay

    def call(self, relay):
        return relay.selected_chat('a', 'cell-credential', json.dumps({'model': 'x', 'messages': [{'role': 'user', 'content': 'hi'}]}).encode())

    def test_a_call_that_worked_is_noted_once_when_its_reply_has_passed_with_the_token_counts(self):
        body = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":1200,"completion_tokens":7,"prompt_tokens_details":{"cached_tokens":1000}}}\n\ndata: [DONE]\n\n'
        up = self.call(self.relay([Response(200, body)]))
        self.assertEqual(self.noted, [])                         # not before the reply has passed
        self.assertEqual(b''.join(up.chunks()), body)
        up.close()                                               # a second close notes nothing more
        (account, call), = self.noted
        self.assertEqual((account, call['route'], call['status'], call['code'], call['reply_bytes']), ('a', 'lumina', 200, '', len(body)))
        self.assertEqual((call['input_tokens'], call['output_tokens'], call['cached_tokens']), (1200, 7, 1000))
        self.assertGreater(call['total_ms'], call['answer_ms'])

    def test_a_call_the_relay_refuses_is_noted_with_its_own_code(self):
        relay = self.relay([Response(429, b'{"error":{"message":"Budget has been exceeded! Key=x","type":"budget_exceeded"}}')])
        with self.assertRaises(model_keys.RelayError):
            self.call(relay)
        (_, call), = self.noted
        self.assertEqual((call['status'], call['code'], call['reply_bytes']), (402, 'budget_exhausted', 0))

    def test_waiting_for_a_busy_provider_is_measured_apart(self):
        up = self.call(self.relay([Response(429, b'{}', {'Retry-After': '7'}), Response(200, b'ok')]))
        list(up.chunks())
        self.assertEqual(self.noted[0][1]['waited_ms'], 7000)

    def test_a_recorder_that_fails_changes_nothing(self):
        relay = self.relay([Response(200, b'ok')])
        relay.record = lambda account, call: 1 / 0
        up = self.call(relay)
        self.assertEqual(b''.join(up.chunks()), b'ok')

    def test_without_a_recorder_the_relay_is_exactly_as_before(self):
        relay = self.relay([Response(200, b'ok')])
        relay.record = None
        up = self.call(relay)
        self.assertEqual((up.status, b''.join(up.chunks())), (200, b'ok'))

    def test_token_counts_are_numbers_or_nothing(self):
        up = model_keys.Upstream(200, 'application/json', None, None)
        self.assertEqual(up.usage(), {'input': None, 'output': None, 'cached': None})
        up.tail = b'{"usage":{"input_tokens":"many","output_tokens":3,"cache_read_input_tokens":true}}'
        self.assertEqual(up.usage(), {'input': None, 'output': 3, 'cached': None})


class Recorded(Base):
    def faults(self, request_id=None):
        return [dict(r) for r in self.rows('SELECT * FROM faults' + (' WHERE request_id=?' if request_id else '') + ' ORDER BY created_epoch,id', (request_id,) if request_id else ())]

    def test_a_failed_model_call_leaves_the_call_and_its_reason_tied_to_the_one_running_task(self):
        sent = self.say()
        self.queue.claim(owner='w', capacity=OK)
        fault = model_calls.note(self.store, 'a', {'route': 'lumina', 'status': 403, 'code': '', 'waited_ms': 0, 'answer_ms': 120, 'total_ms': 130, 'reply_bytes': 80,
                                                 'input_tokens': None, 'output_tokens': None, 'cached_tokens': None}, now=self.now)
        self.assertEqual(fault.reason, 'model.lumina_key_refused')
        call, = self.rows('SELECT * FROM model_calls')
        self.assertEqual((call['request_id'], call['status'], call['route'], call['total_ms'], call['input_tokens']), (sent['id'], 403, 'lumina', 130, None))
        row, = self.faults(sent['id'])
        self.assertEqual((row['kind'], row['actor'], row['expected'], json.loads(row['detail_json'])), ('needs_owner', 'owner', 0, {'route': 'lumina', 'status': 403}))

    def test_a_call_that_worked_leaves_no_fault_and_one_with_no_running_task_is_kept_with_the_account(self):
        self.assertIsNone(model_calls.note(self.store, 'a', {'route': 'own', 'status': 200, 'total_ms': 900, 'input_tokens': 10, 'output_tokens': 2}, now=self.now))
        call, = self.rows('SELECT * FROM model_calls')
        self.assertEqual((call['request_id'], call['route'], call['input_tokens'], call['output_tokens']), (None, 'own', 10, 2))
        self.assertEqual(self.faults(), [])

    def test_recording_never_raises(self):
        class Broken:
            def connect(self): raise RuntimeError('no database')
        self.assertIsNone(model_calls.note(Broken(), 'a', {'status': 500}))
        self.assertIsNone(faults.record(Broken(), 'a', faults.Fault('run.timeout')))

    def test_a_run_the_runtime_ended_in_an_error_leaves_its_reason(self):
        self.gateway.script = lambda text, run, gw: {'error': 'The model request was rate-limited. Please try again in a few minutes.'}
        sent = self.say()
        self.worker.tick()
        self.assertEqual(self.request(sent['id'])['state'], 'failed')
        row, = self.faults(sent['id'])
        self.assertEqual((row['reason'], row['kind'], row['feature'], row['effect']), ('model.rate_limited', 'retry_later', 'model', 'partly_done'))

    def test_a_task_stopped_at_the_spending_limit_is_an_expected_stop_not_an_error(self):
        class Spender(SyntheticGateway):
            readings = [0, 700000, 1400000, 2100000]
            def usage_snapshot(self):
                return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        self.gateway = Spender(polls=50)
        self.make_worker(spend_check_seconds=0)
        sent = self.say()
        self.worker.tick()
        row, = self.faults(sent['id'])
        self.assertEqual((row['reason'], row['kind'], row['actor'], row['expected']), ('task.spending_limit', 'limit', 'customer', 1))

    def test_a_browser_that_did_not_finish_is_the_reason_for_a_partial_task(self):
        sent = self.say()
        with self.store.connect() as con:
            con.execute('INSERT INTO browse_runs(account_id,request_id,goal,status,reason,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?)',
                        ('a', sent['id'], 'goal', 'error', 'the browser run failed (RunnerError)', self.now, self.now))
        self.gateway.script = lambda text, run, gw: {'text': 'I could not open the shop.'}
        self.worker.tick()
        self.assertEqual(self.request(sent['id'])['outcome'], 'partial')
        row, = self.faults(sent['id'])
        self.assertEqual((row['reason'], json.loads(row['detail_json'])), ('browser.failed', {'exception': 'RunnerError', 'state': 'error'}))

    def test_a_clean_answer_and_a_stop_by_the_customer_leave_nothing(self):
        done = self.run_message('hello', ['hi'])
        self.assertEqual(self.request(done['id'])['outcome'], 'completed')
        claim_me = self.say('again', key='k2')
        claim = self.queue.claim(owner='w', capacity=OK)
        self.queue.finish(claim, self.driver._close(claim, 'cancelled', 'Cancelled before execution', verdict=Verdict('cancelled', 'not_applicable', 'Stopped at your request.', '')))
        self.assertEqual(self.request(claim_me['id'])['state'], 'cancelled')
        self.assertEqual(self.faults(), [])

    def test_a_request_whose_fault_cannot_be_written_still_ends(self):
        sent = self.say()
        claim = self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute('DROP TABLE faults')
        receipt = self.driver._close(claim, 'failed', 'x', verdict=Verdict('failed', 'unverified', 'x', ''), fault=faults.Fault('cell.unreachable'))
        self.queue.finish(claim, receipt)
        self.assertEqual(self.request(sent['id'])['state'], 'failed')


class OneReason(Base):
    """Part 2: a run the runtime ended in an error has ONE reason, taken from facts before words, and every place that says why says the same sentence."""
    RUNTIME = '\u26a0\ufe0f Agent failed before reply: LLM request failed: provider rejected the request schema or tool payload.\nTo view logs, run `openclaw logs --follow` in a terminal.'

    def setUp(self):
        super().setUp()
        from agentai_platform.events import EventService
        self.make_worker(events=EventService(self.store))            # with the timeline, so the error row can be read too

    def fail(self, error_reply=None, calls=(), error=None, key='k1'):
        """Send a message whose run the runtime ends in an error, after these model calls were recorded for it."""
        def script(text, run, gw):
            for status, route in calls:
                model_calls.note(self.store, 'a', {'route': route, 'status': status, 'total_ms': 100}, now=self.now)
            return {'error': error or self.RUNTIME, **({'error_reply': error_reply} if error_reply else {})}
        self.gateway.script = script
        sent = self.say(key=key)
        self.worker.tick()
        return self.request(sent['id'])

    def said(self, row):
        """Everything that tells the customer why: the status line's note, the task's result, the timeline's error row, the notice in the chat."""
        error, = [json.loads(r[0])['summary'] for r in self.rows("SELECT public_payload FROM events WHERE task_id=? AND kind='error'", (row['id'],))]
        notice, = [r[0] for r in self.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='system'", (row['id'],))]
        return row['outcome_note'], row['result'], error, notice

    def reason(self, row):
        return [r['reason'] for r in self.rows('SELECT reason FROM faults WHERE request_id=? ORDER BY created_epoch, rowid', (row['id'],))][-1]

    def test_a_refused_key_of_lumina_s_is_ours_to_fix_and_every_place_says_so_in_the_same_words(self):
        row = self.fail(calls=[(200, 'lumina'), (403, 'lumina')])
        sentence = REASONS['model.lumina_key_refused'].customer
        note, result, error, notice = self.said(row)
        self.assertEqual((row['state'], row['outcome'], note, result, error), ('failed', 'failed', sentence, sentence, sentence))
        self.assertIn(sentence, notice)
        self.assertEqual(self.reason(row), 'model.lumina_key_refused')
        self.assertNotIn('try again.', sentence.split('we have been told')[0])      # it does not send the customer to retry something only the owner can fix

    def test_whose_key_it_was_decides_who_is_asked_to_act(self):
        row = self.fail(calls=[(401, 'own')])
        self.assertEqual((self.reason(row), row['outcome_note']), ('model.own_key_refused', REASONS['model.own_key_refused'].customer))

    def test_a_model_that_is_no_longer_offered_is_the_customer_s_choice_to_change(self):
        row = self.fail(calls=[(404, 'lumina')])
        self.assertEqual(self.reason(row), 'model.not_offered')
        self.assertIn('Settings > Assistant > Models', row['outcome_note'])

    def test_a_last_call_that_worked_is_not_blamed_for_the_failure(self):
        row = self.fail(calls=[(429, 'lumina'), (200, 'lumina')])
        self.assertEqual((self.reason(row), row['outcome_note']), ('run.unclassified', REASONS['run.unclassified'].customer))

    def test_the_runtime_s_own_words_for_a_failed_call_are_never_shown_as_a_reply_and_their_status_is_used(self):
        row = self.fail(error_reply='\u26a0\ufe0f LLM request failed (model not found, HTTP 404).')
        self.assertEqual(self.rows("SELECT count(*) FROM chat_messages WHERE request_id=? AND provenance='agent'", (row['id'],))[0][0], 0)
        self.assertEqual((self.reason(row), row['outcome_note']), ('model.not_offered', REASONS['model.not_offered'].customer))
        for text in self.said(row):
            self.assertNotIn('HTTP', text); self.assertNotIn('LLM', text); self.assertNotIn('openclaw', text)

    def test_with_only_the_runtime_s_status_the_key_is_the_customer_s_when_the_task_ran_on_their_own_model(self):
        self.driver._reserved = lambda claim: 1                          # the own-key marker
        row = self.fail(error_reply='\u26a0\ufe0f LLM request failed (authentication failed, HTTP 401). Re-authenticate the provider and try again.')
        self.assertEqual(self.reason(row), 'model.own_key_refused')

    def test_wording_the_driver_already_knew_keeps_its_reason_whatever_number_came_with_it(self):
        row = self.fail(error='The model request was rate-limited. Please try again in a few minutes.', error_reply='\u26a0\ufe0f LLM request failed (rate limited, HTTP 500).')
        self.assertEqual(self.reason(row), 'model.rate_limited')

    def test_an_answer_that_ended_in_an_error_part_way_is_still_the_assistant_s_answer(self):
        self.gateway.script = lambda text, run, gw: {'text': 'Here is the first half of the report', 'stop_reason': 'error'}
        sent = self.say()
        self.worker.tick()
        self.assertEqual(self.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],))[0][0], 'Here is the first half of the report')

    def test_a_run_the_customer_stopped_is_not_given_a_failure_reason(self):
        sent = self.say()
        claim = self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (sent['id'],))
        self.driver._error_status[sent['id']] = 500
        receipt = self.driver._failed(claim, self.gateway, 'session', {'status': 'error', 'aborted': True, 'error': 'aborted'})
        self.assertEqual((receipt.state, receipt.outcome, self.driver._error_status), ('cancelled', 'cancelled', {}))
        self.assertEqual(self.rows('SELECT count(*) FROM faults')[0][0], 0)


class Released(Base):
    """A browser job the assistant no longer needed (it answered, and no step was coming) is not the browser failing: production 2026-11-23, a task that gave its full
    answer and was labelled "Partly done: the browser could not complete this"."""
    def test_a_page_the_assistant_went_on_without_does_not_make_the_task_partly_done(self):
        from agentai_platform import outcome
        from agentai_platform.browse.job_states import RELEASED_REASON
        ok = {'status': 'ok'}
        for state in ('stopped', 'cancelled'):
            verdict = outcome.judge(native=ok, jobs=[{'state': state, 'reason': RELEASED_REASON, 'url': 'https://shop.example/c/shorts'}])
            self.assertEqual((verdict.outcome, verdict.verification, verdict.note, verdict.line), ('completed', 'not_applicable', 'Done.', ''))
        cart = [{'state': 'stopped', 'reason': RELEASED_REASON, 'url': 'https://shop.example/cart'}]
        added = [{'action': 'click', 'result': 'ok', 'changed': True, 'label': 'Add to cart'}]
        self.assertEqual(outcome.judge(native=ok, jobs=cart, steps=added).verification, 'verified')                 # judged like a job that finished: a cart claim is still checked
        self.assertEqual(outcome.judge(native=ok, jobs=cart).verification, 'unverified')
        for reason in ('no answer to the question', 'stopped by you', ''):                                         # any other stop is still what it was
            self.assertEqual(outcome.judge(native=ok, jobs=[{'state': 'stopped', 'reason': reason}]).outcome, 'partial')

    def test_the_whole_way_through_the_driver(self):
        from agentai_platform.browse.job_states import RELEASED_REASON
        sent = self.say()
        with self.store.connect() as con:
            con.execute('INSERT INTO browse_runs(account_id,request_id,goal,status,reason,url,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?,?)',
                        ('a', sent['id'], 'goal', 'stopped', RELEASED_REASON, 'https://shop.example/c/shorts', self.now, self.now))
        self.gateway.script = lambda text, run, gw: {'text': 'The most expensive shorts are four styles tied at one price.'}
        self.worker.tick()
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['outcome'], row['outcome_note']), ('completed', 'completed', 'Done.'))
        self.assertNotIn('Stopped:', row['result'])
        self.assertEqual(self.rows('SELECT count(*) FROM faults')[0][0], 0)


class Kept(Base):
    def test_both_tables_have_a_retention_rule_and_are_swept_after_thirty_days(self):
        with self.store.connect() as con:
            self.assertEqual(retention.unassigned(con), [])
            self.assertEqual((retention.rule_of('faults'), retention.rule_of('model_calls'), retention.BY_KEY['diagnostics'].days), ('diagnostics', 'diagnostics', 30))
        for age in (40, 5):
            when = self.now - age * 86400
            faults.record(self.store, 'a', faults.Fault('run.timeout'), now=when)
            model_calls.note(self.store, 'a', {'status': 200}, now=when)
        self.assertEqual(retention.sweep(self.store, now=self.now)['diagnostics'], 2)
        self.assertEqual((self.rows('SELECT count(*) FROM faults')[0][0], self.rows('SELECT count(*) FROM model_calls')[0][0]), (1, 1))

    def test_a_probe_is_marked_and_a_person_s_request_is_not(self):
        sent = self.say()
        self.assertEqual(self.request(sent['id'])['probe'], 0)


class Report(Base):
    """The report and the monitor's facts read the same records: people's requests and the deploy's probes apart, reasons by code, tools, browser jobs, model calls."""
    def seed(self):
        import time
        from agentai_platform.ops import reliability_report
        iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.now - 60))
        with self.store.connect() as con:
            def request(i, outcome, probe=0, state=None, waited=1):
                rid = f'r{i}'
                con.execute("""INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,outcome,created_epoch,claimed_epoch,probe)
                    VALUES ('a',?,?,?,?,?,?,?,?,?,?,?)""", (rid, 'actor-a', 'p-a', rid, 'h', 'PRIVATE message about Dana', state or ('failed' if outcome == 'failed' else 'completed'), outcome,
                                                        self.now - 3600, self.now - 3600 + waited, probe))
                return rid
            request(1, 'completed'); request(2, 'completed', waited=95)
            failed, partial, limited = request(3, 'failed'), request(4, 'partial'), request(5, 'partial')
            request(6, 'failed', probe=1); request(7, 'completed', probe=1)
            request(8, 'failed')                                                      # a bad ending nobody recorded a reason for
            faults.insert(con, 'a', faults.Fault('model.lumina_key_refused', {'status': 403}), request_id=failed, now=self.now - 100)
            faults.insert(con, 'a', faults.Fault('browser.failed', {'exception': 'TimeoutError'}), request_id=partial, now=self.now - 100)
            faults.insert(con, 'a', faults.Fault('task.spending_limit'), request_id=limited, now=self.now - 100)
            faults.insert(con, 'a', faults.Fault('run.unclassified'), request_id='r6', now=self.now - 100)
            faults.insert(con, 'a', faults.Fault('run.timeout'), request_id='old', now=self.now - 40 * 86400)       # outside the window
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p-a','c-a','r1','completed',1000)")
            for n, (tool, status, source) in enumerate([('web_fetch', 'done', 'gateway'), ('web_fetch', 'failed', 'gateway'), ('lumina__lumina_file_deliver', 'failed', 'gateway'),
                                                         ('browser', 'failed', 'router'), ('exec', 'running', 'gateway'), ('lumina__lumina_mcp_abc123_get_tasks', 'done', 'gateway')]):
                con.execute("INSERT INTO events(account_id,task_id,id,sequence,kind,public_payload,created_at) VALUES ('a','r1',?,?,'activity',?,?)",
                            (f'e{n}', n + 1, json.dumps({'tool': tool, 'status': status, 'source': source, 'detail': 'PRIVATE https://shop.example/x'}), iso))
            con.execute("INSERT INTO browse_runs(account_id,request_id,goal,status,reason,created_epoch,updated_epoch) VALUES ('a','r4','PRIVATE goal','running','',?,?)", (self.now - 3600, self.now - 3000))
            con.execute("INSERT INTO browse_runs(account_id,request_id,goal,status,reason,created_epoch,updated_epoch) VALUES ('a','r1','goal','done','PRIVATE answer',?,?)", (self.now - 3600, self.now - 3000))
        model_calls.note(self.store, 'a', {'route': 'lumina', 'status': 200, 'waited_ms': 0, 'answer_ms': 2000, 'total_ms': 9000, 'input_tokens': 1000, 'output_tokens': 50, 'cached_tokens': 800}, now=self.now - 50)
        model_calls.note(self.store, 'a', {'route': 'lumina', 'status': 200, 'waited_ms': 7000, 'answer_ms': 9000, 'total_ms': 12000}, now=self.now - 50)
        model_calls.note(self.store, 'a', {'route': 'own', 'status': 401, 'answer_ms': 300, 'total_ms': 300}, now=self.now - 50)
        return reliability_report

    def test_the_report_counts_people_and_probes_apart_and_names_every_reason(self):
        report = self.seed().build(self.store.path, days=30, now=self.now)
        people, probes = report['requests']['people'], report['requests']['probes']
        self.assertEqual((people['total'], people['ended_badly'], people['failed'], people['partial']), (6, 4, 2, 2))
        self.assertEqual((probes['total'], probes['ended_badly']), (2, 1))
        errors = {r['reason']: r for r in report['reasons']['errors']}
        self.assertEqual(sorted(errors), ['browser.failed', 'model.lumina_key_refused', 'model.own_key_refused', 'run.unclassified'])
        self.assertEqual((errors['model.lumina_key_refused']['kind'], errors['model.lumina_key_refused']['actor']), ('needs_owner', 'owner'))
        self.assertEqual([r['reason'] for r in report['reasons']['expected_stops']], ['task.spending_limit'])
        self.assertEqual((report['reasons']['unclassified'], report['reasons']['bad_endings_without_a_reason']), (1, 1))

    def test_tools_browser_model_calls_and_starts(self):
        report = self.seed().build(self.store.path, days=30, now=self.now)
        tools = {t['tool']: (t['finished'], t['failed']) for t in report['tools']}
        self.assertEqual(tools, {'web_fetch': (2, 1), 'lumina_file_deliver': (1, 1), 'lumina_mcp_(a connected tool)': (1, 0)})     # the router's mirror and a call still running are not counted
        self.assertEqual((report['browser']['jobs'], report['browser']['by_end_state'], report['browser']['still_running_after_their_task_ended']), (2, {'running': 1, 'done': 1}, 1))
        calls = report['model_calls']
        self.assertEqual((calls['calls'], calls['failed'], calls['failed_by_status'], calls['calls_that_waited_for_a_busy_provider']), (3, 1, {'own 401': 1}, 1))
        self.assertEqual((calls['input_tokens'], calls['cached_input_tokens'], calls['output_tokens'], calls['calls_with_token_counts']), (1000, 800, 50, 1))
        self.assertEqual(calls['seconds_until_the_answer_began'], {'median': 2.0, 'p90': 9.0})
        self.assertEqual((report['starts']['requests'], report['starts']['waited_over_a_minute'], report['starts']['longest_seconds']), (6, 1, 95))

    def test_nothing_a_customer_wrote_or_visited_is_in_the_report(self):
        module = self.seed()
        for out in (module.main(self.store.path, now=self.now), module.main(self.store.path, as_json=True, now=self.now)):
            self.assertNotIn('PRIVATE', out)
            self.assertNotIn('shop.example', out)
            self.assertNotIn('abc123', out)
        self.assertIn("People's requests: 6. Ended badly: 4 of 6 (67%)", module.main(self.store.path, now=self.now))

    def test_a_database_from_before_this_release_gives_an_empty_report_not_an_error(self):
        module = self.seed()
        with self.store.connect() as con:
            con.execute('DROP TABLE faults'); con.execute('DROP TABLE model_calls')
        report = module.build(self.store.path, now=self.now)
        self.assertEqual((report['reasons']['errors'], report['model_calls']), ([], {}))
        self.assertIn('Reliability', module.text(report))

    def test_the_monitor_s_facts_are_the_owner_s_failures_and_the_stale_jobs(self):
        from agentai_platform.ops.hostprobe import HostProbe
        self.seed()
        facts = HostProbe({'app_db': str(self.store.path)}, None, clock=lambda: self.now).task_facts()
        self.assertEqual(facts['owner_faults'], {'browser.failed': 1, 'model.lumina_key_refused': 1, 'run.unclassified': 1})      # the customer's own refused key and their spending limit are not the owner's
        self.assertEqual((facts['requests'], facts['ended_badly'], facts['stale_children']), (6, 4, 1))


if __name__ == '__main__':
    unittest.main()
