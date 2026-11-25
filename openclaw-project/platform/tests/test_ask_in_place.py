"""Asking the customer in place (reliability plan, Part 6): the assistant's question holds its tool call and parks the run, the answer goes straight back to the same
run, and when nobody answers in time the question stays open and resumes as a new turn, as before. The owner's switch `ask_in_place` falls back to today's behaviour."""
import json
import threading
import time

from agentai_platform import handoff
from agentai_platform.connector_tools import ConnectorTools, ask_questions
from agentai_platform.lifecycle.types import Conflict
from tests.connector_fixture import ConnectorBase

SIZES = {'questions': [{'question': 'Which size?', 'options': [{'label': 'M', 'price': '$20'}, {'label': 'L', 'price': '$22', 'details': 'Runs large'}]}]}


class AskInPlace(ConnectorBase):
    def setUp(self):
        super().setUp()
        self.spawned, self.switch = [], True
        test = self

        class Chat:
            def _spawn(self, principal, conversation_id, **kw):
                test.spawned.append(kw)
                return {'id': 'resumed-' + str(len(test.spawned))}
        self.runner.chat = Chat()
        self.tools = ConnectorTools(self.store, self.connectors, self.client, self.actions, self.workflows, clock=lambda: self.now, enabled=lambda a: True,
                                    ask_in_place=lambda a: self.switch, sleep=lambda s: time.sleep(0.005), poll_seconds=0)

    # -- helpers ---------------------------------------------------------------------------------------------------------------------------------
    def ask(self, arguments=SIZES, closed=lambda: False):
        """Call the tool in a thread (it holds the call while it waits); -> (thread, result list)."""
        out = []
        thread = threading.Thread(target=lambda: out.append(self.tools.call('a', arguments, closed, name='lumina_ask_customer', request_id='req-a')), daemon=True)
        thread.start()
        deadline = time.time() + 5
        while not self.rows("SELECT id FROM handoffs WHERE account_id='a'") and time.time() < deadline:
            time.sleep(0.005)
        return thread, out

    def handoff(self):
        return self.rows("SELECT * FROM handoffs WHERE account_id='a'")[0]

    def waiting_in_place(self):
        with self.store.connect() as con:
            return handoff.waiting_in_place(con, 'a', 'req-a', self.now)

    def finish(self, thread, out):
        thread.join(5)
        self.assertFalse(thread.is_alive())
        return out[0]

    # -- the answer comes back to the same run ---------------------------------------------------------------------------------------------------
    def test_an_answer_given_while_the_task_waits_goes_back_to_the_same_run_and_starts_no_second_turn(self):
        thread, out = self.ask()
        self.assertTrue(self.waiting_in_place())                                                    # the driver parks the run on this
        shown = self.runner.handoffs.pending(self.a)[0]
        self.assertEqual(shown['questions'], SIZES['questions'])
        self.assertEqual((shown['question'], shown['options']), ('Which size?', ['M', 'L']))        # what an older reader of the row sees
        answered = self.runner.handoffs.answer(self.a, shown['id'], answers=[{'choice': 'L'}])
        self.assertTrue(answered['in_place'])
        text, problem = self.finish(thread, out)
        self.assertFalse(problem)
        reply = json.loads(text)
        self.assertEqual(reply['answers'], [{'question': 'Which size?', 'answer': 'L'}])
        self.assertIn('Carry on', reply['state'])
        row = self.handoff()
        self.assertEqual((row['state'], row['resumed_request_id']), ('resumed', 'req-a'))
        self.runner.tick()
        self.assertEqual(self.spawned, [])                                                         # the run carried on: no new turn
        self.assertFalse(self.waiting_in_place())

    def test_a_skipped_question_and_answers_in_the_customers_own_words_reach_the_assistant(self):
        thread, out = self.ask({'questions': [{'question': 'Which size?', 'options': ['M', 'L']}, {'question': 'Which colour?'}]})
        self.runner.handoffs.answer(self.a, self.handoff()['id'], answers=[{'skip': True}, {'text': ' navy '}])
        reply = json.loads(self.finish(thread, out)[0])
        self.assertEqual(reply['answers'], [{'question': 'Which size?', 'skipped': True}, {'question': 'Which colour?', 'answer': 'navy'}])
        self.assertIn('skipped', reply['state'])

    # -- nobody answers in time -------------------------------------------------------------------------------------------------------------------
    def test_when_the_window_ends_the_question_stays_open_and_a_later_answer_resumes_as_a_new_turn(self):
        thread, out = self.ask()
        self.now += handoff.IN_PLACE_SECONDS
        text, problem = self.finish(thread, out)
        self.assertFalse(problem)
        self.assertIn('END YOUR TURN', text)
        self.assertFalse(self.waiting_in_place())                                                   # the run is not parked on it any more
        row = self.handoff()
        self.assertEqual(row['state'], 'waiting')
        answered = self.runner.handoffs.answer(self.a, row['id'], answers=[{'choice': 'M'}])
        self.assertFalse(answered['in_place'])
        self.runner.tick()
        self.assertEqual(len(self.spawned), 1)
        self.assertIn('"Which size?": M', self.spawned[0]['message'])

    def test_a_call_that_was_lost_never_takes_the_answer_with_it(self):
        """The tool relay restarted while the call waited: nobody marks the row any more. Within seconds the run is no longer parked on it, and an answer resumes a new turn."""
        with self.coordinator() as con:
            self.runner.handoffs.create(con, account_id='a', actor_id='actor-a', kind='question', request_id='req-a', question='Which size?', options=['M', 'L'],
                                        resume={'question': True, 'in_place': True, 'until': self.now + 500, 'seen': self.now - handoff.SEEN_SECONDS - 1})
        self.assertFalse(self.waiting_in_place())
        self.assertFalse(self.runner.handoffs.answer(self.a, self.handoff()['id'], 'L')['in_place'])
        self.runner.tick()
        self.assertEqual(len(self.spawned), 1)

    def test_a_stopped_task_withdraws_its_question(self):
        thread, out = self.ask()
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET cancel_requested=1 WHERE account_id='a' AND id='req-a'")
        text, problem = self.finish(thread, out)
        self.assertEqual(problem.reason, 'tool.stopped_with_task')
        self.assertEqual(self.handoff()['state'], 'cancelled')
        with self.assertRaises(Conflict):
            self.runner.handoffs.answer(self.a, self.handoff()['id'], 'L')

    def test_a_call_the_runtime_gave_up_on_leaves_the_question_open(self):
        thread, out = self.ask(closed=lambda: True)
        self.finish(thread, out)
        self.assertEqual(self.handoff()['state'], 'waiting')
        self.assertFalse(self.waiting_in_place())
        self.assertFalse(self.runner.handoffs.answer(self.a, self.handoff()['id'], 'L')['in_place'])

    # -- when it does not wait --------------------------------------------------------------------------------------------------------------------
    def test_with_the_switch_off_or_in_a_scheduled_run_the_question_ends_the_turn_as_before(self):
        self.switch = False
        text, problem = self.tools.call('a', SIZES, name='lumina_ask_customer', request_id='req-a')
        self.assertFalse(problem); self.assertIn('END YOUR TURN', text)
        self.assertFalse(self.waiting_in_place())
        self.switch = True
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET context_json=? WHERE account_id='a' AND id='req-a'", (json.dumps({'unattended': True}),))
        text, problem = self.tools.call('a', SIZES, name='lumina_ask_customer', request_id='req-a')
        self.assertIn('END YOUR TURN', text)
        self.assertFalse(self.waiting_in_place())

    def test_a_run_near_the_runtimes_own_limit_does_not_wait_in_place(self):
        with self.store.connect() as con:
            con.execute('''INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,created_epoch,updated_epoch,kind,payload)
                VALUES ('a','req-a',1,'req-a-a1','h','acknowledged','req-a-a1',?,?,'turn','m')''', (self.now - 1150, self.now - 1150))
        text, _ = self.tools.call('a', SIZES, name='lumina_ask_customer', request_id='req-a')
        self.assertIn('END YOUR TURN', text)
        self.assertFalse(self.waiting_in_place())

    # -- what the assistant and the customer may send ---------------------------------------------------------------------------------------------
    def test_a_wrong_question_names_the_field_gives_an_example_and_asks_nothing(self):
        for arguments, field in (({}, '"questions"'), ({'questions': [{'question': 'Size?', 'options': [{'price': '$2'}]}]}, 'questions[0].options[0].label'),
                                 ({'questions': [{'question': 'a'}] * 4}, '"questions"'), ({'question': 'Size?', 'options': ['M', 'M']}, 'different labels')):
            text, problem = self.tools.call('a', arguments, name='lumina_ask_customer', request_id='req-a')
            self.assertEqual(problem.reason, 'tool.bad_arguments')
            self.assertIn(field, text); self.assertIn('Example: {"questions"', text)
        self.assertEqual(self.rows("SELECT count(*) AS n FROM handoffs")[0]['n'], 0)
        self.assertEqual(ask_questions({'question': 'Which?', 'options': ['A']}), [{'question': 'Which?', 'options': [{'label': 'A'}]}])     # the older form still works

    def test_an_answer_must_fit_the_questions(self):
        self.switch = False
        self.tools.call('a', {'questions': [{'question': 'Size?', 'options': ['M']}, {'question': 'Colour?'}]}, name='lumina_ask_customer', request_id='req-a')
        hid = self.handoff()['id']
        for answers in ([{'choice': 'M'}], [{'choice': 'XL'}, {'skip': True}], [{'text': ''}, {'skip': True}], [{'choice': 'M'}, 'red'], 'M'):
            with self.assertRaises(ValueError):
                self.runner.handoffs.answer(self.a, hid, answers=answers)
        self.runner.handoffs.answer(self.a, hid, answers=[{'choice': 'M'}, {'skip': True}])
        self.runner.tick()
        self.assertIn('"Colour?": skipped', self.spawned[0]['message'])

    def coordinator(self):
        return self.runner.handoffs.coordinator.transaction()
