"""Roadmap #78 / #79 engines: a schedule runs at most once per local day, under the customer's own limits, never waits for a person, and never does what the customer could not approve.
Each test is one of the enforcement cases the owner switch `customer_schedules` depends on."""
import datetime as dt
import json
import tempfile
import threading
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from agentai_platform.budget import BudgetLedger
from agentai_platform.capacity import CapacityResult
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.chat_driver import ChatDriver, synthetic_gateway_factory
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.request_queue import RequestQueue
from agentai_platform.request_worker import RequestWorker
from agentai_platform.schedule_engine import ScheduleEngine
from agentai_platform.schedules import MAX_SCHEDULES, ScheduleDisabled, ScheduleService
from agentai_platform.security import NotFound, Principal
from agentai_platform.store import Store
from agentai_platform.watchers import WatcherService

OK = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': 0, 'period_microusd': 10**12, 'daily_microusd': 10**12, 'task_microusd': 5000000, 'max_queued_tasks': 3}
ZONE = ZoneInfo('Europe/Berlin')


def epoch(day, hour, minute=0):
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=ZONE).timestamp()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = epoch(16, 7, 55)
        self.queue = RequestQueue(self.store, clock=lambda: self.now, require_cell=True)
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10**12, clock=lambda: self.now)
        self.chat = ChatService(self.store, queue=self.queue, ledger=self.ledger, pricer=FixedRoute(1000000), clock=lambda: self.now, execution=True)
        self.a, self.b = Principal('a', 'actor-a', 'customer'), Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in ('a', 'b'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'ready')", (x, 'd-' + x))
                con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,'P')", (x, 'p-' + x))
                con.execute("INSERT INTO entitlements VALUES (?,?,'t','trial',?,datetime(?,'unixepoch'))", (x, 'e-' + x, json.dumps({**LIMITS, 'period_start_epoch': int(self.now) - 10**6}), int(self.now) + 10**7))
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES ('a','op1','d-a','start','completed','k','h',1)")
            con.execute("INSERT INTO cell_slots(account_id,deployment_id,operation_id,state) VALUES ('a','d-a','op1','active')")
        self.schedules = ScheduleService(self.store, enforcement_proven=True, clock=lambda: self.now)
        self.on = [True]
        self.engine = ScheduleEngine(self.store, self.chat, enabled=lambda: self.on[0], clock=lambda: self.now)
        self.gateway = SyntheticGateway()

    def schedule(self, name='Morning brief', *, hour=8, minute=0, who=None, **kw):
        return self.schedules.create(who or self.a, 'p-' + (who or self.a).account_id, name, timezone='Europe/Berlin', hour=hour, minute=minute, prompt=kw.pop('prompt', 'Summarize the news'), **kw)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def runs(self, sid=None):
        return [(r['day'], r['state'], r['reason']) for r in self.rows('SELECT day,state,reason FROM schedule_runs' + (' WHERE schedule_id=?' if sid else '') + ' ORDER BY day', (sid,) if sid else ())]

    def requests(self):
        return self.rows("SELECT * FROM customer_requests WHERE intent='schedule' ORDER BY sequence")

    def worker(self, **kw):
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda: self.now, heartbeat=self.queue.heartbeat, **kw)
        return RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now)


class Fires(Base):
    def test_nothing_runs_while_the_owner_switch_is_off_or_before_the_time(self):
        self.schedule()
        self.on[0] = False
        self.now = epoch(16, 8, 1)
        self.assertEqual(self.engine.tick(), {'enabled': False}); self.assertEqual(self.requests(), [])
        self.on[0] = True; self.now = epoch(16, 7, 59)
        self.assertEqual(self.engine.tick()['fired'], 0); self.assertEqual(self.requests(), [])

    def test_a_due_schedule_starts_one_run_in_its_own_conversation_with_its_own_limits(self):
        sid = self.schedule(timeout_seconds=120, task_budget_microusd=2_000_000)
        self.now = epoch(16, 8, 1)
        self.assertEqual(self.engine.tick()['fired'], 1)
        [request] = self.requests()
        self.assertEqual((request['state'], request['account_id']), ('waiting', 'a'))
        context = json.loads(request['context_json'])
        self.assertEqual((context['schedule'], context['unattended'], context['timeout_seconds'], context['budget_microusd']), (sid, True, 120, 2_000_000))
        self.assertEqual(self.runs(sid), [('2026-11-16', 'started', '')])
        reservation = self.rows('SELECT amount_microusd FROM task_reservations WHERE task_id=?', (request['id'],))[0]['amount_microusd']
        self.assertEqual(reservation, 2_000_000)                                    # the schedule's own spending limit is the run's limit
        conversation = self.rows('SELECT conversation_id FROM schedules WHERE id=?', (sid,))[0]['conversation_id']
        self.assertEqual(request['conversation_id'], conversation)

    def test_at_most_one_run_per_day_across_passes_restarts_and_two_engines(self):
        self.schedule(); self.now = epoch(16, 8, 1)
        engines = [ScheduleEngine(self.store, self.chat, enabled=lambda: True, clock=lambda: self.now) for _ in range(4)]
        threads = [threading.Thread(target=e.tick) for e in engines]
        for t in threads: t.start()
        for t in threads: t.join(10)
        self.assertEqual(len(self.requests()), 1)
        for _ in range(3): self.engine.tick()
        self.assertEqual(len(self.requests()), 1)
        self.now = epoch(17, 8, 2)
        self.engine.tick(); self.engine.tick()
        self.assertEqual(len(self.requests()), 2)                                   # the next local day is a new run

    def test_a_crash_between_the_record_and_the_start_is_finished_once_under_the_same_key(self):
        sid = self.schedule(); self.now = epoch(16, 8, 1)
        with self.store.connect() as con:                                           # the process died right after recording the firing
            con.execute("INSERT INTO schedule_runs(account_id,schedule_id,day,state,reason,created_epoch) VALUES ('a',?,'2026-11-16','firing','',?)", (sid, int(self.now) - 120))
            con.execute("UPDATE schedules SET last_fired_day='2026-11-16' WHERE id=?", (sid,))
        report = self.engine.tick()
        self.assertEqual(report['recovered'], 1); self.assertEqual(len(self.requests()), 1)
        self.engine.tick(); self.engine.tick()
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(self.runs(sid), [('2026-11-16', 'started', '')])

    def test_the_local_day_follows_the_schedules_timezone(self):
        self.schedule(hour=0, minute=30)
        self.now = dt.datetime(2026, 11, 15, 23, 45, tzinfo=dt.timezone.utc).timestamp()      # 00:45 on the 16th in Berlin
        self.assertEqual(self.engine.tick()['fired'], 1)
        self.assertEqual(self.runs()[0][0], '2026-11-16')


class MissedRuns(Base):
    def test_skip_policy_runs_only_inside_the_grace_window_and_records_the_miss(self):
        sid = self.schedule(missed_policy='skip', grace_seconds=900)
        self.now = epoch(16, 8, 10)                                                 # the host was down at 8:00 and is back 10 minutes later
        self.assertEqual(self.engine.tick()['fired'], 1)
        sid2 = self.schedule('Evening', hour=9, missed_policy='skip', grace_seconds=900)
        self.now = epoch(16, 14, 0)                                                 # back five hours late
        report = self.engine.tick()
        self.assertEqual((report['missed'], len(self.requests())), (1, 1))
        self.assertEqual(self.runs(sid2), [('2026-11-16', 'missed', 'missed_window')])

    def test_run_once_policy_runs_late_but_only_once_and_never_back_fills(self):
        sid = self.schedule(missed_policy='run_once')
        self.now = epoch(19, 15, 0)                                                 # three days down: one run, not four
        self.assertEqual(self.engine.tick()['fired'], 1)
        self.engine.tick(); self.engine.tick()
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(self.runs(sid), [('2026-11-19', 'started', '')])


class Authority(Base):
    def test_an_expired_grant_denies_and_the_day_says_why(self):
        sid = self.schedule(approve_days=1)
        self.now = epoch(18, 8, 1)                                                  # two days later: the customer's grant has run out
        report = self.engine.tick()
        self.assertEqual((report['denied'], len(self.requests())), (1, 0))
        self.assertEqual(self.runs(sid), [('2026-11-18', 'denied', 'grant_expired')])

    def test_creating_a_schedule_needs_the_proof_flag_valid_input_and_the_customers_own_project(self):
        with self.assertRaises(ScheduleDisabled): ScheduleService(self.store, enforcement_proven=False, clock=lambda: self.now).create(self.a, 'p-a', 'x', timezone='Europe/Berlin', hour=8)
        for bad in ({'hour': 24}, {'timeout_seconds': 5}, {'timeout_seconds': 5000}, {'task_budget_microusd': -1}, {'missed_policy': 'later'}, {'grace_seconds': 1}, {'approve_days': 0}, {'prompt': 'x' * 2001}):
            with self.assertRaises(ValueError): self.schedules.create(self.a, 'p-a', 'x', timezone='Europe/Berlin', **{'hour': 8, **bad})
        with self.assertRaises(ValueError): self.schedules.create(self.a, 'p-a', 'x', timezone='Mars/Base', hour=8)
        with self.assertRaises(NotFound): self.schedules.create(self.a, 'p-b', 'x', timezone='Europe/Berlin', hour=8)
        for n in range(MAX_SCHEDULES): self.schedule(f'S{n}')
        with self.assertRaises(Conflict): self.schedule('one too many')

    def test_a_schedule_never_runs_for_another_account_and_history_is_private(self):
        sid = self.schedule(); self.now = epoch(16, 8, 1); self.engine.tick()
        self.assertEqual({r['account_id'] for r in self.requests()}, {'a'})
        self.assertEqual(len(self.engine.history(self.a, sid)), 1)
        self.assertEqual(self.engine.history(self.b, sid), [])

    def browse_state(self, request_id, status):
        with self.store.connect() as con:
            con.execute('INSERT OR REPLACE INTO browse_runs(account_id,request_id,goal,status,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?)', ('a', request_id, 'goal', status, int(self.now), int(self.now)))

    def test_an_unattended_run_that_needs_a_person_stops_instead_of_waiting_and_says_so(self):
        sid = self.schedule(); self.now = epoch(16, 8, 1); self.engine.tick()
        [request] = self.requests()
        self.gateway.polls = 5
        self.browse_state(request['id'], 'asking')                                  # the assistant's browser asked the customer a question
        worker = self.worker()
        report = worker.tick()
        self.assertNotIn('parked', report)                                          # an ordinary task would be parked and wait for the customer: this one has nobody
        done = self.rows('SELECT state,outcome,outcome_note,parked_reason FROM customer_requests WHERE id=?', (request['id'],))[0]
        self.assertEqual((done['state'], done['outcome'], done['parked_reason']), ('completed', 'blocked', None))
        self.assertIn('needed you', done['outcome_note'])
        self.assertEqual(self.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)
        self.engine.sync()
        self.assertEqual(self.runs(sid), [('2026-11-16', 'blocked', '')])

    def test_the_same_question_in_an_ordinary_task_is_parked_not_stopped(self):
        sent = self.chat.send(self.a, conversation_id=self.chat.create_conversation(self.a, 'p-a')['id'], message='find wings', key='k-plain')
        self.gateway.polls = 5
        self.browse_state(sent['request']['id'] if 'request' in sent else sent['id'], 'asking')
        self.assertEqual(self.worker().tick(), {'ran': 1, 'parked': 'browser_question'})

    def test_the_run_has_the_schedules_own_time_limit_and_is_told_nobody_is_watching(self):
        self.schedule(timeout_seconds=90); self.now = epoch(16, 8, 1); self.engine.tick()
        self.gateway.polls = 5
        self.worker().tick()
        deadline = self.rows('SELECT deadline_epoch,created_epoch FROM chat_deliveries')[0]
        self.assertLessEqual(deadline['deadline_epoch'] - int(self.now), 90)
        sent = self.rows('SELECT payload FROM chat_deliveries')[0]['payload']
        self.assertIn('nobody is watching', sent); self.assertIn('Never act on anything that needs their permission', sent)


class Watchers(Base):
    def observed(self, text):
        import hashlib
        return hashlib.sha256(text.encode()).hexdigest()

    def test_an_unchanged_check_costs_no_model_call_and_starts_nothing(self):
        watchers = WatcherService(self.store, clock=lambda: self.now)
        watcher = watchers.ensure(self.a, 'p-a', 'price page', {'url': 'https://example.org/p'}, 3600)
        sid = self.schedule(watcher_id=watcher)
        first = watchers.observe(self.a, watcher, self.observed('v1'), admit=lambda: True)
        again = watchers.observe(self.a, watcher, self.observed('v1'), admit=lambda: True)
        self.assertEqual((first['reason'], again['reason'], again['model_calls']), ('baseline', 'unchanged', 0))
        self.now = epoch(16, 8, 1)
        self.assertEqual(self.engine.tick()['unchanged'], 1)
        self.assertEqual((len(self.requests()), self.runs(sid)), (0, [('2026-11-16', 'unchanged', 'no_change')]))

    def test_a_change_runs_once_even_across_restarts_and_repeated_observations(self):
        watchers = WatcherService(self.store, clock=lambda: self.now)
        watcher = watchers.ensure(self.a, 'p-a', 'price page', {'url': 'https://example.org/p'}, 3600)
        sid = self.schedule(watcher_id=watcher)
        watchers.observe(self.a, watcher, self.observed('v1'), admit=lambda: True)
        changed = watchers.observe(self.a, watcher, self.observed('v2'), admit=lambda: True)
        self.assertEqual((changed['changed'], changed['escalate']), (True, True))
        for _ in range(3):
            self.assertEqual(WatcherService(self.store, clock=lambda: self.now).observe(self.a, watcher, self.observed('v2'), admit=lambda: True)['escalate'], False)   # a new process, the same observation
        self.now = epoch(16, 8, 1)
        for _ in range(3): self.engine.tick()
        self.assertEqual(len(self.requests()), 1)                                   # one change, one run
        self.assertEqual(self.rows("SELECT state FROM watcher_notifications")[0]['state'], 'delivered')
        self.assertEqual(self.runs(sid), [('2026-11-16', 'started', '')])

    def test_a_denied_change_is_not_lost_and_notifies_once_when_it_is_allowed(self):
        watchers = WatcherService(self.store, clock=lambda: self.now)
        watcher = watchers.ensure(self.a, 'p-a', 'w', {'k': 1}, 3600)
        watchers.observe(self.a, watcher, self.observed('v1'), admit=lambda: True)
        denied = watchers.observe(self.a, watcher, self.observed('v2'), admit=lambda: False)
        self.assertEqual(denied['reason'], 'admission_denied')
        allowed = watchers.observe(self.a, watcher, self.observed('v2'), admit=lambda: True)
        self.assertEqual(allowed['reason'], 'changed')
        self.assertEqual(watchers.observe(self.a, watcher, self.observed('v2'), admit=lambda: True)['escalate'], False)        # and a repeat of it never notifies again


class Proof(unittest.TestCase):
    def test_the_enforcement_flag_rests_on_these_cases(self):
        from agentai_platform import schedules
        names = set(dir(Fires) + dir(MissedRuns) + dir(Authority) + dir(Watchers) + dir(Completion))
        for case in ('test_at_most_one_run_per_day_across_passes_restarts_and_two_engines', 'test_a_crash_between_the_record_and_the_start_is_finished_once_under_the_same_key',
                     'test_a_due_schedule_starts_one_run_in_its_own_conversation_with_its_own_limits', 'test_an_expired_grant_denies_and_the_day_says_why',
                     'test_run_once_policy_runs_late_but_only_once_and_never_back_fills', 'test_an_unattended_run_that_needs_a_person_stops_instead_of_waiting_and_says_so',
                     'test_the_run_has_the_schedules_own_time_limit_and_is_told_nobody_is_watching', 'test_a_schedule_never_runs_for_another_account_and_history_is_private',
                     'test_a_change_runs_once_even_across_restarts_and_repeated_observations', 'test_an_unchanged_check_costs_no_model_call_and_starts_nothing'):
            self.assertIn(case, names)
        self.assertTrue(schedules.ENFORCEMENT_PROVEN)


class Completion(Base):
    def test_a_finished_run_is_recorded_as_completed_and_a_failed_one_as_failed(self):
        sid = self.schedule(); self.now = epoch(16, 8, 1); self.engine.tick()
        self.gateway.script = lambda message, run, gw: {'text': 'brief ready'}
        worker = self.worker()
        for _ in range(3): worker.tick()
        self.engine.sync()
        self.assertEqual(self.runs(sid), [('2026-11-16', 'completed', '')])
        sid2 = self.schedule('Second', hour=9); self.now = epoch(16, 9, 1); self.engine.tick()
        rid = self.requests()[-1]['id']
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='failed' WHERE id=?", (rid,)); con.execute('DELETE FROM request_slots')
        self.engine.sync()
        self.assertEqual(self.runs(sid2), [('2026-11-16', 'failed', '')])

    def test_a_refused_admission_is_recorded_with_a_fixed_reason_and_not_retried_that_day(self):
        sid = self.schedule(); self.now = epoch(16, 8, 1)
        with self.store.connect() as con:
            con.execute("UPDATE entitlements SET status='expired' WHERE account_id='a'")
            con.execute("UPDATE accounts SET status='suspended' WHERE id='a'")
        report = self.engine.tick()
        self.assertEqual((report['fired'], len(self.requests())), (0, 0))
        self.assertEqual(self.runs(sid)[0][0:2], ('2026-11-16', 'refused'))
        self.engine.tick(); self.engine.tick()
        self.assertEqual(len(self.runs(sid)), 1)


if __name__ == '__main__':
    unittest.main()
