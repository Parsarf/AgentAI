"""One search for the command bar (UI remodel, phase 4).

    GET /v1/search?q=<words>&limit=<1..10 per kind>

Asks each store the signed-in person can read, under their own permissions, and merges what comes back: chats (titles and messages), tasks, files, and, while mail and
calendars are on, mail threads and events. Each result says what it is and where it is from. A store that fails, or that would start after the time budget is spent, drops
out and is named in `dropped`, so the bar can say so instead of pretending it searched everywhere. Settings are searched in the page itself (they are words, not data).
"""
import time

from django.http import JsonResponse

from . import wiring
from .services import rate
from .views import customer, endpoint

BUDGET = 0.6          # seconds for the whole search; a store that has not started by then is skipped and named


def _chats(principal, q, limit):
    from .chat import service
    rows = service().conversations(principal, query=q, limit=limit)
    return [{'kind': 'chat', 'id': r['id'], 'title': r.get('title') or 'New chat', 'detail': (r.get('preview') or '')[:120], 'epoch': None, 'when': r.get('last_activity')} for r in rows]


def _tasks(principal, q, limit):
    words = [w.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') for w in q.lower().split() if w][:6]
    if not words:
        return []
    store = wiring.store()
    with store.connect() as con:
        store._authorize(con, principal)
        rows = con.execute('SELECT id,message,state,conversation_id,created_epoch FROM customer_requests WHERE account_id=? AND '
                           + ' AND '.join(["lower(message) LIKE ? ESCAPE '\\'"] * len(words)) + ' ORDER BY created_epoch DESC LIMIT ?',
                           (principal.account_id, *[f'%{w}%' for w in words], limit)).fetchall()
    return [{'kind': 'task', 'id': r['id'], 'title': (r['message'] or '')[:160], 'detail': r['state'], 'conversation_id': r['conversation_id'], 'epoch': r['created_epoch']} for r in rows]


def _files(principal, q, limit):
    found = wiring.catalogue().entries(principal, query=q)['files'][:limit]
    return [{'kind': 'file', 'id': f['id'], 'source': f['kind'], 'title': f['name'], 'detail': 'You uploaded it' if f['kind'] == 'upload' else 'Made by your assistant', 'epoch': None,
             'when': f['created_at']} for f in found]


def _mail(principal, q, limit):
    rows = wiring.hub_service().threads(principal, label='all', query=q, limit=limit)['threads']
    return [{'kind': 'mail', 'id': t['id'], 'connection': t['connection_id'], 'title': t['subject'] or '(no subject)',
             'detail': ', '.join(p.get('name') or p.get('address') or '' for p in t['people'][:3]), 'epoch': t['last_epoch']} for t in rows]


def _events(principal, q, limit):
    rows = wiring.hub_service().search_events(principal, q, limit=limit)['events']
    return [{'kind': 'event', 'id': e['id'], 'connection': e['connection_id'], 'calendar': e['calendar_id'], 'title': 'Busy' if e.get('busy_only') else (e['title'] or '(no title)'),
             'detail': e.get('place') or '', 'epoch': e['start_epoch']} for e in rows]


@endpoint(['GET'])
def search(request):
    denied = customer(request)
    if denied:
        return denied
    rate('search', request.account_id, 600, 600)
    q = request.GET.get('q', '').strip()
    try:
        limit = max(1, min(10, int(request.GET.get('limit') or 5)))
    except ValueError:
        limit = 5
    if not q or len(q) > 200:
        return JsonResponse({'query': q, 'results': [], 'dropped': [], 'took_ms': 0})
    principal = wiring.principal(request)
    stores = [('chats', _chats), ('tasks', _tasks)]
    if wiring.storage_ready():
        stores.append(('files', _files))
    if wiring.hub_on(request.account_id):
        stores += [('mail', _mail), ('events', _events)]
    started = time.monotonic(); results, dropped = [], []
    for name, ask in stores:
        if time.monotonic() - started > BUDGET:
            dropped.append(name)
            continue
        try:
            results += ask(principal, q, limit)
        except Exception:                 # one store failing never takes the others down: it is named instead
            dropped.append(name)
    return JsonResponse({'query': q, 'results': results, 'dropped': dropped, 'took_ms': round((time.monotonic() - started) * 1000)})
