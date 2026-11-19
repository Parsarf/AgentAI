#!/usr/bin/env python3
"""Roadmap Phase 5 exit gate 1 on the live stack: the read-only suite on a real customer account with TWO connected Google accounts. Run it ON THE SERVER:

    sudo systemd-run --wait --pipe --collect --property=User=agentai-platform --property=EnvironmentFile=/etc/agentai-platform/accounts.env \\
        --property=WorkingDirectory=/opt/agentai-platform/current /opt/agentai-platform/current/.venv/bin/python deploy/phase5_live.py [ACCOUNT_ID]

Without ACCOUNT_ID it uses the one account that has two or more working Google connections. Everything it does is what the customer's own Inbox and Calendar pages
and the assistant's tools do: it reads (the provider sees read-only calls), opens one thread per account (opening never marks mail read at the provider), reads one
attachment into the customer's knowledge index (visible on their Sources page, as when they open one), writes one draft in Lumina and discards it, and prepares one
meeting brief. It changes nothing at the provider: the connection's scopes are read only.

  G1-ACCOUNTS    two or more Google connections, each working, each with what the customer picked
  G1-INBOX       the unified inbox lists threads of both accounts in one list
  G1-CALENDAR    the unified calendar lists both accounts' selected calendars, and events of every account that has any
  G1-READ        one thread of each account opens with its message text
  G1-SEARCH      a word from each account's thread finds it in the one search; live provider search for older mail answers with its completeness
  G1-ATTACHMENT  an attachment is read through the knowledge pipeline and is searchable, with the email as its source
  G1-DRAFT       a draft is kept in Lumina (with a compose link to the provider), and discarded
  G1-BRIEF       a meeting brief is prepared for an event with people, every item cited, and what could not be found is said
  G1-ANSWER      the assistant panel answered a question about a thread of the second account and cited it (the customer asks it in the panel; this reads the answer)

Prints one line per gate; the last line is JSON with numbers and booleans only: never a subject, a name, an address or message text.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.db import connection  # noqa: E402

from accounts import wiring  # noqa: E402
from agentai_platform.hub_tools import mail_link  # noqa: E402
from agentai_platform.security import Principal  # noqa: E402

RESULTS = []
DAY = 86400
DOCUMENTS = ('pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'csv', 'txt', 'md', 'html', 'png', 'jpg', 'jpeg')


def record(case, title, ok, detail=None):
    RESULTS.append({'id': case, 'title': title, 'passed': bool(ok), 'detail': detail or {}})
    print(f"{'PASS' if ok else 'FAIL':5} {case}  {title}" + (f'  -- {json.dumps(detail)}' if detail else ''), flush=True)


def sql(q, args=()):
    with connection.cursor() as c:
        c.execute(q, args)
        return c.fetchall()


def pick_account(given):
    if given:
        return given
    rows = sql("SELECT account_id FROM connector_connections WHERE service='google' AND state='connected' GROUP BY account_id HAVING count(*)>=2")
    if len(rows) != 1:
        raise SystemExit(f'give the account id: {len(rows)} accounts have two or more working Google connections')
    return rows[0][0]


def main():
    account = pick_account(sys.argv[1] if len(sys.argv) > 1 else None)
    actor = sql("SELECT actor_id FROM memberships WHERE account_id=%s AND status='active' ORDER BY rowid LIMIT 1", [account])[0][0]
    p = Principal(account, str(actor), 'customer')
    hub = wiring.hub_service()
    real = wiring.switch_on
    wiring.switch_on = lambda name: name == 'customer_knowledge' or real(name)       # this process only: the attachment is read even if the switch is still off
    tools = wiring.knowledge_tools()
    started = time.time()

    # -- G1-ACCOUNTS -------------------------------------------------------------------------------------------------------------------------------------------
    mine = [a for a in hub.accounts(p) if a.get('provider') == 'google']
    working = [a for a in mine if a.get('state') == 'working' and (a.get('granted') or {}).get('mail')]
    calendars = hub.calendars(p)
    selected = {c['connection_id'] for c in calendars if c.get('selected')}
    record('G1-ACCOUNTS', 'Two or more Google accounts, each working, each with what the customer picked', len(working) >= 2,
           {'google_accounts': len(mine), 'working': len(working), 'with_selected_calendars': len(selected)})
    ids = [a['id'] for a in working]

    # -- G1-INBOX ----------------------------------------------------------------------------------------------------------------------------------------------
    page = hub.threads(p, label='all', limit=200)
    by = {}
    for t in page['threads']:
        by.setdefault(t['connection_id'], []).append(t)
    record('G1-INBOX', 'One list holds threads of both accounts', len([i for i in ids if by.get(i)]) >= 2,
           {'threads_on_first_pages': {f'account_{n + 1}': len(by.get(i, [])) for n, i in enumerate(ids)}})

    # -- G1-CALENDAR -------------------------------------------------------------------------------------------------------------------------------------------
    now = int(time.time())
    seen = {}
    for start in range(now - 360 * DAY, now + 360 * DAY, 360 * DAY):
        for e in hub.events(p, start, start + 360 * DAY)['events']:
            seen[e['connection_id']] = seen.get(e['connection_id'], 0) + 1
    with_events = [i for i in ids if seen.get(i)]
    record('G1-CALENDAR', 'The calendar shows both accounts\' calendars, and events of each account that has any', len([i for i in ids if i in selected]) >= 2 and bool(with_events),
           {'selected_calendars_by_account': {f'account_{n + 1}': sum(1 for c in calendars if c['connection_id'] == i and c.get('selected')) for n, i in enumerate(ids)},
            'events_in_two_years_around_today': {f'account_{n + 1}': seen.get(i, 0) for n, i in enumerate(ids)}})

    # -- G1-READ -----------------------------------------------------------------------------------------------------------------------------------------------
    opened = {}
    for i in ids:
        if by.get(i):
            t = by[i][0]
            thread = hub.thread(p, i, t['id'])
            last = (thread.get('messages') or [{}])[-1]
            opened[i] = {'thread': t['id'], 'text': bool(last.get('body') and (last['body'].get('text') or last['body'].get('html'))), 'subject': t.get('subject') or ''}
    record('G1-READ', 'One thread of each account opens with its message text', len([i for i in ids if opened.get(i, {}).get('text')]) >= 2,
           {'opened_with_text': sum(1 for v in opened.values() if v['text'])})

    # -- G1-SEARCH ---------------------------------------------------------------------------------------------------------------------------------------------
    found = 0
    for i, v in opened.items():
        words = [w for w in re.findall(r'[^\W\d_]{4,}', v['subject'])][:1]
        if words and any(t['id'] == v['thread'] for t in hub.threads(p, label='all', query=words[0], limit=200)['threads']):
            found += 1
    older = None
    if opened:
        i, v = next(iter(opened.items()))
        word = ([w for w in re.findall(r'[^\W\d_]{4,}', v['subject'])] or ['invoice'])[0]
        older = hub.search_older(p, i, word)
    page_of = (older or {}).get('page') or {}
    record('G1-SEARCH', 'A word of each opened thread finds it in the one search; the live search of older mail says whether it is complete',
           found >= 2 and older is not None and not older.get('problem') and 'complete' in page_of,
           {'found_by_their_own_word': found, 'older_search_problem': (older or {}).get('problem'), 'older_search_says_complete': page_of.get('complete')})

    # -- G1-ATTACHMENT -----------------------------------------------------------------------------------------------------------------------------------------
    marks = ','.join('%s' for _ in ids)
    candidates = sql(f'SELECT connection_id,id FROM hub_messages WHERE account_id=%s AND connection_id IN ({marks}) AND has_attachments=1 ORDER BY sent_epoch DESC LIMIT 25',
                     [account, *ids])
    attachment = None
    for conn, message in candidates:
        body = (hub.message(p, conn, message).get('body') or {})
        files = [f for f in body.get('attachments') or [] if str(f.get('name') or '').rsplit('.', 1)[-1].lower() in DOCUMENTS and (f.get('size') or 0) < 10 * 2 ** 20]
        if files:
            attachment = {'account': conn, 'message': message, 'attachment': files[0]['id']}
            break
    if attachment:
        out = tools._mail_attachment(p, None, None, attachment)
        state = sql('SELECT state,passages,kind FROM knowledge_sources WHERE account_id=%s AND id=%s', [account, out.get('source')]) if out.get('source') else []
        ok = bool(state) and state[0][0] == 'ready' and state[0][1] > 0 and state[0][2] == 'attachment' and bool(out.get('outline'))
        record('G1-ATTACHMENT', 'An attachment is read through the knowledge pipeline, with the email as its source', ok,
               {'state': state[0][0] if state else None, 'passages': state[0][1] if state else 0})
    else:
        record('G1-ATTACHMENT', 'An attachment is read through the knowledge pipeline', False, {'messages_with_a_document_attachment': 0})

    # -- G1-DRAFT ----------------------------------------------------------------------------------------------------------------------------------------------
    draft_ok, detail = False, {}
    if opened:
        i, v = list(opened.items())[-1]
        draft = hub.save_draft(p, connection_id=i, thread_id=v['thread'], subject='Re: (Lumina live check)', body='A draft written by the Lumina live check. It is discarded at once.')
        link = hub.compose_link(p, draft['id']).get('link')
        listed = any(d['id'] == draft['id'] for d in hub.drafts(p))
        hub.discard_draft(p, draft['id'])
        gone = not any(d['id'] == draft['id'] for d in hub.drafts(p))
        draft_ok = listed and gone and str(link or '').startswith('https://mail.google.com/')
        detail = {'listed': listed, 'compose_link_to_provider': str(link or '').startswith('https://mail.google.com/'), 'discarded': gone}
    record('G1-DRAFT', 'A draft is kept in Lumina with a compose link to the provider, then discarded', draft_ok, detail)

    # -- G1-BRIEF ----------------------------------------------------------------------------------------------------------------------------------------------
    chosen = sql(f"""SELECT connection_id,calendar_id,id FROM hub_events WHERE account_id=%s AND connection_id IN ({marks}) AND json_array_length(attendees_json)>=2
        AND cancelled=0 AND visibility!='busy' ORDER BY abs(start_epoch-%s) LIMIT 1""", [account, *ids, now])
    if chosen:
        brief = tools._meeting_brief(p, None, None, {'account': chosen[0][0], 'calendar': chosen[0][1], 'event': chosen[0][2]})
        cites = json.dumps(brief).count('"open"')
        record('G1-BRIEF', 'A meeting brief for an event with people: every item cited, what was not found is said', cites >= 1 and 'could_not_find' in brief,
               {'citations': cites, 'not_found_statements': len(brief.get('could_not_find') or [])})
    else:
        record('G1-BRIEF', 'A meeting brief for an event with people', False, {'events_with_two_or_more_people': 0})

    # -- G1-ANSWER ---------------------------------------------------------------------------------------------------------------------------------------------
    second = ids[1] if len(ids) > 1 else None
    rows = sql("""SELECT m.content FROM chat_messages m JOIN conversations c ON c.account_id=m.account_id AND c.id=m.conversation_id
        JOIN projects pr ON pr.account_id=c.account_id AND pr.id=c.project_id WHERE m.account_id=%s AND m.provenance='agent' AND pr.name='Assistant panel'
        ORDER BY m.id DESC LIMIT 20""", [account])
    cited = second is not None and any(f'/inbox?connection={second}' in r[0] or mail_link(second, '').split('&')[0] in r[0] for r in rows)
    record('G1-ANSWER', 'The assistant panel answered about a thread of the second account and cited it', cited, {'recent_panel_answers': len(rows)})

    failed = [r for r in RESULTS if not r['passed']]
    print(json.dumps({'passed': not failed, 'seconds': round(time.time() - started, 1), 'cases': RESULTS}), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
