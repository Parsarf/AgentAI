"""The one customer-facing picture of a task (work.py), the push gateway that streams it (live/push.py), and its tickets."""
import http.client
import json
import threading
import time
import unittest

from agentai_platform import work
from agentai_platform.events import EventService
from agentai_platform.live import ticket
from agentai_platform.live.push import PushGateway, make_server
from agentai_platform.security import NotFound, Principal
from .test_native_run import Base, OK

SECRET = b's' * 40


def ev(seq, kind, at='2026-11-13T10:00:00.000Z', **payload):
    return {'sequence': seq, 'kind': kind, 'payload': payload, 'created_at': at}


def act(seq, ref, status='running', category='search', at='2026-11-13T10:00:00.000Z', **extra):
    return ev(seq, 'activity', at, ref=ref, status=status, category=category, label={'search': 'Searched the web', 'command': 'Ran a command', 'read': 'Opened a page', 'file': 'Wrote a file'}.get(category, 'Used a tool'), **extra)


class TimelineChecks(unittest.TestCase):
    def test_a_tool_call_is_one_row_that_its_result_closes(self):
        rows = work.timeline([act(1, 'c1', detail='lumina pricing'), act(2, 'c1', 'done', detail='lumina pricing', at='2026-11-13T10:00:02.500Z')])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['status'], rows[0]['first'], rows[0]['seq'], rows[0]['ended_at'] - rows[0]['at']), ('done', 1, 2, 2500))

    def test_calls_that_overlap_stay_separate_and_are_grouped_and_finishing_one_does_not_finish_the_other(self):
        rows = work.timeline([act(1, 'a'), act(2, 'b', category='read'), act(3, 'a', 'done'), act(4, 'c', category='command')])
        by = {r['key']: r for r in rows}
        self.assertEqual((by['a']['status'], by['b']['status'], by['c']['status']), ('done', 'running', 'running'))
        self.assertEqual(by['a']['group'], by['b']['group'])
        self.assertIsNotNone(by['a']['group'])
        self.assertEqual(by['c']['group'], by['a']['group'])          # c started while b was still running

    def test_calls_one_after_another_are_not_grouped(self):
        rows = work.timeline([act(1, 'a'), act(2, 'a', 'done'), act(3, 'b'), act(4, 'b', 'failed', output='exit 1')])
        self.assertEqual([r['group'] for r in rows], [None, None])
        self.assertEqual((rows[1]['status'], rows[1]['output']), ('failed', 'exit 1'))

    def test_notes_errors_files_and_permission_prompts_are_rows_and_housekeeping_is_not(self):
        rows = work.timeline([ev(1, 'progress', summary='transcript update'), ev(2, 'progress', summary='Your message was added to the task that is running.'),
                              ev(3, 'error', summary='The page did not load.'), ev(4, 'artifact', name='report.pdf', artifact_id='x', version=1),
                              ev(5, 'approval_request', request_id='call1', summary='Asked to use create issue on Linear'), ev(6, 'approval_decision', request_id='call1', decision='approved'),
                              ev(7, 'task_steps', mode='direct', steps=[]), ev(8, 'result', summary='done')])
        self.assertEqual([(r['kind'], r['status']) for r in rows], [('note', 'note'), ('error', 'failed'), ('file', 'done'), ('approval', 'approved')])
        self.assertEqual(rows[3]['seq'], 6)

    def test_the_cursor_returns_only_rows_touched_after_it(self):
        events = [act(1, 'a'), act(2, 'b'), act(3, 'a', 'done')]
        rows = work.timeline(events)
        self.assertEqual([r['key'] for r in rows if r['seq'] > 2], ['a'])           # a changed after 2; b did not


class BrowserSteps(unittest.TestCase):
    """The browser's own steps are part of the browser call they were taken in, in a customer's words (reliability plan, Part 4). The sequence is one read from
    production (2026-11-24): each call was shown as "Used the browser" beside a second row "Clicked “Men” · JEV"."""
    def step(self, seq, text, **more):
        return {**ev(seq, 'progress', f'2026-11-13T10:00:{seq:02d}.000Z', summary=text, **more), 'source': 'browser'}

    def call(self, seq, ref, status='running'):
        return act(seq, ref, status, 'browse', f'2026-11-13T10:00:{seq:02d}.000Z', detail='shop.example')

    def test_a_call_carries_its_steps_and_a_call_of_one_step_is_that_step(self):
        rows = work.timeline([self.call(7, 'c1'), self.step(8, 'Opened https://shop.example/'), self.step(9, 'Clicked “Close” · JEV'), self.step(10, 'Scrolled · JEV'), self.call(12, 'c1', 'done'),
                              self.call(13, 'c2'), self.step(14, 'Typed into “Search” · Assistant'), self.call(20, 'c2', 'done')])
        self.assertEqual([(r['key'], r['label'], [s['label'] for s in r['steps']]) for r in rows],
                         [('c1', 'Used a tool', ['Opened https://shop.example/', 'Clicked “Close”', 'Scrolled']), ('c2', 'Typed into “Search”', [])])
        self.assertEqual(rows[0]['seq'], 12)

    def test_a_step_noted_before_its_call_appears_waits_for_that_call_and_is_never_put_under_an_earlier_one(self):
        events = [self.call(1, 'c1'), self.step(2, 'Clicked “Men” · JEV'), self.step(3, 'Scrolled · JEV'), self.call(4, 'c1', 'done'), self.step(5, 'Clicked “Filters” · Assistant')]
        rows, upcoming = work.read_timeline(events)
        self.assertEqual(([len(r['steps']) for r in rows], [s['label'] for s in upcoming]), ([2], ['Clicked “Filters”']))
        rows, upcoming = work.read_timeline(events + [self.call(6, 'c2'), self.call(7, 'c2', 'done')])
        self.assertEqual(([(r['key'], r['label']) for r in rows], upcoming), ([('c1', 'Used a tool'), ('c2', 'Clicked “Filters”')], []))

    def test_when_the_task_is_over_a_step_no_call_followed_is_kept_with_the_last_call(self):
        events = [self.call(1, 'c1'), self.step(2, 'Clicked “Men” · JEV'), self.step(3, 'Scrolled · JEV'), self.call(4, 'c1', 'done'), self.step(5, 'Clicked “Filters” · Assistant'), ev(6, 'result', summary='x')]
        rows, upcoming = work.read_timeline(events)
        self.assertEqual(([s['label'] for s in rows[0]['steps']], rows[0]['seq'], upcoming), (['Clicked “Men”', 'Scrolled', 'Clicked “Filters”'], 5, []))
        alone, upcoming = work.read_timeline([self.step(1, 'Opened https://shop.example/'), ev(2, 'result', summary='x')])
        self.assertEqual(([(r['kind'], r['label']) for r in alone], upcoming), ([('note', 'Opened https://shop.example/')], []))

    def test_a_step_that_did_not_work_says_what_could_not_be_done_and_why_in_plain_words(self):
        row, = work.timeline([self.call(1, 'c1'), self.step(2, 'Clicked “Expand Men” · Assistant (failed: covered)'), self.step(3, 'Clicked “Men” · JEV'), self.call(4, 'c1', 'done')])
        self.assertEqual([(s['label'], s['status']) for s in row['steps']],
                         [('Could not click “Expand Men”: something on the page was covering it', 'failed'), ('Clicked “Men”', 'done')])
        from agentai_platform.browse.adapter import summary_of
        from agentai_platform.browse.words import reworded
        self.assertEqual(summary_of({'kind': 'step', 'by': 'jev', 'action': 'click', 'label': 'Price: High to Low', 'result': 'ok'}), 'Clicked “Price: High to Low”')
        self.assertEqual(summary_of({'kind': 'step', 'by': 'agent', 'action': 'select', 'label': 'Size', 'result': 'no_option'}), 'Could not choose in “Size”: that choice is not on the page')
        self.assertEqual(summary_of({'kind': 'step', 'by': 'agent', 'action': 'click', 'label': 'Buy', 'result': 'a_code_nobody_listed'}), 'Could not click “Buy”: it did not work')
        for old, new in (('Pressed · Assistant', 'Pressed a key'), ('Went back · rule (failed: left_the_site)', 'Could not go back: it would have left the site'),
                         ('Clicked “A · B” · haiku', 'Clicked “A · B”'), ('Clicked “Men”', 'Clicked “Men”'), ('Opened https://shop.example/', 'Opened https://shop.example/')):
            self.assertEqual(reworded(old), new)
        for text in ('Clicked “Men”', 'Could not click “Expand Men”: something on the page was covering it', 'Pressed a key'):
            self.assertNotRegex(text, r'JEV|Assistant|covered\b|\(failed')

    def test_the_browser_s_question_and_other_notes_stay_notes_and_a_limit_reached_is_in_the_record(self):
        rows = work.timeline([self.call(1, 'c1'), self.step(2, 'The browser is waiting for your answer.', step='asking'), self.call(3, 'c1', 'done'),
                              ev(4, 'progress', summary='The assistant has your message and is working on it.', step='working'),
                              ev(5, 'budget', note='Your spending limit for this task was reached.')])
        self.assertEqual([(r['kind'], r['category'], r['label']) for r in rows if r['kind'] != 'tool'],
                         [('note', 'note', 'The browser is waiting for your answer.'), ('note', 'note', 'The assistant has your message and is working on it.'),
                          ('note', 'limit', 'Your spending limit for this task was reached.')])
        self.assertEqual(rows[0]['steps'], [])

    def test_a_long_browser_call_keeps_its_newest_steps(self):
        row, = work.timeline([self.call(1, 'c1')] + [self.step(n, f'Clicked “Item {n}” · JEV') for n in range(2, 92)])
        self.assertEqual((len(row['steps']), row['steps'][-1]['label']), (work.MAX_STEPS, 'Clicked “Item 91”'))


class ChecklistChecks(unittest.TestCase):
    STEPS = [{'id': 'read', 'title': 'Read', 'status': 'done'}, {'id': 'write', 'title': 'Write', 'status': 'running'}, {'id': 'check', 'title': 'Check', 'status': 'pending'}]

    def row(self, state):
        return {'state': state}

    def test_the_newest_valid_report_wins_and_bad_ones_are_ignored(self):
        events = [ev(1, 'task_steps', mode='plan', steps=self.STEPS), ev(2, 'task_steps', mode='nope', steps=self.STEPS), ev(3, 'task_steps', mode='plan', steps=[{'id': 1}])]
        self.assertEqual([s['status'] for s in work.checklist(events, self.row('running'))['steps']], ['done', 'running', 'pending'])
        self.assertIsNone(work.checklist([], self.row('running')))

    def test_a_finished_request_never_shows_a_step_as_still_going(self):
        events = [ev(1, 'task_steps', mode='plan', steps=self.STEPS)]
        self.assertEqual([s['status'] for s in work.checklist(events, self.row('completed'))['steps']], ['done', 'unreported', 'unreported'])
        self.assertEqual([s['status'] for s in work.checklist(events, self.row('failed'))['steps']], ['done', 'failed', 'failed'])
        self.assertEqual([s['status'] for s in work.checklist(events, self.row('cancelled'))['steps']], ['done', 'stopped', 'stopped'])


class VocabularyChecks(unittest.TestCase):
    def row(self, state='running', **kw):
        return {'state': state, 'paused': 0, 'cancel_requested': 0, 'closing': 0, 'parked_reason': None, 'outcome': None, 'verification': None, 'outcome_note': None, 'result': None,
                'goal_mode': 0, 'continue_goal': 0, **kw}

    def test_phases(self):
        self.assertEqual(work.phase_of(self.row('waiting')), 'queued')
        self.assertEqual(work.phase_of(self.row('waiting', paused=1)), 'paused')
        self.assertEqual(work.phase_of(self.row('starting')), 'starting')
        self.assertEqual(work.phase_of(self.row('running')), 'working')
        self.assertEqual(work.phase_of(self.row('running'), waiting_on='approval'), 'needs_you')
        self.assertEqual(work.phase_of(self.row('running', cancel_requested=1), waiting_on='approval'), 'stopping')
        self.assertEqual(work.phase_of(self.row('uncertain')), 'reconnecting')
        self.assertEqual(work.phase_of(self.row('completed', cancel_requested=1)), 'ended')

    def test_finishing_and_being_confirmed_are_worded_apart(self):
        done = lambda verification: work.label_of('ended', self.row('completed', outcome='completed', verification=verification))
        self.assertEqual((done('verified'), done('unverified'), done('not_applicable')), ('Done · confirmed', 'Done · not confirmed', 'Done'))
        self.assertEqual(work.tone_of('ended', self.row('completed', outcome='completed', verification='unverified')), 'unsure')
        self.assertEqual(work.tone_of('ended', self.row('completed', outcome='completed', verification='verified')), 'ok')
        self.assertEqual(work.label_of('ended', self.row('completed', outcome='partial')), 'Partly done')
        self.assertEqual(work.label_of('ended', self.row('completed', outcome='partial', continue_goal=1)), 'Continuing towards your goal')
        self.assertEqual(work.tone_of('ended', self.row('completed', outcome='blocked')), 'bad')
        self.assertEqual(work.label_of('ended', self.row('cancelled', outcome='cancelled')), 'Stopped')

    def test_controls(self):
        self.assertEqual({k for k, v in work.controls_of(self.row('running')).items() if v}, {'stop', 'steer'})
        self.assertEqual({k for k, v in work.controls_of(self.row('running', cancel_requested=1)).items() if v}, set())
        self.assertEqual({k for k, v in work.controls_of(self.row('waiting')).items() if v}, {'stop', 'pause'})
        self.assertEqual({k for k, v in work.controls_of(self.row('waiting', paused=1)).items() if v}, {'stop', 'resume'})
        self.assertEqual({k for k, v in work.controls_of(self.row('failed')).items() if v}, {'retry'})
        self.assertEqual({k for k, v in work.controls_of(self.row('completed', goal_mode=1, outcome='partial')).items() if v}, {'goal_resume', 'goal_clear'})


class ReaderChecks(Base):
    def setUp(self):
        super().setUp()
        self.reader = work.WorkReader(self.store, clock=lambda: self.now)
        self.events = EventService(self.store)
        self.sent = self.say('Find the cheapest flight to Lisbon', 'w1')
        self.id = self.sent['id']

    def claim(self):
        claim = self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='running' WHERE id=?", (self.id,))
        return claim

    def emit(self, kind, **payload):
        return self.events.append('a', self.id, kind, payload, 'gateway')

    def test_a_waiting_task_is_queued_and_can_be_paused_or_stopped(self):
        view = self.reader.listing(self.a)['tasks'][0]
        self.assertEqual((view['phase'], view['tone'], view['attention']), ('queued', 'pending', None))
        self.assertTrue(view['controls']['pause'] and view['controls']['stop'])
        self.queue.pause(self.a, self.id)
        view = self.reader.listing(self.a)
        self.assertEqual((view['tasks'][0]['phase'], view['tasks'][0]['attention'], view['attention']), ('paused', 'paused', 1))

    def test_a_running_task_says_what_it_is_doing_and_concurrent_calls_are_all_listed(self):
        self.claim()
        waiting = self.reader.listing(self.a)['tasks'][0]
        self.assertEqual((waiting['label'], waiting['waiting_for']), ('Waiting for the model', 'model'))       # no tool is running: the wait is named, not "Thinking"
        self.emit('activity', ref='c1', status='running', category='search', label='Searched the web', detail='flights lisbon', tool='web_search', output='')
        self.emit('activity', ref='c2', status='running', category='read', label='Opened a page', detail='example.com/flights', tool='web_fetch', output='')
        view = self.reader.listing(self.a)['tasks'][0]
        self.assertEqual((view['phase'], view['label']), ('working', 'Reading a page'))
        self.assertEqual([n['label'] for n in view['now']], ['Searching the web', 'Reading a page'])
        self.emit('activity', ref='c2', status='done', category='read', label='Opened a page', detail='example.com/flights', tool='web_fetch', output='')
        self.assertEqual(self.reader.listing(self.a)['tasks'][0]['label'], 'Searching the web')

    def test_while_the_browser_works_the_line_is_its_newest_step(self):
        self.claim()
        self.emit('activity', ref='c1', status='running', category='browse', label='Used the browser', detail='shop.example', tool='lumina_browser', output='')
        self.assertEqual(self.reader.listing(self.a)['tasks'][0]['label'], 'Using the browser')
        self.events.append('a', self.id, 'progress', {'summary': 'Clicked “Men” · JEV'}, 'browser')
        self.events.append('a', self.id, 'progress', {'summary': 'Clicked “Price: High to Low” · JEV'}, 'browser')
        view = self.reader.detail(self.a, self.id)
        self.assertEqual((view['task']['label'], view['task']['activity']['detail'], view['task']['waiting_for']), ('Clicked “Price: High to Low”', 'shop.example', None))
        self.assertEqual([(r['label'], len(r['steps'])) for r in view['rows']], [('Used the browser', 2)])
        self.emit('activity', ref='c1', status='done', category='browse', label='Used the browser', detail='shop.example', tool='lumina_browser', output='')
        self.events.append('a', self.id, 'progress', {'summary': 'Clicked “Filters” · Assistant'}, 'browser')       # the next call's step, noted before its row exists
        view = self.reader.listing(self.a)['tasks'][0]
        self.assertEqual((view['label'], view['activity']['key']), ('Clicked “Filters”', 'browser'))

    def test_a_wait_is_named_from_what_lumina_knows_with_when_it_began_and_how_long_such_a_wait_takes(self):
        view = self.reader.listing(self.a)['tasks'][0]
        self.assertEqual((view['label'], view['waiting_for'], view['expect_seconds']), ('Next in line', None, None))
        self.events.append('a', self.id, 'progress', {'summary': 'Waking your assistant. Its workspace is starting up.', 'step': 'waking'}, 'lifecycle')
        view = self.reader.listing(self.a)['tasks'][0]
        self.assertEqual((view['label'], view['waiting_for'], view['since_epoch'], view['expect_seconds']), ('Waking your workspace', 'workspace', self.sent['created_epoch'] if 'created_epoch' in self.sent else view['created_epoch'], None))
        with self.store.connect() as con:                        # three recent requests met a sleeping workspace: 80, 95 and 120 seconds
            for n, took in enumerate((80, 95, 120, 2)):
                con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,claimed_epoch)
                    VALUES ('b',?, 'actor-b','p-b','c-b',?,'h','x','completed',?,?)''', (f'old{n}', f'k{n}', self.now - 1000 + n, self.now - 1000 + n + took))
        self.assertEqual(self.reader.listing(self.a)['tasks'][0]['expect_seconds'], 95)       # the median of the starts that were cold; the 2-second one was not
        self.claim()
        self.emit('activity', ref='c1', status='done', category='read', label='Opened a page', detail='example.com', tool='web_fetch', output='')
        view = self.reader.detail(self.a, self.id)['task']
        self.assertEqual((view['label'], view['waiting_for']), ('Waiting for the model', 'model'))
        self.assertEqual(view['since_epoch'], round(work._ms(self.rows('SELECT created_at FROM events WHERE task_id=? ORDER BY sequence DESC LIMIT 1', (self.id,))[0][0]) / 1000))
        self.events.append('a', self.id, 'progress', {'summary': 'Waiting a moment for the model provider, then carrying on.', 'step': 'provider_wait', 'detail': '21'}, 'gateway')
        self.now = view['since_epoch'] + 3
        view = self.reader.detail(self.a, self.id)['task']
        self.assertEqual((view['label'], view['waiting_for'], view['expect_seconds']), ('Waiting for the model provider', 'provider', 21))
        self.now = view['since_epoch'] + 60                      # the pause it asked for is long over: the call is going again
        self.assertEqual(self.reader.detail(self.a, self.id)['task']['waiting_for'], 'model')

    def test_a_failed_step_is_listed_with_its_reason_and_marks_the_task_only_when_nothing_made_up_for_it(self):
        self.claim()
        self.emit('activity', ref='c1', status='failed', category='read', label='Opened a page', detail='shop.example/a', tool='web_fetch', output='Web fetch failed (403)', reason='site.refused')
        self.emit('activity', ref='c2', status='done', category='read', label='Opened a page', detail='other.example/a', tool='web_fetch', output='')
        self.emit('activity', ref='c3', status='failed', category='other', label='Prepared a file for you', detail='', tool='lumina_file_deliver', output='x', reason='tool.not_found')
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='completed',outcome='completed',verification='not_applicable' WHERE id=?", (self.id,))
        view = self.reader.detail(self.a, self.id)['task']
        from agentai_platform.faults_registry import REASONS
        self.assertEqual([(f['label'], f['why'], f['recovered']) for f in view['evidence']['failed']],
                         [('Opened a page', REASONS['site.refused'].customer, True), ('Prepared a file for you', REASONS['tool.not_found'].customer, False)])
        self.assertEqual((view['evidence']['failed_steps'], view['evidence']['unrecovered']), (2, 1))
        self.assertEqual(view['trouble'], {'steps': 1, 'why': REASONS['tool.not_found'].customer})
        self.assertEqual(view['label'], 'Done')                  # how it ended is unchanged; the trouble is said beside it

    def test_a_parked_run_says_what_it_waits_for_and_an_unknown_reason_is_not_called_the_browser(self):
        self.claim()
        for reason, label in (('browser_question', 'Waiting for your answer'), ('browser_takeover', 'You have the browser'), ('location_permission', 'Waiting for location permission'),
                              ('something_new', 'Waiting for you')):
            with self.store.connect() as con:
                con.execute('UPDATE customer_requests SET parked_reason=? WHERE id=?', (reason, self.id))
            view = self.reader.listing(self.a)['tasks'][0]
            self.assertEqual((view['phase'], view['label']), ('needs_you', label), reason)

    def test_the_cursor_read_returns_what_was_missed_and_nothing_else(self):
        self.claim()
        self.emit('activity', ref='c1', status='running', category='search', label='Searched the web', detail='q', tool='web_search', output='')
        first = self.reader.detail(self.a, self.id)
        self.assertEqual([r['key'] for r in first['rows']], ['c1'])
        again = self.reader.detail(self.a, self.id, after=first['cursor'])
        self.assertEqual((again['rows'], again['task']['rev']), ([], first['task']['rev']))
        self.emit('activity', ref='c1', status='done', category='search', label='Searched the web', detail='q', tool='web_search', output='')
        self.emit('activity', ref='c2', status='running', category='command', label='Ran a command', detail='ls', tool='exec', output='')
        missed = self.reader.detail(self.a, self.id, after=first['cursor'])
        self.assertEqual([(r['key'], r['status']) for r in missed['rows']], [('c1', 'done'), ('c2', 'running')])
        self.assertNotEqual(missed['task']['rev'], first['task']['rev'])

    def test_a_permission_prompt_makes_the_task_need_the_customer_and_expires_by_itself(self):
        self.claim()
        with self.store.connect() as con:
            con.execute("INSERT INTO mcp_connections(account_id,id,name,url,auth_method,state,created_epoch) VALUES ('a','conn1','Linear','https://mcp.linear.app/mcp','none','ready',?)", (self.now,))
            con.execute("INSERT INTO mcp_calls(account_id,id,connection_id,tool_name,payload_hash,schema_hash,request_id,arguments_json,state,expires_epoch,created_epoch) VALUES ('a','call1','conn1','create_issue','h','s',?,?,'pending',?,?)",
                        (self.id, json.dumps({'title': 'Bug'}), self.now + 600, self.now))
        view = self.reader.detail(self.a, self.id)['task']
        self.assertEqual((view['phase'], view['label'], view['attention']), ('needs_you', 'Waiting for your permission', 'approval'))
        self.assertEqual((view['needs'][0]['tool'], view['needs'][0]['service'], view['needs'][0]['arguments']), ('create_issue', 'Linear', {'title': 'Bug'}))
        self.now += 601
        self.assertEqual(self.reader.detail(self.a, self.id)['task']['phase'], 'working')

    def test_a_browser_waiting_for_the_customer_and_a_location_prompt_need_the_customer(self):
        self.claim()
        with self.store.connect() as con:
            con.execute("INSERT INTO browse_runs(account_id,request_id,goal,status,url,pending_json,created_epoch,updated_epoch) VALUES ('a',?,'g','handoff','https://shop.example/cart',?,?,?)",
                        (self.id, json.dumps({'label': 'Pay now'}), self.now, self.now))
        view = self.reader.detail(self.a, self.id)['task']
        self.assertEqual((view['phase'], view['attention'], view['needs'][0]), ('needs_you', 'browser_handoff', {'kind': 'browser_handoff', 'before': 'Pay now'}))
        self.assertEqual(view['browser'], {'status': 'handoff', 'live': True, 'host': 'shop.example'})
        with self.store.connect() as con:
            con.execute("UPDATE browse_runs SET status='running'")
            con.execute("UPDATE customer_requests SET parked_reason='location_permission' WHERE id=?", (self.id,))
        self.assertEqual(self.reader.detail(self.a, self.id)['task']['label'], 'Waiting for location permission')

    def test_stopping_is_its_own_phase_and_an_ended_task_carries_its_verdict_and_evidence(self):
        self.claim()
        self.emit('activity', ref='c1', status='done', category='read', label='Opened a page', detail='tap.pt/flights', tool='web_fetch', output='')
        self.emit('activity', ref='c2', status='done', category='file', label='Wrote a file', detail='notes/flights.md', tool='write', output='')
        self.emit('activity', ref='c3', status='failed', category='command', label='Ran a command', detail='curl x', tool='exec', output='timeout')
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET cancel_requested=1 WHERE id=?", (self.id,))
        view = self.reader.detail(self.a, self.id)['task']
        self.assertEqual((view['phase'], view['label'], view['controls']['stop']), ('stopping', 'Stopping', False))
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET cancel_requested=0,state='completed',outcome='completed',verification='unverified',outcome_note='Done, but I could not confirm it from the page.' WHERE id=?", (self.id,))
        view = self.reader.detail(self.a, self.id)['task']
        self.assertEqual((view['phase'], view['outcome'], view['verification'], view['label'], view['tone']), ('ended', 'completed', 'unverified', 'Done · not confirmed', 'unsure'))
        self.assertEqual((view['evidence']['steps'], view['evidence']['failed_steps'], view['evidence']['sites'], view['evidence']['files'], view['evidence']['commands']), (3, 1, ['tap.pt'], ['notes/flights.md'], 1))
        self.assertIsNotNone(view['evidence']['duration_s'])

    def test_another_account_cannot_read_a_task_and_a_removed_member_cannot_read_at_all(self):
        with self.assertRaises(NotFound):
            self.reader.detail(Principal('b', 'actor-b', 'customer'), self.id)
        self.assertEqual(self.reader.listing(Principal('b', 'actor-b', 'customer'))['tasks'], [])
        with self.assertRaises(NotFound):
            self.reader.listing(Principal('a', 'someone-else', 'customer'))

    def test_the_list_rev_changes_only_when_something_shown_changes(self):
        first = self.reader.listing(self.a)['rev']
        self.assertEqual(self.reader.listing(self.a)['rev'], first)
        self.queue.pause(self.a, self.id)
        self.assertNotEqual(self.reader.listing(self.a)['rev'], first)


class WorkTicketChecks(unittest.TestCase):
    def test_round_trip_expiry_tamper_and_no_crossover_with_frame_tickets(self):
        now = [1000.0]
        t = ticket.mint_work(SECRET, 'acct', '42', now=lambda: now[0])
        self.assertEqual(ticket.verify_work(SECRET, t, now=lambda: now[0]), ('acct', '42'))
        for bad in (t[:-2] + 'xx', t.replace('w1.', 'v1.', 1), 'nonsense', ticket.mint(SECRET, 'acct', 'b' * 32)):
            with self.assertRaises(ticket.TicketError):
                ticket.verify_work(SECRET, bad, now=lambda: now[0])
        with self.assertRaises(ticket.TicketError):
            ticket.verify_work(b'x' * 40, t, now=lambda: now[0])
        with self.assertRaises(ticket.TicketError):
            ticket.verify(SECRET, t, 'b' * 32)                           # a work ticket is not a frame ticket
        now[0] += ticket.WORK_TTL_SECONDS + 1
        with self.assertRaises(ticket.TicketError):
            ticket.verify_work(SECRET, t, now=lambda: now[0])


def frames(raw: bytes):
    out = []
    for block in raw.decode().split('\n\n'):
        lines = [l for l in block.split('\n') if l and not l.startswith(':')]
        if lines:
            out.append((lines[0].removeprefix('event: '), json.loads(lines[1].removeprefix('data: '))))
    return out


class PushChecks(Base):
    def setUp(self):
        super().setUp()
        self.events = EventService(self.store)
        self.id = self.say('Summarise the report', 'p1')['id']
        self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='running' WHERE id=?", (self.id,))
        self.principal = Principal('a', 'actor-a', 'customer')

    def push(self, **kw):
        ticks = {'n': 0}

        def sleep(seconds):
            ticks['n'] += 1
            for hook in self.hooks.pop(ticks['n'], []):
                hook()
        self.hooks = {}
        clock = {'t': 0.0}

        def monotonic():
            clock['t'] += 0.01
            return clock['t'] + ticks['n'] * 0.25
        return PushGateway(self.store, SECRET, sleep=sleep, monotonic=monotonic, window=kw.pop('window', 2), **kw)

    def collect(self, gateway, **kw):
        return frames(b''.join(gateway.stream(self.principal, **kw)))

    def emit(self, **payload):
        self.events.append('a', self.id, 'activity', {'category': 'search', 'label': 'Searched the web', 'detail': 'q', 'tool': 'web_search', 'output': '', **payload}, 'gateway')

    def test_a_new_tab_gets_the_list_and_the_focused_task_then_changes_as_they_happen_then_reopen(self):
        g = self.push()
        self.hooks = {2: [lambda: self.emit(ref='c1', status='running')], 4: [lambda: self.emit(ref='c1', status='done')]}
        got = self.collect(g, focus=self.id)
        kinds = [k for k, _ in got]
        self.assertEqual(kinds[:3], ['hello', 'list', 'task'])
        self.assertEqual(kinds[-1], 'reopen')
        tasks = [d for k, d in got if k == 'task']
        self.assertEqual([[(r['key'], r['status']) for r in t['rows']] for t in tasks[1:]], [[('c1', 'running')], [('c1', 'done')]])
        self.assertEqual(got[-1][1]['after'], tasks[-1]['cursor'])

    def test_a_reconnect_with_its_cursors_gets_only_what_it_missed(self):
        self.emit(ref='c1', status='running')
        first = self.collect(self.push(window=0.5), focus=self.id)
        cursors = first[-1][1]
        self.emit(ref='c1', status='done')
        self.emit(ref='c2', status='running')
        again = self.collect(self.push(window=0.5), focus=self.id, **cursors)
        tasks = [d for k, d in again if k == 'task']
        self.assertEqual([(r['key'], r['status']) for r in tasks[0]['rows']], [('c1', 'done'), ('c2', 'running')])
        quiet = self.collect(self.push(window=0.5), focus=self.id, **again[-1][1])
        self.assertEqual([k for k, _ in quiet], ['hello', 'reopen'])                    # nothing changed: nothing is sent again

    def test_a_task_of_another_account_is_never_streamed_and_a_removed_member_is_told_to_stop(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,intent) VALUES ('b',?,'actor-b','p-b','c-b','kb','h','secret plan','waiting',?,'chat')",
                        ('f' * 32, self.now))
        got = self.collect(self.push(window=0.5), focus='f' * 32)
        self.assertNotIn('task', [k for k, _ in got])
        self.assertNotIn('secret plan', json.dumps(got))
        with self.store.connect() as con:
            con.execute("UPDATE memberships SET status='revoked' WHERE account_id='a'")
        self.assertEqual([k for k, _ in self.collect(self.push(window=0.5), focus=self.id)], ['hello', 'bye'])

    def test_reply_text_is_streamed_as_additions_for_the_focused_tasks_own_run_only(self):
        script = [{'seq': 3}, {'seq': 4, 'runId': self.id + '-a1', 'itemId': 'm:1', 'text': 'Hel', 'done': False}, {'seq': 5, 'runId': self.id + '-a1', 'itemId': 'm:1', 'text': 'Hello there', 'done': False},
                  {'seq': 6, 'runId': 'f' * 32 + '-a1', 'itemId': 'x:1', 'text': 'someone else', 'done': False}, {'seq': 7, 'runId': self.id + '-a1', 'itemId': 'm:2', 'text': 'Next', 'done': True}]
        asked = []

        def draft(account, after, wait_ms):
            asked.append((account, after))
            return script.pop(0) if script else {'seq': after}
        got = [d for k, d in self.collect(self.push(draft=draft, window=1), focus=self.id) if k == 'draft']
        self.assertEqual([(d['item'], d['at'], d['add'], d['done']) for d in got], [('m:1', 0, 'Hel', False), ('m:1', 3, 'lo there', False), ('m:2', 0, 'Next', True)])
        self.assertTrue(all(account == 'a' for account, _ in asked))
        self.assertEqual(asked[1][1], 3)                                                 # it starts from "now": text written before the tab opened is not replayed

    def test_admission_needs_a_good_ticket_and_caps_streams_per_account(self):
        g = self.push()
        self.assertIsNone(g.admit('nope'))
        good = ticket.mint_work(SECRET, 'a', 'actor-a')
        held = [g.admit(good) for _ in range(6)]
        self.assertTrue(all(isinstance(p, Principal) for p in held))
        self.assertIs(g.admit(good), False)
        g.release(held[0])
        self.assertIsInstance(g.admit(good), Principal)

    def test_over_http_it_is_an_event_stream_and_refuses_everything_else(self):
        g = PushGateway(self.store, SECRET, window=0.6, tick=0.05)
        server = make_server(g, '127.0.0.1', 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        port = server.server_address[1]

        def get(path, method='GET'):
            con = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            con.request(method, path)
            response = con.getresponse()
            body = response.read()
            con.close()
            return response.status, response.getheader('Content-Type'), body
        self.assertEqual(get('/v1/push?t=bad')[0], 403)
        self.assertEqual(get('/v1/other')[0], 404)
        self.assertEqual(get('/v1/push', 'POST')[0], 405)
        status, kind, body = get('/v1/push?t=' + ticket.mint_work(SECRET, 'a', 'actor-a') + '&focus=' + self.id)
        self.assertEqual((status, kind), (200, 'text/event-stream'))
        self.assertEqual([k for k, _ in frames(body)][:3], ['hello', 'list', 'task'])
        self.assertEqual(g._open, {})                                                    # the place is given back when the stream ends


class DecisionChecks(Base):
    """A permission prompt's answer reaches the assistant by itself, and the chat records it as a decision (never as a message the customer wrote)."""

    def messages(self):
        return [(m['provenance'], m['content']) for m in self.rows("SELECT provenance,content FROM chat_messages WHERE conversation_id='c-a' ORDER BY id")]

    def test_a_decision_while_the_task_runs_is_steered_into_it(self):
        sent = self.say('File the bug in Linear', 'd1')
        self.gateway.polls = 2
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._admit(claim); self.gateway.on_wait = None
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])            # the task is running: its first delivery is out
        out = self.chat.continue_after_decision(self.a, sent['id'], approved=True, tool='create_issue', service='Linear', key='approval-call1')
        self.assertTrue(out['steered'])
        self.assertEqual(out['id'], sent['id'])                                          # no second task
        self.assertIn(('system', 'You allowed create issue on Linear.'), self.messages())
        self.assertNotIn('customer', [p for p, c in self.messages() if 'allowed' in c])
        delivery = self.rows("SELECT payload FROM chat_deliveries WHERE request_id=? AND kind='steer'", (sent['id'],))[0]['payload']
        self.assertIn('The customer allowed the request to use create issue on Linear', delivery)
        self.chat.continue_after_decision(self.a, sent['id'], approved=True, tool='create_issue', service='Linear', key='approval-call1')      # a double click adds nothing
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_deliveries WHERE request_id=? AND kind='steer'", (sent['id'],))), 1)

    def test_a_decision_after_the_task_ended_starts_a_turn_named_after_the_task_it_continues(self):
        sent = self.run_message('File the bug in Linear', ['I need your permission to create the issue.'], key='d2')
        out = self.chat.continue_after_decision(self.a, sent['id'], approved=False, tool='create_issue', service='Linear <script>', key='approval-call2')
        self.assertNotEqual(out['id'], sent['id'])
        self.assertEqual(self.messages()[-1], ('system', 'You declined create issue on Linear script. Nothing was run.'))
        row = self.request(out['id'])
        self.assertIn('declined the request to use create issue', row['message'])
        self.assertEqual(json.loads(row['context_json'])['follows'], sent['id'])
        view = work.WorkReader(self.store, clock=lambda: self.now).detail(self.a, out['id'])['task']
        self.assertEqual((view['title'], view['request'], view['follows']), ('File the bug in Linear', 'File the bug in Linear', sent['id']))
        again = self.chat.continue_after_decision(self.a, sent['id'], approved=False, tool='create_issue', service='Linear <script>', key='approval-call2')
        self.assertEqual(again['id'], out['id'])

    def test_nothing_is_continued_for_another_account_or_a_task_without_a_chat(self):
        sent = self.say('File the bug', 'd3')
        with self.assertRaises(NotFound):
            self.chat.continue_after_decision(Principal('a', 'intruder', 'customer'), sent['id'], approved=True, tool='t', key='approval-x')
        self.assertIsNone(self.chat.continue_after_decision(Principal('b', 'actor-b', 'customer'), sent['id'], approved=True, tool='t', key='approval-y'))
        with self.assertRaises(ValueError):
            self.chat.continue_after_decision(self.a, sent['id'], approved='yes', tool='t', key='approval-z')
