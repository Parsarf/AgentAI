"""TEST-ONLY fake payment provider — clearly labeled, never shipped.

This module exists ONLY so the provider-independent purchase path
(core.purchases) can be exercised end to end in tests. It is never imported
by runtime code; production runs with ``core.purchases.get_provider() is
None``, which denies every purchase in preflight.

It records every attempt so tests can assert "zero provider calls on denial"
and "no double charge", and its idempotency contract mirrors what a real
provider must offer:
- ``execute`` keyed by idempotency key: the same key replays the SAME outcome
  without a new charge (this is the no-double-charge seam).
- ``lookup`` resolves past submissions; beyond ``idempotency_retention`` it
  returns None (the key is gone — reconciliation, not a new payment).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from core.purchases import ProviderOutcome


class FakePurchaseProvider:
    """Scriptable fake. Install via core.purchases.set_provider(fake) and
    ALWAYS reset with set_provider(None) (the purchase_env fixture does)."""

    name = "fake-test-only"

    def __init__(self, retention: timedelta = timedelta(hours=24)) -> None:
        self.idempotency_retention = retention
        self._installed_at = datetime.now(UTC)
        self._results: dict[str, ProviderOutcome] = {}
        self._scripts: dict[str, Callable[[dict], ProviderOutcome]] = {}
        self.executions: list[str] = []  # every execute attempt (incl. replays)
        self.charges: list[dict] = []  # only NEW successful charges
        self.lookups: list[str] = []
        self.delay: float = 0.0  # seconds to stall execute (timeout tests)
        self.retention_expired = False  # simulate keys older than retention

    # ---- scripting -------------------------------------------------------

    def script(self, merchant: str, outcome: ProviderOutcome) -> None:
        """Outcome for the next NEW execute against this merchant."""

        def _fn(purchase: dict) -> ProviderOutcome:
            return outcome

        self._scripts[merchant] = _fn

    def remember(self, idempotency_key: str, outcome: ProviderOutcome) -> None:
        """Pre-seed a provider-side outcome (simulates a submission that
        completed provider-side while our DB write failed)."""

        self._results[idempotency_key] = outcome

    # ---- provider interface ----------------------------------------------

    async def execute(
        self, user_id, purchase: dict, idempotency_key: str
    ) -> ProviderOutcome:
        self.executions.append(idempotency_key)
        import asyncio

        if self.delay:
            await asyncio.sleep(self.delay)
        if idempotency_key in self._results:
            return self._results[idempotency_key]  # idempotent replay: no new charge
        script = self._scripts.get(purchase["merchant"])
        outcome = script(purchase) if script else ProviderOutcome(
            status="succeeded",
            provider_ref=f"fake_{idempotency_key[:12]}",
            recipient=purchase["merchant"],
        )
        if outcome.status == "succeeded":
            self.charges.append(
                {
                    "key": idempotency_key,
                    "user_id": str(user_id),
                    "merchant": purchase["merchant"],
                    "amount": str(purchase["amount"]),
                }
            )
        self._results[idempotency_key] = outcome
        return outcome

    async def lookup(self, user_id, idempotency_key: str) -> ProviderOutcome | None:
        self.lookups.append(idempotency_key)
        if self.retention_expired:
            return None  # beyond idempotency retention: unresolvable here
        return self._results.get(idempotency_key)
