#!/usr/bin/env python3
"""Roadmap Phase 6 exit gate 8 for Microsoft (#D8): the Phase 5 read suite and the Phase 6 write cycle on a REAL Outlook account, connected beside a Google one. Run it ON THE
SERVER once the owner's Entra app is configured (AGENTAI_MICROSOFT_CLIENT_ID, AGENTAI_MICROSOFT_CLIENT_SECRET_FILE) and an Outlook account is connected with
"Allow changes" given for calendar, sending and organizing:

    sudo systemd-run --wait --pipe --collect --property=User=agentai-platform --property=EnvironmentFile=/etc/agentai-platform/accounts.env \\
        --property=WorkingDirectory=/opt/agentai-platform/current /opt/agentai-platform/current/.venv/bin/python deploy/phase6_microsoft_live.py CONNECTION_ID

Changes count as proven INSIDE THIS PROCESS ONLY. It works on what it makes itself (an event with no attendees, a message to the account itself) and removes it.

  X-READ      folders, messages (a delta page), a message body, calendars and occurrences, in the neutral shapes, synced into the one inbox and calendar
  X-EVENT     an event created once (a retry finds it by its key), changed with its version, cancelled; undo puts it back
  X-SEND      a draft to the account itself sent once: a lost answer is found in Sent Items by its marker, never sent again
  X-ORGANIZE  a conversation flagged and put back, archived and put back
  CLEANUP     nothing it made is left (the sent message goes to Deleted Items)

Prints one line per case; the last line is JSON with numbers and booleans only.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.db import connection as db  # noqa: E402

from accounts import wiring  # noqa: E402
from agentai_platform import hub_model  # noqa: E402
from agentai_platform.google_mail_writes import marker  # noqa: E402
from agentai_platform.security import Principal  # noqa: E402

RESULTS, MADE = [], []
_real = wiring.switch_on
wiring.switch_on = lambda name: name == 'mail_calendar_writes' or _real(name)
hub_model.PROVING_IN_THIS_PROCESS.update({'send', 'organize', 'mark_read', 'event_write', 'respond', 'event_change', 'event_series'})


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
    row, declaration, adapter, credential = client.open(p, connection_id, 'connection.read')

    def run(action):
        actions.approve(p, action['id'], action['payload_hash'])
        return actions.execute(account, action['id'])
    stamp = uuid.uuid4().hex[:8]
    title = f'Lumina live check (safe to delete) {stamp}'
    try:
        # -- X-READ ---------------------------------------------------------------------------------------------------------------------------------
        page = adapter.mail_changes(credential, None, int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp()), None, 20)
        cals = adapter.calendars(credential)
        primary = next((c for c in cals if c['primary']), cals[0])
        events = adapter.event_changes(credential, primary['id'], None, int(datetime.now(timezone.utc).timestamp()) - 86400 * 30, int(datetime.now(timezone.utc).timestamp()) + 86400 * 60, 50)
        content = adapter.mail_body(credential, page.items[0]['id']) if page.items else None
        threads = hub.threads(p, connections=[connection_id], limit=5)['threads']
        record('X-READ', 'Folders, messages, a body, calendars and occurrences read into the neutral shapes and the one inbox',
               bool(cals) and content is not None and isinstance(events.items, list) and len(threads) > 0,
               {'messages': len(page.items), 'calendars': len(cals), 'occurrences': len(events.items), 'threads_in_inbox': len(threads)})

        # -- X-EVENT --------------------------------------------------------------------------------------------------------------------------------
        day = (datetime.now(timezone.utc) + timedelta(days=2)).strftime('%Y-%m-%d')
        made = actions.propose(p, connection_id, 'event.create', {'calendar': primary['id'], 'title': title, 'start': f'{day}T15:00', 'end': f'{day}T15:30', 'timezone': 'UTC'})
        key = sql('SELECT idempotency_key FROM actions WHERE id=%s', [made['id']])[0][0]
        created = run(made)
        again = actions.execute(account, made['id'])
        event_id = (actions.get(p, made['id']).get('result') or {}).get('record', {}).get('id') if isinstance(actions.get(p, made['id']).get('result'), dict) else None
        found = adapter.find_effect(credential, 'event.create', {'calendar': primary['id']}, key)
        MADE.append(found['record']['id'] if found else None)
        change = actions.propose(p, connection_id, 'event.update', {'event': found['record']['id'], 'title': title + ' (changed)', 'notify': False})
        changed = run(change)
        cancel = actions.propose(p, connection_id, 'event.delete', {'event': found['record']['id'], 'notify': False})
        cancelled = run(cancel)
        record('X-EVENT', 'An event created once, changed with its version and cancelled',
               created == 'done' and again == 'done' and changed == 'done' and cancelled == 'done' and actions.get(p, made['id'])['verified'] is True,
               {'created': created, 'run_again': again, 'changed': changed, 'cancelled': cancelled})

        # -- X-SEND ---------------------------------------------------------------------------------------------------------------------------------
        own = sql('SELECT identity_label FROM connector_connections WHERE id=%s', [connection_id])[0][0]
        draft = hub.save_draft(p, connection_id=connection_id, to=[own], subject=title, body='A message Lumina sent to this account to check sending. Safe to delete.', origin='customer')
        conn_id, payload = hub.send_payload(p, draft['id'])
        sent = actions.propose(p, conn_id, 'mail.send', payload)
        hub.mark_sending(p, draft['id'], sent['id'])
        actions.approve(p, sent['id'], sent['payload_hash'])
        client.write(p, conn_id, 'mail.send', payload, idempotency_key=sql('SELECT idempotency_key FROM actions WHERE id=%s', [sent['id']])[0][0])
        sql("UPDATE actions SET state='uncertain' WHERE id=%s", [sent['id']])
        settled = actions.reconcile(account, sent['id'])
        copies = adapter._get(credential, '/me/mailFolders/sentitems/messages', [('$filter', f"singleValueExtendedProperties/Any(ep: ep/id eq '{__import__('agentai_platform.microsoft_writes', fromlist=['MARK']).MARK}' and ep/value eq '{marker(draft['id'])}')"), ('$select', 'id,conversationId')]).get('value') or []
        MADE.extend(('message', c['id']) for c in copies)
        record('X-SEND', 'A draft is sent once: a lost answer is found in Sent Items by its marker', settled == 'done' and len(copies) == 1, {'settled': settled, 'copies_in_sent': len(copies)})

        # -- X-ORGANIZE -----------------------------------------------------------------------------------------------------------------------------
        thread = threads[0]['id']
        steps = []
        for op in ('star', 'archive'):
            kind, change = hub.organize_payload(p, connection_id, [thread], op)
            done = actions.direct(p, connection_id, kind, change, screen='inbox')
            back = actions.undo_direct(p, done['id'], screen='inbox')
            steps.append((op, done['state'], done['verified'], back['state']))
        record('X-ORGANIZE', 'A conversation flagged and archived, each put back in one step', all(s[1] == 'done' and s[2] is True and s[3] == 'done' for s in steps),
               {'steps': [list(s) for s in steps]})
    finally:
        left = 0
        for item in MADE:
            if isinstance(item, tuple) and item[0] == 'message':
                try:
                    adapter._send(credential, 'POST', f'/me/messages/{item[1]}/move', {'destinationId': 'deleteditems'})
                except Exception:
                    left += 1
        record('CLEANUP', 'Nothing it made is left (the event was cancelled; the sent message is in Deleted Items)', left == 0, {'left': left})
    failed = [r for r in RESULTS if not r['passed']]
    print(json.dumps({'passed': not failed, 'cases': RESULTS}), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
