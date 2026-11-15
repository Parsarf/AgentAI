"""Roadmap #2: a reply that ends because the model hit its output limit is carried on in the same task, a bounded number of times, and the customer is told."""
import unittest

from agentai_platform.chat_driver import CUTOFF_CONTINUES, CUTOFF_TEXT
from tests.test_request_worker import RequestWorkerChecks


class CutOffChecks(unittest.TestCase):
    hold_cell = RequestWorkerChecks.hold_cell

    def setUp(self):
        RequestWorkerChecks.setUp(self)
        from agentai_platform.chat_driver import ChatDriver, synthetic_gateway_factory
        from agentai_platform.events import EventService
        from agentai_platform.request_worker import RequestWorker
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda: self.now,
                            events=EventService(self.store, clock=lambda: self.now), heartbeat=self.queue.heartbeat)
        self.worker = RequestWorker(self.queue, driver, lambda: __import__('tests.test_request_worker', fromlist=['OK']).OK, clock=lambda: self.now)

    def run_script(self, script, key='k1'):
        self.gateway.script = script
        self.chat.send(self.a, conversation_id='c-a', message='write the long report', key=key); self.hold_cell()
        for _ in range(4):
            self.worker.tick()
        with self.store.connect() as con:
            request = con.execute('SELECT id,state FROM customer_requests').fetchone()
            deliveries = con.execute('SELECT attempt,kind,payload FROM chat_deliveries WHERE request_id=? ORDER BY attempt', (request['id'],)).fetchall()
            notes = [r[0] for r in con.execute("SELECT public_payload FROM events WHERE task_id=? AND kind='progress'", (request['id'],)).fetchall()]
        return request, deliveries, notes

    def test_a_cut_off_reply_is_continued_once_and_the_task_then_finishes(self):
        def script(message, run, gateway):
            return {'text': 'Part one. ', 'stop_reason': 'length'} if message != CUTOFF_TEXT else {'text': 'Part two.'}
        request, deliveries, notes = self.run_script(script)
        self.assertEqual(request['state'], 'completed')
        self.assertEqual([d['payload'] == CUTOFF_TEXT for d in deliveries], [False, True])
        self.assertTrue(any('length limit' in n for n in notes))
        with self.store.connect() as con:
            texts = [r[0] for r in con.execute("SELECT content FROM chat_messages WHERE provenance='agent' ORDER BY id")]
        self.assertEqual(texts, ['Part one.', 'Part two.'])

    def test_a_normal_stop_is_never_continued(self):
        request, deliveries, _ = self.run_script(lambda message, run, gateway: {'text': 'All done.'})
        self.assertEqual((request['state'], len(deliveries)), ('completed', 1))

    def test_continuing_is_bounded(self):
        request, deliveries, notes = self.run_script(lambda message, run, gateway: {'text': 'More. ', 'stop_reason': 'length'})
        self.assertEqual(len(deliveries), 1 + CUTOFF_CONTINUES)                 # the first turn plus at most three automatic continuations
        self.assertEqual(request['state'], 'completed')
        self.assertTrue(any('several times' in n for n in notes))               # and the customer is told it stopped continuing


if __name__ == '__main__':
    unittest.main()
