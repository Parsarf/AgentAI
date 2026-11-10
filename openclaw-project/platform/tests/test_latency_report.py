"""deploy/latency_report.py against a fixture database built from the REAL migrations, with known timestamps."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agentai_platform.store import Store

SPEC = importlib.util.spec_from_file_location('latency_report', Path(__file__).resolve().parents[1] / 'deploy' / 'latency_report.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def at(sec):
    return '2026-01-01T00:%02d:%06.3fZ' % (int(sec // 60), sec % 60)


class Fixture:
    def __init__(self, path):
        self.con = sqlite3.connect(path)
        self.con.execute('PRAGMA foreign_keys=OFF')
        self.seq = 0

    def request(self, rid, account='A', state='completed', epoch=0):
        self.con.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,created_epoch) VALUES (?,?,?,?,?,?,?,?,?)",
                         (account, rid, 'u', 'p', 'k' + rid, 'h', 'PRIVATE-MESSAGE-TEXT', state, epoch))

    def audit(self, account, rid, action, sec):
        self.seq += 1
        self.con.execute("INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (account, 'a%d' % self.seq, 'u', rid, 'lifecycle.' + action, 'completed', 'random%d' % self.seq, at(sec)))

    def event(self, account, rid, kind, sec, payload='{}'):
        self.seq += 1
        self.con.execute("INSERT INTO events(account_id,task_id,id,sequence,kind,public_payload,created_at) VALUES (?,?,?,?,?,?,?)", (account, rid, 'e%d' % self.seq, self.seq, kind, payload, at(sec)))

    def agent_row(self, account, rid, sec, provenance='agent'):
        self.seq += 1
        self.con.execute("INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content,native_message_id,created_at) VALUES (?,?,?,?,?,?,?)",
                         (account, 'c', rid, provenance, 'PRIVATE-REPLY-TEXT', 'n%d' % self.seq, at(sec)))


class LatencyReportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        (Path(self.dir.name) / 'state').mkdir(mode=0o700)
        self.path = Path(self.dir.name) / 'state' / 'db.sqlite3'
        Store(self.path).initialize()
        f = Fixture(self.path)
        # R1: normal, three assistant rows
        f.request('R1'); f.audit('A', 'R1', 'chat.send', 10.0); f.audit('A', 'R1', 'request_claim', 12.5)
        f.event('A', 'R1', 'task_started', 13.0); f.event('A', 'R1', 'progress', 14.2, '{"step":"working","summary":"x"}'); f.event('A', 'R1', 'progress', 15.0, '{"step":"other"}')
        for s in (20.7, 25.0, 31.0): f.agent_row('A', 'R1', s)
        f.agent_row('A', 'R1', 11.0, provenance='customer')            # the customer's own row must not count as a reply
        f.audit('A', 'R1', 'request_finish', 31.4)
        # R2: waits behind R1 (slot overlap) with a cell start queued meanwhile; steered at 40.0
        f.request('R2'); f.audit('A', 'R2', 'chat.send', 15.0); f.audit('A', 'R2', 'request_claim', 31.6)
        f.event('A', 'R2', 'task_started', 32.0); f.event('A', 'R2', 'progress', 33.0, '{"step":"working"}')
        f.agent_row('A', 'R2', 35.0); f.audit('A', 'R2', 'chat.steer', 40.0); f.agent_row('A', 'R2', 45.5); f.audit('A', 'R2', 'request_finish', 46.0)
        f.con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation,created_at) VALUES ('A','op1','d','start','completed','ik','rh',1,?)", (at(20.0),))
        # R3: incomplete (claimed and prepared, then nothing)
        f.request('R3', state='running'); f.audit('A', 'R3', 'chat.send', 50.0); f.audit('A', 'R3', 'request_claim', 51.0); f.event('A', 'R3', 'task_started', 51.5)
        # R4: no chat.send audit (epoch only), never claimed
        f.request('R4', state='waiting', epoch=100)
        # R5: finished before its first row (ordering problem) -> flagged
        f.request('R5'); f.audit('B', 'R5', 'chat.send', 60.0); f.audit('B', 'R5', 'request_claim', 61.0); f.agent_row('B', 'R5', 70.0); f.audit('B', 'R5', 'request_finish', 65.0)
        f.con.execute("UPDATE customer_requests SET account_id='B' WHERE id='R5'")
        f.con.commit(); f.con.close()
        self.con = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True)

        def deny(action, a1, a2, db, source):       # prove the report never reads message / reply / result text
            if action == sqlite3.SQLITE_READ and (a1, a2) in {('chat_messages', 'content'), ('customer_requests', 'message'), ('customer_requests', 'result')}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.con.set_authorizer(deny)
        self.rows = {r['request']: r for r in report.collect(self.con, 50)}

    def tearDown(self):
        self.con.close(); self.dir.cleanup()

    def test_normal_request_known_spans(self):
        r = self.rows['R1']
        self.assertEqual((r['accepted_to_claimed'], r['claimed_to_prepared'], r['prepared_to_submitted'], r['claimed_to_submitted']), (2.5, 0.5, 1.2, 1.7))
        self.assertEqual(r['accepted_to_submitted'], 4.2)          # one direct difference, not a sum of stage medians
        self.assertEqual((r['submitted_to_first_row'], r['first_row_to_finished'], r['accepted_to_finished'], r['claimed_to_finished']), (6.5, 10.7, 21.4, 18.9))
        self.assertEqual((r['first_row_to_last_row'], r['last_row_to_finished']), (10.3, 0.4))
        self.assertEqual(r['rows'], 3)                   # three assistant rows; the customer's row is excluded
        self.assertEqual(r['accepted_src'], 'audit')

    def test_wait_behind_another_run_is_evidenced_not_assumed(self):
        r = self.rows['R2']
        self.assertEqual(r['accepted_to_claimed'], 16.6)
        self.assertEqual(r['slot_overlap'], ['R1'])
        self.assertEqual(r['cell_ops'], ['start'])
        self.assertEqual(self.rows['R1']['slot_overlap'], [])      # nothing held the slot when R1 waited

    def test_steer_is_measured_separately(self):
        r = self.rows['R2']
        self.assertEqual(r['steers'], 1)
        self.assertEqual(r['steer_to_next_row'], [5.5])
        self.assertEqual(r['accepted_to_finished'], 31.0)

    def test_incomplete_run_has_none_not_zero(self):
        r = self.rows['R3']
        self.assertEqual(r['claimed_to_prepared'], 0.5)
        for key in ('prepared_to_submitted', 'submitted_to_first_row', 'first_row_to_finished', 'accepted_to_finished', 'claimed_to_finished'):
            self.assertIsNone(r[key], key)
        self.assertEqual(r['rows'], 0)

    def test_epoch_fallback_and_missing_claim(self):
        r = self.rows['R4']
        self.assertEqual(r['accepted_src'], 'epoch')
        self.assertIsNone(r['accepted_to_claimed'])
        self.assertIsNone(r['slot_overlap'])

    def test_negative_span_is_flagged(self):
        r = self.rows['R5']
        self.assertEqual(r['first_row_to_finished'], -5.0)
        self.assertIn('first_row_to_finished', r['flags'])


if __name__ == '__main__':
    unittest.main()
