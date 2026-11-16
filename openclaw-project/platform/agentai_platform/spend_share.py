"""Exact cost per request when several requests of one account run at the same time (roadmap #10, parallel phases).

The cell's model key has ONE running total. A request's cost used to be that total at its end minus at its start, which is right only while it runs alone. Now every request records the
total when it starts and when it ends (`spend_marks`). The total is walked in order: each stretch between two marks is a slice of spend, and the slice is shared equally by the requests
that were running during it. So every cent the key spent is charged to some request, once, and a request that ran alone is charged exactly what it always was.
"""
from __future__ import annotations
import time

WINDOW = 86400      # marks older than this cannot belong to a run that is still going


class SpendShare:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def mark(self, account, request, kind, spend):
        """Record the key's running total at the start or the end of a request. Once per request and kind (a repeat changes nothing)."""
        if kind not in ('start', 'end') or type(spend) is not int or spend < 0:
            return
        with self.store.connect() as con:
            con.execute('INSERT OR IGNORE INTO spend_marks(account_id,request_id,kind,spend_microusd,epoch) VALUES (?,?,?,?,?)', (account, request, kind, spend, int(self.clock())))

    def close(self, account, request):
        """A request is over but its end could not be read (the runtime was unreachable, the provider's total could not be fetched): end it where it started. It then takes no
        share of anything, and, above all, it is not counted as still running beside every later request of the account (which halved their cost). Changes nothing when the
        request has no start mark or already has an end mark."""
        with self.store.connect() as con:
            con.execute("""INSERT OR IGNORE INTO spend_marks(account_id,request_id,kind,spend_microusd,epoch)
                SELECT account_id,request_id,'end',spend_microusd,? FROM spend_marks WHERE account_id=? AND request_id=? AND kind='start'""", (int(self.clock()), account, request))

    def cost(self, account, request, now_spend=None):
        """-> this request's share of the key's spend so far (to its end mark if it has one, else to `now_spend`), or None when it has no start mark (the caller falls back to end - start)."""
        with self.store.connect() as con:
            own = con.execute("SELECT epoch FROM spend_marks WHERE account_id=? AND request_id=? AND kind='start'", (account, request)).fetchone()
            if own is None:
                return None
            rows = con.execute('SELECT request_id,kind,spend_microusd,id FROM spend_marks WHERE account_id=? AND epoch>=? ORDER BY spend_microusd,id',
                               (account, own['epoch'] - WINDOW)).fetchall()
            # A request that is over but left no end mark (an ending that never reached `close`, or one from before `close` existed) is not running: it ends where it started.
            ended = {r['request_id'] for r in rows if r['kind'] == 'end'}
            open_ids = sorted({r['request_id'] for r in rows if r['kind'] == 'start' and r['request_id'] not in ended and r['request_id'] != request})
            over = set()
            for i in range(0, len(open_ids), 400):
                part = open_ids[i:i + 400]
                over |= {r[0] for r in con.execute(f"SELECT id FROM customer_requests WHERE account_id=? AND state IN ('completed','failed','cancelled') AND id IN ({','.join('?' * len(part))})",
                                                   (account, *part))}
        return self.walk([(r['request_id'], r['kind'], r['spend_microusd']) for r in rows if r['request_id'] not in over], request, now_spend)

    @staticmethod
    def walk(marks, request, now_spend=None):
        """Pure: marks are (request, 'start'|'end', total) in order of total. Returns the share of `request`, or None without its start mark."""
        active, share, previous, started, finished = set(), 0, None, False, False
        for who, kind, total in marks:
            if started and not finished and previous is not None and request in active:
                share += (total - previous) // len(active)
            if kind == 'start':
                active.add(who)
                if who == request:
                    started = True
            else:
                active.discard(who)
                if who == request and started:
                    finished = True
            previous = total
            if finished:
                break
        if not started:
            return None
        if not finished and now_spend is not None and previous is not None and request in active and now_spend > previous:
            share += (now_spend - previous) // len(active)
        return max(0, share)
