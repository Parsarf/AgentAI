"""The worker's side of the panel: while a run of a conversation is going, keep the customer's connected Chrome holding a fresh panel ticket. There is no withdrawal: when the
run ends the tickets simply stop and the last one lapses within 90 seconds, which leaves the panel just long enough to read how the task ended.

The worker (the app user, which alone holds the signing key) asks the browse service which computer is connected and pushes the finished ticket through it; the service
only relays an opaque string. Nothing here is on the run's critical path: every failure is swallowed, and with no key, no connected computer or the customer's "use my own
browser" switch off, it does nothing."""
from __future__ import annotations
import threading
import time
from pathlib import Path

from . import ticket as panel_ticket

EVERY = 30        # seconds between fresh tickets (a ticket lives 90)
RETRY = 5         # seconds before trying again when nothing could be handed over (no computer connected yet, the service busy)


def read_secret(path) -> bytes:
    """The signing key from its file (app user only; the browse service never reads it). Missing, unreadable or short (under 32 bytes) means the feature is off."""
    try:
        data = Path(path).read_bytes().strip() if path else b''
    except OSError:
        return b''
    return data if len(data) >= 32 else b''


class PanelOffer:
    def __init__(self, secret, rpc_factory, *, clock=time.time, every=EVERY, enabled=lambda: True):
        """secret() -> bytes ('' = feature off); rpc_factory(account) -> BrowseRpc-like callable(op, **params); enabled() -> the owner switch."""
        self.secret, self.rpc_factory, self.clock, self.every, self.enabled = secret, rpc_factory, clock, every, enabled
        self._next, self._lock = {}, threading.Lock()

    def tick(self, claim) -> bool:
        """Called from the supervision loop of a run. -> True when a fresh ticket was handed to the connected computer."""
        key = (claim.account_id, claim.conversation_id)
        if not claim.conversation_id:
            return False
        now = self.clock()
        with self._lock:
            if now < self._next.get(key, 0):
                return False
            self._next[key] = now + RETRY      # until it works: look again soon, without asking the service on every pass of the supervision loop
        try:
            if not self.enabled():
                return False
            secret = self.secret()
            if not secret:
                return False
            rpc = self.rpc_factory(claim.account_id)
            state = rpc('device_list')
            device = next((d['device_id'] for d in state.get('devices') or [] if d.get('connected')), None)
            if not state.get('allowed') or not state.get('use') or not device:
                return False
            minted = panel_ticket.mint(secret, claim.account_id, claim.actor_id, claim.conversation_id, device, now=self.clock)
            out = rpc('device_push', payload={'ticket': minted, 'conversation_id': claim.conversation_id, 'device_id': device, 'expires_in': panel_ticket.TTL_SECONDS})
            if not out.get('pushed'):
                return False
            with self._lock:
                self._next[key] = self.clock() + self.every      # handed over: the next fresh ticket is due in `every` seconds
            return True
        except Exception:
            return False
