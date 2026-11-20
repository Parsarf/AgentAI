"""Changing Google calendars through the action pipeline (roadmap Phase 6, #61 and #63): the Phase 3 write cycle against the fake Google: preview equals payload, one effect
under a retry, a double approval and a lost answer, read-back verification, undo; and the permission it needs (asked on first use) and the calendars it may change."""
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from agentai_platform import google_hub
from agentai_platform.actions import ActionService
from agentai_platform.connector_kit import ConnectorFault, payload_hash
from agentai_platform.google_calendar_writes import event_id_for
from agentai_platform.lifecycle.types import Conflict
from tests.test_google_hub import SCOPES, GoogleBase

EVENT = {'calendar': 'dana@gmail.test', 'title': 'Planning', 'start': '2033-05-20T10:00', 'end': '2033-05-20T11:00', 'timezone': 'America/New_York',
         'attendees': ['bo@y.test', 'cy@z.test'], 'notify': True}


class CalendarWrites(GoogleBase):
    def setUp(self):
        super().setUp()
        self.actions = ActionService(self.store, self.connectors, self.client, clock=lambda: self.now)
        self.connection, _ = self.sign_in()
        self.run_sync()                                                    # the calendars and what this account may do in each are known after the first sync

    def allow(self):
        """The customer gives Lumina the calendar permission, on this account, in place (re-consent on first use)."""
        started = self.connectors.start_link(self.a, 'google', self.redirect, upgrade=self.connection)
        self.g.scope = SCOPES + ' ' + google_hub.EVENTS_SCOPE
        self.assertEqual(self.connectors.finish_link(self.a, started['state'], 'good-code', self.redirect, self.exchange), self.connection)

    def made(self, action):
        return self.g.events['dana@gmail.test'].get(event_id_for(self.rows('SELECT idempotency_key FROM actions WHERE id=?', (action['id'],))[0]['idempotency_key']))

    def inserts(self):
        return [c for c in self.g.calls if c[0] == 'POST' and c[1].endswith('/events')]

    def approve_and_run(self, action):
        self.actions.approve(self.a, action['id'], action['payload_hash'] if 'payload_hash' in action else payload_hash(json.loads(
            self.rows('SELECT payload_json FROM actions WHERE id=?', (action['id'],))[0]['payload_json'])))
        return self.actions.execute('a', action['id'])

    def test_nothing_can_be_prepared_without_the_permission_or_on_a_calendar_this_account_may_only_read(self):
        with self.assertRaises(ConnectorFault) as refused:
            self.actions.propose(self.a, self.connection, 'event.create', EVENT)
        self.assertEqual(refused.exception.kind, 'refused')
        caps = next(a for a in self.hub.accounts(self.a) if a['id'] == self.connection)['capabilities']
        self.assertEqual((caps['event_write'], caps['missing'].get('event_write')), (False, 'calendar_write'))
        self.allow()
        caps = next(a for a in self.hub.accounts(self.a) if a['id'] == self.connection)['capabilities']
        self.assertTrue(caps['event_write'])
        with self.assertRaises(ConnectorFault) as shared:                  # "Team" is shared with this account to read only
            self.actions.propose(self.a, self.connection, 'event.create', {**EVENT, 'calendar': 'team@group.calendar.google.com'})
        self.assertEqual(shared.exception.kind, 'refused')
        with self.assertRaises(ConnectorFault):                            # and another customer reaches nothing of this connection
            self.actions.propose(self.b, self.connection, 'event.create', EVENT)
        self.assertEqual(self.inserts(), [])

    def test_the_write_cycle_one_event_under_retry_double_approval_and_a_lost_answer_then_undo(self):
        self.allow()
        action = self.actions.propose(self.a, self.connection, 'event.create', EVENT)
        preview = action['preview']
        self.assertEqual(action['state'], 'proposed')
        self.assertIn('Planning', preview['summary'])
        self.assertIn('Fri 20 May 2033, 10:00 to 11:00 (America/New_York)', preview['summary'])
        self.assertIn({'field': 'invitations', 'before': None, 'after': '2 people will be invited by email'}, preview['changes'])
        self.assertEqual(self.inserts(), [])                               # preparing sends nothing
        self.assertEqual(self.approve_and_run(action), 'done')
        with self.assertRaises(Conflict):                                  # a second approval of the same change does nothing
            self.actions.approve(self.a, action['id'], payload_hash(EVENT))
        self.assertEqual(self.actions.execute('a', action['id']), 'done')  # and running it again sends nothing
        self.assertEqual(len(self.inserts()), 1)
        made = self.made(action)
        self.assertEqual((made['summary'], made['start']['timeZone'], [p['email'] for p in made['attendees']]), ('Planning', 'America/New_York', ['bo@y.test', 'cy@z.test']))
        self.assertEqual(self.g.updates, ['all'])                          # the invitations were sent, as the preview said
        done = self.actions.get(self.a, action['id'])
        self.assertEqual((done['verified'], done['can_undo']), (True, True))

        # a lost answer: Google made the event, the answer never came; it is read back by its id, never sent again
        lost = self.actions.propose(self.a, self.connection, 'event.create', {**EVENT, 'title': 'Retro', 'start': '2033-05-21T10:00', 'end': '2033-05-21T11:00'})
        self.g.lose_answer = True
        self.assertEqual(self.approve_and_run(lost), 'uncertain')
        self.assertEqual(self.actions.reconcile('a', lost['id']), 'done')
        self.assertEqual(len(self.inserts()), 2)
        self.assertEqual(sum(1 for e in self.g.events['dana@gmail.test'].values() if e['summary'] == 'Retro'), 1)

        # undo: the created event is cancelled, with its version, and the people are told; undoing that puts it back
        undo = self.actions.undo(self.a, action['id'])
        self.assertIn({'field': 'invitations', 'before': None, 'after': '2 people are told it is cancelled'}, undo['preview']['changes'])
        self.assertEqual(self.approve_and_run(undo), 'done')
        self.assertEqual(self.made(action)['status'], 'cancelled')
        deletes = [c for c in self.g.calls if c[0] == 'DELETE']
        self.assertEqual(len(deletes), 1)
        back = self.actions.undo(self.a, undo['id'])
        self.assertEqual(self.approve_and_run(back), 'done')
        again = [e for e in self.g.events['dana@gmail.test'].values() if e['summary'] == 'Planning' and e['status'] != 'cancelled']
        self.assertEqual(len(again), 1)

    def test_an_event_changed_elsewhere_is_not_cancelled_over_the_change(self):
        self.allow()
        action = self.actions.propose(self.a, self.connection, 'event.create', EVENT)
        self.approve_and_run(action)
        made = self.made(action)
        self.g.event_version += 1
        made.update(summary='Planning (moved by Ann)', etag=f'"{self.g.event_version}"', _v=self.g.event_version)       # somebody changed it in Google meanwhile
        undo = self.actions.undo(self.a, action['id'])
        state = self.approve_and_run(undo)
        self.assertNotEqual(state, 'done')
        ended = self.actions.get(self.a, undo['id'])
        self.assertEqual(ended['ended_reason'], 'conflict')
        self.assertEqual(ended['conflict']['current']['title'], 'Planning (moved by Ann)')          # the customer is shown the version that is there now
        self.assertEqual(made['status'], 'confirmed')                      # nothing was cancelled over their change

    def test_the_customers_own_press_is_the_approval_and_an_assistants_change_is_never_recorded_as_direct(self):
        self.allow()
        mine = self.actions.direct(self.a, self.connection, 'event.create', EVENT, screen='calendar')
        self.assertEqual((mine['state'], mine['direct'], mine['approved_by_you']), ('done', 'calendar', True))
        self.assertEqual(len(self.inserts()), 1)
        prepared = self.actions.propose(self.a, self.connection, 'event.create', {**EVENT, 'title': 'Prepared'}, request_id='req-1')
        done = self.actions.get(self.a, prepared['id'])
        self.assertEqual(self.approve_and_run(prepared), 'done')
        self.assertIsNone(self.actions.get(self.a, prepared['id'])['direct'])       # approved on whatever screen: still the assistant's change, never "direct"
        self.assertIsNone(done['direct'])
        undone = self.actions.undo_direct(self.a, mine['id'], screen='calendar')
        self.assertEqual((undone['state'], undone['direct']), ('done', 'calendar'))
        self.assertEqual(self.made(mine)['status'], 'cancelled')
        later = self.actions.direct(self.a, self.connection, 'event.create', {**EVENT, 'title': 'Held'}, screen='calendar', delay_seconds=10)
        self.assertEqual(later['state'], 'approved')                            # waiting its few seconds: nothing has gone
        self.assertEqual(self.actions.cancel(self.a, later['id'])['state'], 'declined')
        self.now += 11
        self.assertEqual(self.actions.execute('a', later['id']), 'declined')
        self.assertFalse(any(e['summary'] == 'Held' for e in self.g.events['dana@gmail.test'].values()))
        with self.assertRaises(ValueError):
            self.actions.direct(self.a, self.connection, 'event.create', EVENT, screen='assistant')

    def test_the_assistant_only_prepares_and_nothing_is_sent_until_the_customer_approves(self):
        from agentai_platform.hub_tools import HubTools
        with self.store.connect() as con:
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','d-a',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p-a','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-a','c-a','d-a')")
            con.execute("""INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
                VALUES ('a','req-a','actor-a','p-a','c-a','k-a','h','m','running',1)""")
        writes = {'on': False}
        tools = HubTools(self.store, self.hub, clock=lambda: self.now, enabled=lambda a: True, actions=self.actions, writes_on=lambda a: writes['on'])
        self.assertNotIn('lumina_calendar_create', {t['name'] for t in tools.specs_for('a')})
        self.assertIn('lumina_calendar_free', {t['name'] for t in tools.specs_for('a')})
        ask = dict(account=self.connection, calendar='dana@gmail.test', title='Planning', start='2033-05-20T10:00', end='2033-05-20T11:00', attendees=['bo@y.test'])
        self.assertTrue(tools.call('a', ask, name='lumina_calendar_create', request_id='req-a')[1])          # writes off: refused, nothing prepared
        writes['on'] = True
        text, is_error = tools.call('a', ask, name='lumina_calendar_create', request_id='req-a')
        self.assertTrue(is_error)
        self.assertIn('Allow changes', text)                                                               # the permission is missing: the customer is told how
        self.allow()
        text, is_error = tools.call('a', ask, name='lumina_calendar_create', request_id='req-a')
        self.assertFalse(is_error, text)
        self.assertIn('NOT DONE', text)
        waiting = self.rows("SELECT id,state,direct_screen,request_id FROM actions")
        self.assertEqual([(r['state'], r['direct_screen'], r['request_id']) for r in waiting], [('proposed', None, 'req-a')])
        self.assertEqual(self.inserts(), [])                                                               # nothing reached Google
        self.assertEqual(json.loads(tools.call('a', ask, name='lumina_calendar_create', request_id='req-a')[0])['prepared'], json.loads(text)['prepared'])
        self.assertEqual(len(self.rows('SELECT 1 FROM actions')), 1)                                      # asked twice in one task: one change

    def test_answering_an_invitation_changes_only_the_customers_own_answer_and_undo_puts_the_old_one_back(self):
        self.allow()
        self.g.event('inv', start={'dateTime': '2033-05-21T15:00:00Z'}, end={'dateTime': '2033-05-21T16:00:00Z'}, summary='Quarterly review',
                     organizer={'email': 'ann@x.test'}, attendees=[{'email': 'ann@x.test', 'organizer': True, 'responseStatus': 'accepted'},
                                                                  {'email': 'dana@gmail.test', 'self': True, 'responseStatus': 'needsAction'},
                                                                  {'email': 'bo@y.test', 'responseStatus': 'tentative'}])
        answer = self.actions.propose(self.a, self.connection, 'event.respond', {'event': 'dana@gmail.test|inv', 'response': 'declined', 'note': 'Travelling that week'})
        self.assertIn('Answer "Not going" to "Quarterly review"', answer['preview']['summary'])
        self.assertIn({'field': 'your answer', 'before': 'Not answered', 'after': 'Not going'}, answer['preview']['changes'])
        self.assertEqual(self.approve_and_run(answer), 'done')
        people = {a['email']: (a['responseStatus'], a.get('comment')) for a in self.g.events['dana@gmail.test']['inv']['attendees']}
        self.assertEqual(people, {'ann@x.test': ('accepted', None), 'dana@gmail.test': ('declined', 'Travelling that week'), 'bo@y.test': ('tentative', None)})
        self.assertTrue(self.actions.get(self.a, answer['id'])['verified'])
        undo = self.actions.undo(self.a, answer['id'])
        self.assertEqual(self.approve_and_run(undo), 'done')
        self.assertEqual(next(a for a in self.g.events['dana@gmail.test']['inv']['attendees'] if a.get('self'))['responseStatus'], 'needsAction')
        # an event changed meanwhile is not answered over the change; an event the customer is not invited to cannot be answered
        again = self.actions.propose(self.a, self.connection, 'event.respond', {'event': 'dana@gmail.test|inv', 'response': 'accepted'})
        self.g.event_version += 1
        self.g.events['dana@gmail.test']['inv'].update(summary='Quarterly review (moved)', etag=f'"{self.g.event_version}"', _v=self.g.event_version)
        self.assertEqual(self.approve_and_run(again), 'failed')
        self.assertEqual(self.actions.get(self.a, again['id'])['ended_reason'], 'conflict')
        self.g.event('mine', start={'dateTime': '2033-05-22T15:00:00Z'}, end={'dateTime': '2033-05-22T16:00:00Z'}, summary='Solo')
        solo = self.actions.propose(self.a, self.connection, 'event.respond', {'event': 'dana@gmail.test|mine', 'response': 'accepted'})
        self.assertNotEqual(self.approve_and_run(solo), 'done')

    def test_a_time_that_does_not_exist_or_an_end_before_the_start_is_refused_before_anything_is_stored(self):
        self.allow()
        for bad in ({**EVENT, 'start': '2033-03-13T02:30', 'end': '2033-03-13T03:30'},        # New York skips 02:00 to 03:00 that night
                    {**EVENT, 'end': '2033-05-20T09:00'}, {**EVENT, 'attendees': ['not an address']}, {**EVENT, 'timezone': 'Mars/Olympus'},
                    {**EVENT, 'recurrence': ['RRULE:FREQ=SECONDLY']}, {**EVENT, 'calendar': 'a|b'}):
            with self.assertRaises(ConnectorFault, msg=bad) as refused:
                self.actions.propose(self.a, self.connection, 'event.create', bad)
            self.assertEqual(refused.exception.kind, 'invalid')
        self.assertEqual(self.rows('SELECT 1 FROM actions'), [])
        day = self.actions.propose(self.a, self.connection, 'event.create', {'calendar': 'dana@gmail.test', 'title': 'Offsite', 'start': '2033-05-23', 'end': '2033-05-25', 'all_day': True})
        self.assertIn('Mon 23 May 2033 to Tue 24 May 2033, all day', day['preview']['summary'])


NY = ZoneInfo('America/New_York')


def at(text):
    return int(datetime.strptime(text, '%Y-%m-%dT%H:%M').replace(tzinfo=NY).timestamp())


class Availability(GoogleBase):
    def setUp(self):
        super().setUp()
        self.now = at('2033-03-07T07:00')                              # a Monday, before the clocks change on Sunday 13 March
        self.g.event('busy1', start={'dateTime': '2033-03-07T10:00:00-05:00'}, end={'dateTime': '2033-03-07T11:00:00-05:00'}, summary='Dentist')
        self.g.event('tent', start={'dateTime': '2033-03-07T14:00:00-05:00'}, end={'dateTime': '2033-03-07T14:30:00-05:00'}, summary='Maybe lunch',
                     attendees=[{'email': 'dana@gmail.test', 'self': True, 'responseStatus': 'tentative'}])
        self.g.event('away', start={'date': '2033-03-09'}, end={'date': '2033-03-10'}, summary='Out of office')
        self.g.event('later', start={'dateTime': '2033-03-21T09:30:00-04:00'}, end={'dateTime': '2033-03-21T10:00:00-04:00'}, summary='Board')
        self.connection, _ = self.sign_in()
        self.run_sync()

    def test_free_time_uses_the_live_answer_working_hours_notice_buffer_and_all_day_events(self):
        free = self.hub.free(self.a, at('2033-03-07T00:00'), at('2033-03-10T00:00'), NY, minutes=30)
        shown = [(datetime.fromtimestamp(a, NY).strftime('%a %H:%M'), datetime.fromtimestamp(b, NY).strftime('%H:%M')) for a, b in free['free']]
        self.assertEqual(shown[:4], [('Mon 09:00', '10:00'), ('Mon 11:00', '14:00'), ('Mon 14:30', '17:00'), ('Tue 09:00', '17:00')])
        self.assertNotIn('Wed', ' '.join(d for d, _ in shown))             # the all-day "Out of office" counts as busy
        self.assertTrue(all(src['live'] for src in free['sources'] if src['calendar'] == 'dana@gmail.test'))
        self.assertTrue(any(c[0] == 'POST' and c[1].endswith('/freeBusy') for c in self.g.calls))
        self.hub.set_availability(self.a, {'buffer_minutes': 15, 'notice_minutes': 180, 'hours': {'tue': None}})
        free = self.hub.free(self.a, at('2033-03-07T00:00'), at('2033-03-09T00:00'), NY, minutes=30)
        shown = [(datetime.fromtimestamp(a, NY).strftime('%a %H:%M'), datetime.fromtimestamp(b, NY).strftime('%H:%M')) for a, b in free['free']]
        self.assertEqual(shown, [('Mon 11:15', '13:45'), ('Mon 14:45', '17:00')])        # not before 10:00 (three hours' notice), 15 minutes kept around each, no Tuesday
        with self.assertRaises(ValueError):
            self.hub.set_availability(self.a, {'hours': {'mon': ['17:00', '09:00']}})

    def test_a_weekly_proposal_across_the_clock_change_reports_only_the_dates_that_clash(self):
        found = self.hub.conflicts(self.a, '2033-03-07T09:30', '2033-03-07T10:30', NY, rule='RRULE:FREQ=WEEKLY;COUNT=3')
        dates = [(datetime.fromtimestamp(o['start_epoch'], NY).strftime('%d %H:%M %Z'), [c['title'] for c in o['conflicts']]) for o in found['occurrences']]
        self.assertEqual(dates, [('07 09:30 EST', ['Dentist']), ('14 09:30 EDT', []), ('21 09:30 EDT', ['Board'])])
        self.assertEqual(found['clashing'], 2)
        maybe = self.hub.conflicts(self.a, '2033-03-07T14:15', '2033-03-07T15:00', NY)['occurrences'][0]['conflicts']
        self.assertEqual([(c['title'], c['tentative']) for c in maybe], [('Maybe lunch', True)])
        self.hub.set_availability(self.a, {'tentative_busy': False})
        self.assertEqual(self.hub.conflicts(self.a, '2033-03-07T14:15', '2033-03-07T15:00', NY)['occurrences'][0]['conflicts'], [])
        self.hub.set_availability(self.a, {'buffer_minutes': 30})
        near = self.hub.conflicts(self.a, '2033-03-07T11:15', '2033-03-07T12:00', NY)['occurrences'][0]['conflicts']
        self.assertEqual([(c['title'], c['buffer_only']) for c in near], [('Dentist', True)])         # back to back without the buffer the customer asked for
        day = self.hub.conflicts(self.a, '2033-03-09T11:00', '2033-03-09T12:00', NY)['occurrences'][0]['conflicts']
        self.assertEqual([(c['title'], c.get('all_day')) for c in day], [('Out of office', True)])


if __name__ == '__main__':
    unittest.main()


SERIES_ZONE = {'timeZone': 'America/New_York'}


class SeriesChanges(GoogleBase):
    """Changing an event and the parts of a repeating series (#62, #63): the customer chooses the scope, and nothing outside it changes; each has its own way back."""
    def setUp(self):
        super().setUp()
        from agentai_platform import hub_model
        self.actions = ActionService(self.store, self.connectors, self.client, clock=lambda: self.now)
        self.connection, _ = self.sign_in()
        self.run_sync()
        started = self.connectors.start_link(self.a, 'google', self.redirect, upgrade=self.connection)
        self.g.scope = SCOPES + ' ' + google_hub.EVENTS_SCOPE
        self.connectors.finish_link(self.a, started['state'], 'good-code', self.redirect, self.exchange)
        self.proving = hub_model.PROVING_IN_THIS_PROCESS
        self.addCleanup(self.proving.clear)
        me = {'email': 'dana@gmail.test', 'self': True, 'responseStatus': 'accepted'}
        self.g.event('one', summary='Planning', start={'dateTime': '2033-05-20T10:00:00-04:00', **SERIES_ZONE}, end={'dateTime': '2033-05-20T11:00:00-04:00', **SERIES_ZONE},
                     attendees=[me, {'email': 'bo@y.test', 'responseStatus': 'accepted'}], location='Room 1')
        self.g.event('wk', summary='Standup', recurrence=['RRULE:FREQ=WEEKLY;COUNT=6'], start={'dateTime': '2033-05-16T09:00:00-04:00', **SERIES_ZONE},
                     end={'dateTime': '2033-05-16T09:30:00-04:00', **SERIES_ZONE}, attendees=[me, {'email': 'bo@y.test'}])
        for day in ('16', '23', '30'):
            self.g.event(f'wk_203305{day}T130000Z', summary='Standup', recurringEventId='wk', start={'dateTime': f'2033-05-{day}T09:00:00-04:00', **SERIES_ZONE},
                         end={'dateTime': f'2033-05-{day}T09:30:00-04:00', **SERIES_ZONE}, attendees=[me, {'email': 'bo@y.test'}])

    def ev(self, eid):
        return self.g.events['dana@gmail.test'][eid]

    def do(self, kind, payload):
        action = self.actions.propose(self.a, self.connection, kind, payload)
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        return action, self.actions.execute('a', action['id'])

    def undo(self, action):
        back = self.actions.undo(self.a, action['id'])
        self.actions.approve(self.a, back['id'], back['payload_hash'])
        return back, self.actions.execute('a', back['id'])

    def test_a_change_is_off_until_proven_then_one_event_changes_once_says_who_is_told_and_undoes(self):
        caps = next(a for a in self.hub.accounts(self.a) if a['id'] == self.connection)['capabilities']
        self.assertEqual((caps['event_write'], caps['event_change'], caps['event_series']), (True, False, False))   # built, not yet proven on the real provider
        change = {'event': 'dana@gmail.test|one', 'title': 'Planning (moved)', 'start': '2033-05-20T14:00', 'end': '2033-05-20T15:00', 'timezone': 'America/New_York', 'notify': True}
        with self.assertRaises(ConnectorFault) as refused:
            self.actions.propose(self.a, self.connection, 'event.update', change)
        self.assertEqual(refused.exception.kind, 'refused')
        self.proving.update({'event_change', 'event_series'})
        action = self.actions.propose(self.a, self.connection, 'event.update', change)
        fields = {c['field']: c for c in action['preview']['changes']}
        self.assertEqual((fields['title']['before'], fields['title']['after']), ('Planning', 'Planning (moved)'))
        self.assertIn('10:00 to 11:00', fields['when']['before'])
        self.assertIn('14:00 to 15:00', fields['when']['after'])
        self.assertEqual(fields['invitations']['after'], '1 person is told about the change')
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.assertEqual(self.actions.execute('a', action['id']), 'done')
        self.assertEqual(self.actions.execute('a', action['id']), 'done')                       # running it again sends nothing
        patches = [c for c in self.g.calls if c[0] == 'PATCH']
        self.assertEqual(len(patches), 1)
        self.assertEqual((self.ev('one')['summary'], self.ev('one')['start']['dateTime'][:16], self.ev('one')['location']), ('Planning (moved)', '2033-05-20T14:00', 'Room 1'))
        self.assertEqual(self.actions.get(self.a, action['id'])['verified'], True)
        self.assertEqual([a['email'] for a in self.ev('one')['attendees']], ['dana@gmail.test', 'bo@y.test'])          # people untouched
        back, state = self.undo(action)
        self.assertEqual(state, 'done')
        self.assertEqual((self.ev('one')['summary'], self.ev('one')['start']['dateTime'][:16]), ('Planning', '2033-05-20T10:00'))
        self.assertEqual(self.actions.get(self.a, back['id'])['verified'], True)

    def test_a_change_made_elsewhere_after_it_was_read_stops_it(self):
        self.proving.add('event_change')
        action = self.actions.propose(self.a, self.connection, 'event.update', {'event': 'dana@gmail.test|one', 'title': 'Mine'})
        self.ev('one').update(summary='Theirs', etag='"elsewhere"')                              # changed at Google after the preview
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.assertEqual(self.actions.execute('a', action['id']), 'failed')
        self.assertEqual(self.actions.get(self.a, action['id'])['ended_reason'], 'conflict')
        self.assertEqual(self.ev('one')['summary'], 'Theirs')

    def test_a_series_change_touches_only_the_chosen_scope(self):
        self.proving.update({'event_change', 'event_series'})
        # this occurrence only
        one, state = self.do('event.update', {'event': 'dana@gmail.test|wk_20330523T130000Z', 'title': 'Standup (demo)', 'notify': False})
        self.assertEqual(state, 'done')
        self.assertEqual([self.ev(e)['summary'] for e in ('wk', 'wk_20330516T130000Z', 'wk_20330523T130000Z', 'wk_20330530T130000Z')],
                         ['Standup', 'Standup', 'Standup (demo)', 'Standup'])
        self.assertIn({'field': 'series', 'before': None, 'after': 'Only this occurrence'}, one['preview']['changes'])
        # the whole series, moved one hour from one occurrence: the series itself moves the same way
        whole, state = self.do('event.update', {'event': 'dana@gmail.test|wk', 'occurrence': 'dana@gmail.test|wk_20330523T130000Z', 'start': '2033-05-23T10:00',
                                                 'end': '2033-05-23T10:30', 'timezone': 'America/New_York', 'notify': False})
        self.assertEqual(state, 'done')
        self.assertEqual((self.ev('wk')['start']['dateTime'][:16], self.ev('wk')['end']['dateTime'][:16]), ('2033-05-16T10:00', '2033-05-16T10:30'))
        self.assertIn({'field': 'series', 'before': None, 'after': 'Every occurrence of the series'}, whole['preview']['changes'])
        self.assertEqual(self.undo(whole)[1], 'done')
        self.assertEqual(self.ev('wk')['start']['dateTime'][:16], '2033-05-16T09:00')

    def test_this_and_later_occurrences_split_the_series_once_under_a_lost_answer_and_undo_puts_it_back(self):
        self.proving.update({'event_change', 'event_series'})
        action = self.actions.propose(self.a, self.connection, 'event.update_rest', {'event': 'dana@gmail.test|wk_20330530T130000Z', 'series': 'dana@gmail.test|wk',
                                                                                          'title': 'Standup v2', 'notify': True})
        self.assertIn({'field': 'series', 'before': None, 'after': 'This and every later occurrence; earlier ones stay as they are'}, action['preview']['changes'])
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.g.lose_answer = True                                                              # the new series is made, the answer is lost
        self.assertEqual(self.actions.execute('a', action['id']), 'uncertain')
        self.assertIn(self.actions.reconcile('a', action['id']), ('done', 'approved'))
        if self.actions.get(self.a, action['id'])['state'] == 'approved':
            self.assertEqual(self.actions.execute('a', action['id']), 'done')                  # sent once more: the same id is answered by Google, no second series
        key = self.rows('SELECT idempotency_key FROM actions WHERE id=?', (action['id'],))[0]['idempotency_key']
        new = self.ev(event_id_for(key))
        self.assertEqual((new['summary'], new['start']['dateTime'][:16], new['recurrence']), ('Standup v2', '2033-05-30T09:00', ['RRULE:FREQ=WEEKLY;COUNT=4']))
        self.assertEqual(self.ev('wk')['recurrence'], ['RRULE:FREQ=WEEKLY;UNTIL=20330530T125959Z'])     # the original ends just before that occurrence
        self.assertEqual(self.ev('wk')['summary'], 'Standup')
        self.assertEqual(len([c for c in self.g.calls if c[0] == 'POST' and c[1].endswith('/events')]), 1)
        self.assertEqual(self.undo(action)[1], 'done')
        self.assertEqual((self.ev(event_id_for(key))['status'], self.ev('wk')['recurrence']), ('cancelled', ['RRULE:FREQ=WEEKLY;COUNT=6']))

    def test_one_occurrence_or_the_rest_of_a_series_is_cancelled_and_put_back(self):
        self.proving.update({'event_change', 'event_series'})
        cancel, state = self.do('event.cancel_one', {'event': 'dana@gmail.test|wk_20330523T130000Z', 'notify': True})
        self.assertEqual(state, 'done')
        self.assertIn('1 person is told it is cancelled', json.dumps(cancel['preview']))
        self.assertEqual([self.ev(e)['status'] for e in ('wk', 'wk_20330516T130000Z', 'wk_20330523T130000Z')], ['confirmed', 'confirmed', 'cancelled'])
        self.assertEqual(self.undo(cancel)[1], 'done')
        self.assertEqual(self.ev('wk_20330523T130000Z')['status'], 'confirmed')
        ended, state = self.do('event.end_series', {'event': 'dana@gmail.test|wk_20330530T130000Z', 'series': 'dana@gmail.test|wk', 'notify': False})
        self.assertEqual(state, 'done')
        self.assertIn('from Mon 30 May 2033 on', ended['preview']['summary'])
        self.assertEqual(self.ev('wk')['recurrence'], ['RRULE:FREQ=WEEKLY;UNTIL=20330530T125959Z'])
        self.assertEqual(self.undo(ended)[1], 'done')
        self.assertEqual(self.ev('wk')['recurrence'], ['RRULE:FREQ=WEEKLY;COUNT=6'])
        whole = self.actions.propose(self.a, self.connection, 'event.delete', {'event': 'dana@gmail.test|wk', 'notify': False})
        self.assertIn('All 6 occurrences of the series are cancelled', json.dumps(whole['preview']))

    def test_a_series_part_names_an_occurrence_of_that_series(self):
        self.proving.update({'event_change', 'event_series'})
        for kind, payload in (('event.update_rest', {'event': 'dana@gmail.test|one', 'series': 'dana@gmail.test|wk', 'title': 'x'}),
                              ('event.end_series', {'event': 'dana@gmail.test|wk_20330530T130000Z', 'series': 'dana@gmail.test|other'}),
                              ('event.cancel_one', {'event': 'dana@gmail.test|one'}),
                              ('event.update', {'event': 'dana@gmail.test|one'})):
            with self.assertRaises((ValueError, ConnectorFault)):
                self.actions.propose(self.a, self.connection, kind, payload)


class KindNames(unittest.TestCase):
    def test_every_declared_write_kind_fits_the_operation_record(self):
        # connector_operations.kind holds at most 20 characters (a CHECK): a longer name failed every execution of that kind as "invalid" before anything was sent.
        names = [k.name for k in google_hub.DECLARATION.write_kinds]
        self.assertTrue(names)
        self.assertEqual([n for n in names if not 1 <= len(n) <= 20], [])
