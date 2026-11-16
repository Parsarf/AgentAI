"""Credential refresh (roadmap #16): provider tokens are renewed before they end, by one background job, one connection at a time.

Rules:
* a lock per connection, taken in the database, so two workers never refresh the same connection at once (with some providers a second refresh invalidates the first);
* a failure is one of three kinds. `temporary`: try again later, with a growing pause. `needs_customer`: the connection is marked "needs you", its customer is told once, and
  work that needs it stops at its next call with that reason. `revoked`: the provider ended the access, so the connection goes through revocation (#17);
* tokens only ever live in custody: the new ones are sealed before the old reference is dropped, and nothing here logs or returns one. What is logged is the connection id
  and the outcome, nothing else;
* remote MCP connections that use OAuth are kept fresh by the same job (their own service does the provider call and holds their credentials).
"""
from __future__ import annotations
import json
import logging
import time

log = logging.getLogger('agentai.connectors')

LEAD_SECONDS = 600                 # refresh this long before the token ends
LOCK_SECONDS = 120                 # a refresh that has not finished in this time is considered dead and may be tried again
BACKOFF = (60, 300, 900, 3600)     # pauses after temporary failures
OUTCOMES = ('refreshed', 'temporary', 'needs_customer', 'revoked', 'skipped')


class RefreshFault(Exception):
    """What a refresher raises. `kind`: temporary | needs_customer | revoked."""
    def __init__(self, kind):
        if kind not in ('temporary', 'needs_customer', 'revoked'):
            raise ValueError('unknown refresh fault')
        super().__init__(kind); self.kind = kind


class ConnectorRefresher:
    """`refreshers`: {service: callable(tokens: dict) -> {'tokens': dict, 'expires_in': seconds or None}}, raising RefreshFault. A service with no refresher is left alone
    (its tokens do not expire, or it is an MCP wrapper). `mcp`: the remote MCP ConnectionService, or None."""

    def __init__(self, store, connectors, refreshers: dict | None = None, *, mcp=None, clock=time.time, lead=LEAD_SECONDS):
        self.store, self.connectors, self.refreshers, self.mcp, self.clock, self.lead = store, connectors, refreshers or {}, mcp, clock, lead

    def due(self) -> list[dict]:
        now = int(self.clock())
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT account_id,id,service,secret_ref,refresh_failures FROM connector_connections
                WHERE state='connected' AND secret_ref IS NOT NULL AND expires_epoch IS NOT NULL AND expires_epoch<=? AND coalesce(refresh_after_epoch,0)<=?
                AND coalesce(refresh_lock_epoch,0)<=? ORDER BY expires_epoch LIMIT 50""", (now + self.lead, now, now - LOCK_SECONDS))]

    def _lock(self, row) -> bool:
        now = int(self.clock())
        with self.store.connect() as con:
            return con.execute("""UPDATE connector_connections SET refresh_lock_epoch=? WHERE account_id=? AND id=? AND state='connected' AND secret_ref=?
                AND coalesce(refresh_lock_epoch,0)<=?""", (now, row['account_id'], row['id'], row['secret_ref'], now - LOCK_SECONDS)).rowcount == 1

    def refresh(self, row) -> str:
        """Refresh one connection. -> one of OUTCOMES."""
        refresher = self.refreshers.get(row['service'])
        if refresher is None or not self._lock(row):
            return 'skipped'                               # no refresher, or another worker holds this connection
        account, connection, now = row['account_id'], row['id'], int(self.clock())
        outcome = 'temporary'
        try:
            tokens = json.loads(self.connectors.custody.get(account, row['secret_ref']))
            fresh = refresher(tokens)
            if not isinstance(fresh, dict) or not isinstance(fresh.get('tokens'), dict) or not fresh['tokens']:
                raise RefreshFault('temporary')
            new_ref = self.connectors.custody.put(account, row['service'], json.dumps(fresh['tokens']).encode())
            expires = fresh.get('expires_in')
            with self.store.connect() as con:
                swapped = con.execute("""UPDATE connector_connections SET secret_ref=?,expires_epoch=?,refresh_after_epoch=NULL,refresh_failures=0,refresh_lock_epoch=NULL,updated_epoch=?
                    WHERE account_id=? AND id=? AND state='connected' AND secret_ref=?""",
                                      (new_ref, now + int(expires) if expires else None, now, account, connection, row['secret_ref'])).rowcount == 1
            # The connection was removed while the provider was being asked: the new tokens must not outlive it.
            self.connectors.custody.delete(account, row['secret_ref'] if swapped else new_ref)
            outcome = 'refreshed' if swapped else 'skipped'
        except RefreshFault as fault:
            outcome = fault.kind
        except Exception:
            outcome = 'temporary'                          # custody or the network: nothing is known to be wrong with the connection itself
        if outcome == 'temporary':
            failures = row['refresh_failures'] + 1
            with self.store.connect() as con:
                con.execute('UPDATE connector_connections SET refresh_failures=?,refresh_after_epoch=?,refresh_lock_epoch=NULL WHERE account_id=? AND id=?',
                            (failures, now + BACKOFF[min(failures, len(BACKOFF)) - 1], account, connection))
        elif outcome == 'needs_customer':
            with self.store.connect() as con:
                con.execute('UPDATE connector_connections SET refresh_lock_epoch=NULL WHERE account_id=? AND id=?', (account, connection))
            self.connectors.needs_customer(account, connection, 'reconnect')
        elif outcome == 'revoked':
            self.connectors.revoke_by_system(account, connection, 'provider')
        log.info('connector_refresh connection=%s outcome=%s', connection, outcome)       # the id and the outcome, nothing else
        return outcome

    def tick(self) -> dict:
        """One pass: refresh what is due, finish removing the tokens of connections that were revoked, keep remote MCP OAuth connections fresh. -> counts by outcome."""
        report = {name: 0 for name in OUTCOMES}
        for row in self.due():
            report[self.refresh(row)] += 1
        report['purged'] = self.connectors.purge_revoked()
        if self.mcp is not None:
            try:
                report['mcp'] = self.mcp.refresh_due(lead=self.lead)
            except Exception:
                report['mcp'] = {'error': 1}
        return report
