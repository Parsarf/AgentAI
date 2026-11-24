"""What each model call did, as Lumina's own model relay saw it (reliability plan, Part 1): one row in `model_calls` per call, and a fault when it failed.

The relay (model_keys.ModelRelay) is where every model call of every cell passes, so it is the one place that knows, as facts, what a provider answered: the HTTP status,
how long the answer took to begin and to end, how long the call waited for a busy provider, and the token counts the provider reported. Nothing of the request or the reply
is kept. This is what later tells a customer "waiting for the model", tells the owner that Lumina's own key was refused, and gives a failed run its reason without reading
the runtime's wording.

A model call cannot say which of an account's tasks it is for. It is tied to a request only when exactly one of the account's requests is running; otherwise it is kept
with the account alone.
"""
from __future__ import annotations
import time
import uuid

from . import faults, request_states


def owner_request(con, account_id):
    """The one running request of this account, or None when there is none or more than one."""
    rows = con.execute(f"SELECT r.id FROM customer_requests r WHERE r.account_id=? AND {request_states.live_run()} LIMIT 2", (account_id,)).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def note(store, account_id, call, *, now=None):
    """Keep one finished model call (`call` is what ModelRelay hands its recorder). -> the fault it was, or None. Never raises."""
    try:
        now = int(now if now is not None else time.time())
        status, code, route = int(call.get('status') or 0), str(call.get('code') or '')[:60], 'own' if call.get('route') == 'own' else 'lumina'
        fault = faults.of_model_status(status, code, own=route == 'own')
        number = lambda key: int(call[key]) if isinstance(call.get(key), int) and not isinstance(call.get(key), bool) and call[key] >= 0 else None
        with store.connect() as con:
            request = owner_request(con, account_id)
            con.execute('''INSERT INTO model_calls(account_id,id,request_id,route,status,code,waited_ms,answer_ms,total_ms,reply_bytes,input_tokens,output_tokens,cached_tokens,created_epoch)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (account_id, uuid.uuid4().hex, request, route, status if 0 <= status <= 599 else 0, code, number('waited_ms') or 0, number('answer_ms') or 0,
                         number('total_ms') or 0, number('reply_bytes') or 0, number('input_tokens'), number('output_tokens'), number('cached_tokens'), now))
            if fault is not None:
                faults.insert(con, account_id, fault, request_id=request, now=now)
        return fault
    except Exception:
        faults.log.error('model call not recorded account=%s', str(account_id)[:40])
        return None
