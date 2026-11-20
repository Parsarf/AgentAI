#!/usr/bin/env python3
"""Roadmap Phase 6 exit gate 1 for calendar changes: the Phase 3 write cycle on the REAL provider. Run it ON THE SERVER, after the customer has allowed calendar changes on
the account to test with (Calendar > Allow changes):

    sudo systemd-run --wait --pipe --collect --property=User=agentai-platform --property=EnvironmentFile=/etc/agentai-platform/accounts.env \\
        --property=WorkingDirectory=/opt/agentai-platform/current /opt/agentai-platform/current/.venv/bin/python deploy/phase6_live.py CONNECTION_ID

It works in that connection's primary calendar, on events it makes itself (titled "Lumina live check", with NO attendees, so nobody is told anything), and removes every one
of them before it ends. `mail_calendar_writes` counts as on INSIDE THIS PROCESS ONLY: no customer sees anything.

  W-FREE        a live free/busy answer for the calendar
  W-CREATE      preview equals payload; approved; executed once; read back and verified
  W-RETRY       running the done action again sends nothing; a second approval is refused; the same request sent again (same key) is answered by Google and makes no second event
  W-UNKNOWN     an outcome left unknown (as after a crash mid-send) is settled by reading the event back, never by sending again
  W-UNDO        undo cancels it with its version; undoing that puts it back
  W-CONFLICT    an event changed at the provider after it was read is not cancelled over that change
  W-RESPOND     an answer to an invitation (the account invites only itself) changes only its own answer; undo puts the old one back
  W-CHANGE      a change to one event (title and time) is sent once and verified; running it again sends nothing; undo puts the old values back (#62)
  W-SERIES-ONE  in a repeating series, a change to one occurrence changes only that occurrence; cancelling one occurrence and putting it back (#62, #63)
  W-SERIES-REST this and later occurrences: the series is split once (the original ends before it, a new series carries the change) and undo joins it again;
                ending a series there and undoing it (#62, #63)
  W-SERIES-ALL  the whole series moved from one occurrence moves by the same amount; undo moves it back (#62)
  CLEANUP       nothing this run made is left in the calendar

Prints one line per case; the last line is JSON with numbers and booleans only.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.db import connection as db  # noqa: E402

from accounts import wiring  # noqa: E402
from agentai_platform.connector_kit import ConnectorFault  # noqa: E402
from agentai_platform.google_calendar_writes import event_id_for, split_id  # noqa: E402
from agentai_platform.lifecycle.types import Conflict  # noqa: E402
from agentai_platform.security import Principal  # noqa: E402

RESULTS, MADE = [], []
TITLE = 'Lumina live check (safe to delete)'
_real = wiring.switch_on
wiring.switch_on = lambda name: name == 'mail_calendar_writes' or _real(name)          # this process only
from agentai_platform import hub_model  # noqa: E402
hub_model.PROVING_IN_THIS_PROCESS.update({'event_change', 'event_series'})           # the kinds being proven: on in this process only, never for a customer


def record(case, title, ok, detail=None):
    RESULTS.append({'id': case, 'title': title, 'passed': bool(ok), 'detail': detail or {}})
    print(f"{'PASS' if ok else 'FAIL':5} {case}  {title}" + (f'  -- {json.dumps(detail)}' if detail else ''), flush=True)


def sql(q, args=()):
    with db.cursor() as c:
        c.execute(q, args)
        return c.fetchall()


def main():
    connection_id = sys.argv[1]
    account = sql('SELECT account_id FROM connector_connections WHERE id=%s', [connection_id])[0][0]
    actor = sql("SELECT actor_id FROM memberships WHERE account_id=%s AND status='active' ORDER BY rowid LIMIT 1", [account])[0][0]
    p = Principal(account, str(actor), 'customer')
    connectors, client, actions, _ = wiring.action_services()
    hub = wiring.hub_service()
    calendar = sql("SELECT id,timezone FROM hub_calendars WHERE account_id=%s AND connection_id=%s AND is_primary=1", [account, connection_id])[0]
    calendar_id, zone_name = calendar[0], calendar[1] or 'UTC'
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(zone_name)
    row, declaration, adapter, credential = client.open(p, connection_id, 'connection.read')
    day = (datetime.now(zone) + timedelta(days=2)).date()

    def payload(hour, title=TITLE):
        return {'calendar': calendar_id, 'title': title, 'start': f'{day}T{hour:02d}:00', 'end': f'{day}T{hour:02d}:30', 'timezone': zone_name, 'notify': False}

    def at_google(event_id):
        found = adapter._read_event(credential, calendar_id, event_id)
        return found if found and found.get('status') != 'cancelled' else None

    def run(action):
        actions.approve(p, action['id'], action['payload_hash'])
        return actions.execute(account, action['id'])

    try:
        # -- W-FREE -----------------------------------------------------------------------------------------------------------------------------------------
        start = int(datetime.combine(day, datetime.min.time(), zone).timestamp())
        busy = adapter.free_busy(credential, [calendar_id], start, start + 86400)
        record('W-FREE', 'A live free/busy answer for the calendar', busy.get(calendar_id) is not None, {'busy_blocks': len(busy.get(calendar_id) or [])})

        # -- W-CREATE ---------------------------------------------------------------------------------------------------------------------------------------
        first = actions.propose(p, connection_id, 'event.create', payload(7))
        key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [first['id']])[0][0]
        MADE.append(event_id_for(key))
        shown = first['preview']
        before = at_google(event_id_for(key))
        state = run(first)
        done = actions.get(p, first['id'])
        made = at_google(event_id_for(key))
        record('W-CREATE', 'Preview equals payload; executed once; read back and verified',
               before is None and state == 'done' and done['verified'] is True and made is not None and made.get('summary') == TITLE
               and TITLE in shown['summary'] and not any(c['field'] == 'invitations' for c in shown['changes']),
               {'state': state, 'verified': done['verified'], 'at_provider': made is not None})

        # -- W-RETRY ----------------------------------------------------------------------------------------------------------------------------------------
        again = actions.execute(account, first['id'])
        try:
            actions.approve(p, first['id'], first['payload_hash']); second_approval = 'accepted'
        except Conflict:
            second_approval = 'refused'
        repeat = client.write(p, connection_id, 'event.create', payload(7), idempotency_key=key)       # the same request again, as a retry after a lost answer would be
        copies = [e for e in (adapter._get(credential, adapter._event_url(calendar_id), [('q', TITLE), ('timeMin', datetime.combine(day, datetime.min.time(), zone).isoformat()),
                                                                                       ('timeMax', datetime.combine(day + timedelta(days=1), datetime.min.time(), zone).isoformat()),
                                                                                       ('singleEvents', 'true')]).get('items') or []) if e.get('status') != 'cancelled']
        record('W-RETRY', 'Running it again sends nothing, a second approval is refused, the same request again makes no second event',
               again == 'done' and second_approval == 'refused' and split_id(repeat['record']['id'])[1] == event_id_for(key) and len(copies) == 1,
               {'run_again': again, 'second_approval': second_approval, 'events_with_this_title': len(copies)})

        # -- W-UNKNOWN --------------------------------------------------------------------------------------------------------------------------------------
        lost = actions.propose(p, connection_id, 'event.create', payload(8))
        lost_key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [lost['id']])[0][0]
        MADE.append(event_id_for(lost_key))
        actions.approve(p, lost['id'], lost['payload_hash'])
        client.write(p, connection_id, 'event.create', payload(8), idempotency_key=lost_key)          # it reached Google...
        sql("UPDATE actions SET state='uncertain' WHERE id=%s", [lost['id']])                          # ...and the answer was lost (a crash mid-send)
        settled = actions.reconcile(account, lost['id'])
        record('W-UNKNOWN', 'An unknown outcome is settled by reading the event back, never by sending again',
               settled == 'done' and at_google(event_id_for(lost_key)) is not None, {'settled': settled})

        # -- W-UNDO -----------------------------------------------------------------------------------------------------------------------------------------
        undo = actions.undo(p, first['id'])
        undone = run(undo)
        gone = at_google(event_id_for(key)) is None
        back = actions.undo(p, undo['id'])
        restored = run(back)
        back_key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [back['id']])[0][0]
        MADE.append(event_id_for(back_key))
        record('W-UNDO', 'Undo cancels it with its version; undoing that puts it back',
               undone == 'done' and gone and restored == 'done' and at_google(event_id_for(back_key)) is not None,
               {'undo': undone, 'cancelled_at_provider': gone, 'put_back': restored})

        # -- W-RESPOND --------------------------------------------------------------------------------------------------------------------------------------
        me = sql('SELECT identity_label FROM connector_connections WHERE id=%s', [connection_id])[0][0]
        invite = actions.propose(p, connection_id, 'event.create', {**payload(10), 'attendees': [me], 'notify': False})
        invite_key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [invite['id']])[0][0]
        MADE.append(event_id_for(invite_key))
        run(invite)
        answer = actions.propose(p, connection_id, 'event.respond', {'event': f'{calendar_id}|{event_id_for(invite_key)}', 'response': 'tentative', 'notify': False})
        answered = run(answer)
        mine = lambda: next((a.get('responseStatus') for a in (at_google(event_id_for(invite_key)) or {}).get('attendees') or [] if a.get('self')), None)
        after = mine()
        back_answer = run(actions.undo(p, answer['id']))
        record('W-RESPOND', 'An answer changes only the account\'s own answer; undo puts the old one back',
               answered == 'done' and after == 'tentative' and back_answer == 'done' and mine() != 'tentative' and actions.get(p, answer['id'])['verified'] is True,
               {'answered': answered, 'answer_at_provider': after, 'undo': back_answer})

        # -- W-CONFLICT -------------------------------------------------------------------------------------------------------------------------------------
        third = actions.propose(p, connection_id, 'event.create', payload(9))
        third_key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [third['id']])[0][0]
        MADE.append(event_id_for(third_key))
        run(third)
        undo_lost = actions.undo(p, third['id'])                                                        # prepared against the version as it is now
        status, _, _ = adapter._send(credential, 'PATCH', adapter._event_url(calendar_id, event_id_for(third_key)), {'summary': TITLE + ' (changed elsewhere)'})
        refused = run(undo_lost)
        still = at_google(event_id_for(third_key))
        record('W-CONFLICT', 'An event changed at the provider after it was read is not cancelled over that change',
               status == 200 and refused == 'failed' and actions.get(p, undo_lost['id'])['ended_reason'] == 'conflict' and still is not None,
               {'changed_elsewhere': status == 200, 'state': refused, 'still_there': still is not None})
        # -- W-CHANGE -------------------------------------------------------------------------------------------------------------------------------------
        plain = actions.propose(p, connection_id, 'event.create', payload(11))
        plain_id = event_id_for(sql('SELECT idempotency_key FROM actions WHERE id=%s', [plain['id']])[0][0])
        MADE.append(plain_id)
        run(plain)
        change = actions.propose(p, connection_id, 'event.update', {'event': f'{calendar_id}|{plain_id}', 'title': TITLE + ' (changed)', 'start': f'{day}T12:00',
                                                                   'end': f'{day}T12:45', 'timezone': zone_name, 'notify': False})
        changed = run(change)
        again = actions.execute(account, change['id'])
        there = at_google(plain_id) or {}
        back = run(actions.undo(p, change['id']))
        restored = at_google(plain_id) or {}
        record('W-CHANGE', 'A change to one event is sent once, verified, and undone',
               changed == 'done' and again == 'done' and actions.get(p, change['id'])['verified'] is True and there.get('summary') == TITLE + ' (changed)'
               and str((there.get('start') or {}).get('dateTime', ''))[11:16] == '12:00' and back == 'done' and restored.get('summary') == TITLE
               and str((restored.get('start') or {}).get('dateTime', ''))[11:16] == '11:00',
               {'change': changed, 'run_again': again, 'undo': back})

        # a repeating series of four daily occurrences, made by Lumina, with no attendees
        series = actions.propose(p, connection_id, 'event.create', {**payload(13), 'recurrence': ['RRULE:FREQ=DAILY;COUNT=4']})
        master_id = event_id_for(sql('SELECT idempotency_key FROM actions WHERE id=%s', [series['id']])[0][0])
        MADE.append(master_id)
        run(series)
        def occurrences():
            items = adapter._get(credential, adapter._event_url(calendar_id, master_id) + '/instances?maxResults=10&showDeleted=true').get('items') or []
            return sorted(items, key=lambda e: str((e.get('originalStartTime') or {}).get('dateTime', '')))
        first = occurrences()
        ids = [e['id'] for e in first]

        # -- W-SERIES-ONE -------------------------------------------------------------------------------------------------------------------------------
        one = run(actions.propose(p, connection_id, 'event.update', {'event': f'{calendar_id}|{ids[1]}', 'title': TITLE + ' (one)', 'notify': False}))
        titles = [e.get('summary') for e in occurrences()]
        cancel = actions.propose(p, connection_id, 'event.cancel_one', {'event': f'{calendar_id}|{ids[2]}', 'notify': False})
        cancelled = run(cancel)
        status_after = [e.get('status') for e in occurrences()]
        put_back = run(actions.undo(p, cancel['id']))
        status_back = [e.get('status') for e in occurrences()]
        record('W-SERIES-ONE', 'One occurrence changes alone; one occurrence is cancelled and put back',
               one == 'done' and titles == [TITLE, TITLE + ' (one)', TITLE, TITLE] and cancelled == 'done' and status_after[2] == 'cancelled'
               and status_after.count('cancelled') == 1 and put_back == 'done' and status_back.count('cancelled') == 0,
               {'one': one, 'titles_changed': sum(t != TITLE for t in titles), 'cancel': cancelled, 'put_back': put_back})

        # -- W-SERIES-REST ------------------------------------------------------------------------------------------------------------------------------
        split = actions.propose(p, connection_id, 'event.update_rest', {'event': f'{calendar_id}|{ids[2]}', 'series': f'{calendar_id}|{master_id}',
                                                                        'title': TITLE + ' (rest)', 'notify': False})
        split_key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [split['id']])[0][0]
        MADE.append(event_id_for(split_key))
        splitted = run(split)
        master_now = adapter._read_event(credential, calendar_id, master_id) or {}
        new_series = adapter._read_event(credential, calendar_id, event_id_for(split_key)) or {}
        joined = run(actions.undo(p, split['id']))
        master_back = adapter._read_event(credential, calendar_id, master_id) or {}
        ended = actions.propose(p, connection_id, 'event.end_series', {'event': f'{calendar_id}|{ids[2]}', 'series': f'{calendar_id}|{master_id}', 'notify': False})
        end_state = run(ended)
        master_ended = adapter._read_event(credential, calendar_id, master_id) or {}
        unended = run(actions.undo(p, ended['id']))
        master_whole = adapter._read_event(credential, calendar_id, master_id) or {}
        record('W-SERIES-REST', 'This and later occurrences: split once and joined again; ended there and restored',
               splitted == 'done' and any('UNTIL=' in r for r in master_now.get('recurrence') or []) and new_series.get('recurrence') == ['RRULE:FREQ=DAILY;COUNT=2']
               and new_series.get('summary') == TITLE + ' (rest)' and joined == 'done' and master_back.get('recurrence') == ['RRULE:FREQ=DAILY;COUNT=4']
               and (adapter._read_event(credential, calendar_id, event_id_for(split_key)) or {}).get('status') == 'cancelled'
               and end_state == 'done' and any('UNTIL=' in r for r in master_ended.get('recurrence') or []) and unended == 'done'
               and master_whole.get('recurrence') == ['RRULE:FREQ=DAILY;COUNT=4'],
               {'split': splitted, 'new_series_count': new_series.get('recurrence'), 'joined': joined, 'ended': end_state, 'restored': unended})

        # -- W-SERIES-ALL -------------------------------------------------------------------------------------------------------------------------------
        local = lambda raw: str(((raw or {}).get('start') or {}).get('dateTime', ''))[11:16]
        moved = actions.propose(p, connection_id, 'event.update', {'event': f'{calendar_id}|{master_id}', 'occurrence': f'{calendar_id}|{ids[1]}',
                                                                  'start': f'{(day + timedelta(days=1))}T13:30', 'end': f'{(day + timedelta(days=1))}T14:00',
                                                                  'timezone': zone_name, 'notify': False})
        moved_state = run(moved)
        master_moved = adapter._read_event(credential, calendar_id, master_id)
        moved_back = run(actions.undo(p, moved['id']))
        master_original = adapter._read_event(credential, calendar_id, master_id)
        record('W-SERIES-ALL', 'The whole series moved from one occurrence moves by the same amount, and back',
               moved_state == 'done' and local(master_moved) == '13:30' and moved_back == 'done' and local(master_original) == '13:00',
               {'moved': moved_state, 'series_starts_at': local(master_moved), 'undo': moved_back, 'back_at': local(master_original)})
    finally:
        # -- CLEANUP: every event this run made goes, whatever happened above ------------------------------------------------------------------------------
        left = 0
        for event_id in MADE:
            found = adapter._read_event(credential, calendar_id, event_id)
            if found and found.get('status') != 'cancelled':
                adapter._send(credential, 'DELETE', adapter._event_url(calendar_id, event_id) + '?sendUpdates=none')
                left += 1 if at_google(event_id) else 0
        record('CLEANUP', 'Nothing this run made is left in the calendar', left == 0, {'events_made': len(MADE), 'left': left})
    failed = [r for r in RESULTS if not r['passed']]
    print(json.dumps({'passed': not failed, 'cases': RESULTS}), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
