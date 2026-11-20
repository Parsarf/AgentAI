"""Meeting scheduling (roadmap Phase 6, #65): times free for the customer and for every attendee whose free time their account may see; the others are offered the times
by a draft email and the work waits for their answer without holding anything; the event is created with one approval."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from agentai_platform import google_hub
from agentai_platform.actions import ActionService
from tests.test_google_hub import SCOPES, GoogleBase

NY = ZoneInfo('America/New_York')
day = lambda text: int(datetime.strptime(text, '%Y-%m-%d').replace(tzinfo=NY).timestamp())


class MeetingTimes(GoogleBase):
    def setUp(self):
        super().setUp()
        self.connection, _ = self.sign_in()
        self.run_sync()
        self.g.shared_busy = {'bo@y.test': [('2033-05-18T13:00:00Z', '2033-05-18T16:00:00Z')],            # 9:00 to 12:00 in New York
                              'cy@z.test': [('2033-05-19T13:00:00Z', '2033-05-19T13:30:00Z')]}

    def test_two_internal_attendees_get_times_free_for_everyone_one_a_day_first(self):
        found = self.hub.meeting_times(self.a, self.connection, ['bo@y.test', 'CY@z.test', 'bo@y.test'], 30, day('2033-05-18'), day('2033-05-20'), 'America/New_York',
                                       title='Planning')
        self.assertEqual((found['internal'], found['external']), (['bo@y.test', 'cy@z.test'], []))
        self.assertEqual([o['start'] for o in found['options']], ['2033-05-18T12:00', '2033-05-18T12:30', '2033-05-19T09:30'])
        self.assertEqual([o['end'] for o in found['options']][0], '2033-05-18T12:30')
        drawn = self.hub.proposals(self.a, day('2033-05-18'), day('2033-05-21'))
        self.assertEqual([(p['id'], p['title'], len(p['options'])) for p in drawn], [(found['proposal'], 'Planning', 3)])
        self.assertEqual(self.hub.proposals(self.b, day('2033-05-18'), day('2033-05-21')), [])                     # another customer sees nothing
        # the customer picks the first time: one approval creates it with the attendees, and the suggestion goes
        actions = ActionService(self.store, self.connectors, self.client, clock=lambda: self.now)
        started = self.connectors.start_link(self.a, 'google', self.redirect, upgrade=self.connection)
        self.g.scope = SCOPES + ' ' + google_hub.EVENTS_SCOPE
        self.connectors.finish_link(self.a, started['state'], 'good-code', self.redirect, self.exchange)
        first = found['options'][0]
        event = actions.propose(self.a, self.connection, 'event.create', {'calendar': 'dana@gmail.test', 'title': 'Planning', 'start': first['start'], 'end': first['end'],
                                                                          'timezone': 'America/New_York', 'attendees': ['bo@y.test', 'cy@z.test'], 'notify': True})
        actions.approve(self.a, event['id'], event['payload_hash'])
        self.assertEqual(actions.execute('a', event['id']), 'done')
        self.hub.close_proposal(self.a, found['proposal'], 'picked')
        self.assertEqual(self.hub.proposals(self.a, day('2033-05-18'), day('2033-05-21')), [])
        made = [e for e in self.g.events['dana@gmail.test'].values() if e.get('summary') == 'Planning']
        self.assertEqual([[a['email'] for a in e['attendees']] for e in made], [['bo@y.test', 'cy@z.test']])

    def test_an_external_attendee_is_offered_the_times_and_the_work_waits_without_holding_anything(self):
        found = self.hub.meeting_times(self.a, self.connection, ['bo@y.test', 'zed@else.test'], 60, day('2033-05-18'), day('2033-05-19'), 'America/New_York', title='Intro')
        self.assertEqual((found['internal'], found['external']), (['bo@y.test'], ['zed@else.test']))
        draft = self.hub.save_draft(self.a, connection_id=self.connection, to=['zed@else.test'], subject='Intro', origin='assistant',
                                    body='Would one of these suit you? ' + '; '.join(o['start'] for o in found['options']))
        waited = self.hub.wait_for_reply(self.a, found['proposal'], draft_id=draft['id'])
        row = self.rows('SELECT kind,state,expires_epoch,created_epoch,resume_json FROM handoffs WHERE id=?', (waited['handoff'],))[0]
        self.assertEqual((row['kind'], row['state'], row['expires_epoch'] - row['created_epoch']), ('question', 'waiting', 14 * 86400))
        self.assertEqual(json.loads(row['resume_json'])['meeting_proposal'], found['proposal'])
        self.assertIn('zed@else.test', waited['question'])
        self.assertEqual(self.rows("SELECT count(*) AS n FROM request_slots")[0]['n'], 0)                       # nothing held while it waits
        self.hub.close_proposal(self.a, found['proposal'], 'dismissed')
        self.assertEqual(self.rows('SELECT state FROM handoffs WHERE id=?', (waited['handoff'],))[0]['state'], 'expired')

    def test_no_time_when_everyone_is_busy_and_bad_input_is_refused(self):
        self.g.shared_busy['bo@y.test'] = [('2033-05-18T00:00:00Z', '2033-05-20T00:00:00Z')]
        found = self.hub.meeting_times(self.a, self.connection, ['bo@y.test'], 30, day('2033-05-18'), day('2033-05-19'), 'America/New_York')
        self.assertEqual((found['options'], found['proposal']), ([], None))
        with self.assertRaises(ValueError):
            self.hub.meeting_times(self.a, self.connection, ['not an address'], 30, day('2033-05-18'), day('2033-05-19'), 'America/New_York')
