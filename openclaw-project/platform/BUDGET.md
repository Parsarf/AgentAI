# Phase 5 — offline admission and accounting core

`agentai_platform.budget.BudgetLedger` uses the existing metadata DB. Atomic
admission creates a queued task, reservation and append-only usage/audit entries
together after account/project/conversation authorization. Reject changed
idempotency payloads, unknown upper bounds, missing service allocation, invalid
currency, expired/ambiguous entitlement, task/period/rolling-day/service exhaustion
and a full three-task queue. A rejected admission creates no task or provider call.

Actual provider receipts remain separate from reservations, estimates and final
reconciliation. Receipt identity/payload/price/time changes are rejected; receipts
are append-only. Reported cost consumes the held allocation rather than being
counted again alongside the full hold. Unknown effects keep the remaining hold.
Only proved quiescence plus all-route reconciliation can release unused allowance.
Overrun receipts are retained and reduce future access rather than discarded.
Late usage marks reconciliation pending, then appends revised settlement/release
entries without changing old spend. Restoring spend state must still reconcile
with provider/backstop state before activation; the DB alone cannot enforce this.

`manage.py seed_trial --account <existing-id>` is host-only and prepares the
seven-day/$1 entitlement once. It sends no invitation, starts no cell, charges
nothing and refuses to reset an existing entitlement. No real account was seeded.
`GET /v1/costs` and `/account/usage/` read the same reported/held/remaining values
used for admission, bound to the verified current account. Expired accounts can
read usage but cannot admit work. Running estimates are explicitly unknown until
route adapters are connected. No write API accepts prices or usage assertions.

## Route readiness — no live provider accounting claimed

| Route | Receipt/price/enforcement integration | Activation |
|---|---|---|
| Gateway orchestrator/model routes | Missing per-account/task adapter and current price evidence | Off |
| Coding/native harness | Missing commercial route custody, attribution and dispatch fence | Off |
| Independent ACP review | Missing isolated identity, receipts and route admission | Off |
| Search/non-token tools | Missing actual call-fee attribution and upper bounds | Off |
| Optional embeddings/fallback/optimization | Not selected/verified against the task ledger | Off |

The owner's provider keys, OAuth login and existing $2/day+$25/30-day backstops
are unchanged and not borrowed for customers. A real service allocation is
unknown; `BudgetLedger` defaults it to None and denies admissions. The fixture
uses a tiny synthetic allocation and no paid routes. Provider upper bounds must
cover all planned calls/verification/retries/fallbacks and uncertainty; a client
cannot set `upper_bound_verified`. Integration must reserve incremental calls
within this task hold and bound route output/steps/time/concurrency, reconcile
crashes/late receipts, and prevent restoration/key rotation from resetting spend.
Task leases/global dispatch limits belong to the Phase4/5 worker integration,
not an entitlement that can override capacity. Real costs and provider data terms
need route-specific proof; no zero-cost provider assumption.

Build: admission/accounting component READY locally; full Phase5 PARTIAL because
all-route metering/dispatch, running estimates and native stop fences are missing.
Live paid/provider acceptance remains NOT_RUN Phase15. Billing checkout/webhooks
remain Phase13; no payment mode or price changes were made here.
