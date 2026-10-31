# Hosted billing (Phase 13) — Stripe test mode, built offline

Commercial access is derived only from **verified provider state** and written to the same
`entitlements` table the Phase 5 budget ledger already reads. A task needs an eligible entitlement and a
reservation to start, so billing can never be bypassed by a redirect, a client field or a stale page.
Card details stay with Stripe's hosted pages. Live mode is refused in code unless the owner explicitly
authorizes it (`AGENTAI_BILLING_ALLOW_LIVE=1`, not set anywhere).

## Access modes (two owner switches on the dashboard)

| `billing_checkout` ("Require payment") | `open_access` ("Free access") | Result |
|---|---|---|
| off | **on** (current setting) | Every active account gets a rolling `open` entitlement with the plan limits ($25/month, $15/day, $5/task, 3 queued; allowance resets each calendar month). Subscribe buttons stay hidden. |
| off | off | Invitation-only as before: only trial/paid entitlements grant access. |
| **on** | any | Payment required: the worker ends every `open` entitlement within one pass (about 30 s); accounts without a paid plan are paused. Payment wins over free access, so there is no state where both apply. |

Free access never overrides paid access or a dispute hold, supersedes an invitation-trial row while it lasts, and lapses on its own after
3 days if the worker stops refreshing it (fail closed). `billing_worker` applies it on every run and needs no Stripe configuration.

## Access policy (one pure function: `derive_access`)

| Provider/ledger state | Entitlement | New tasks | Running/reserved work |
|---|---|---|---|
| `active`, before period end | `active` until period end | allowed | continues |
| `active` + cancel at period end | `active` until period end (no renewal) | allowed until period end | continues |
| `active` but period ended with no renewal | `expired` | denied | drains and settles |
| `past_due` (first failure seen at T) | `grace` until T + 72 h (from `plan.json` `billing_grace_hours`) | allowed | continues |
| `past_due` after 72 h | `expired` | denied | drains; billing pages and export stay available |
| `canceled`, `unpaid`, `incomplete*`, `paused` | `expired` | denied | drains |
| `trialing`, unknown status, unknown price, >1 line item | `expired` (fail closed) | denied | drains |
| open dispute | `suspended` | denied | drains |
| full refund of the paid invoice (or lost dispute) | `expired` (`refunded`) until a later paid period | denied | drains |
| partial refund | unchanged | unchanged | unchanged |
| later `invoice.paid` with `active` subscription | `active` again (reactivation only from verified state) | allowed | — |

Receipts are never rewritten: refunds, cancellations and disputes only stop *new admissions*. Period limits
come from `product/plan.json` ($25 included, $15/day, $5/task, 3 queued, no automatic overage) and the
period start moves with each paid period, so the allowance resets on renewal. Time-based ends (period end,
grace end) take effect from the stored `valid_until` even if a webhook never arrives; `billing_worker`
re-labels states and `--reconcile` corrects drift from Stripe's canonical objects.

## Data model (`migrations/0013_billing.sql`; no foreign keys to `accounts`, so required financial records survive account content deletion)

`billing_customers` (account ↔ `cus_`), `billing_checkout_sessions`, `billing_subscriptions` (provider status, periods,
refund/dispute flags, derived access), `billing_invoices` (hosted-URL only on `*.stripe.com`),
`billing_flags` (refund/dispute objects), `billing_inbox` (event id primary key, sha256, state, attempts, error code),
`billing_operations` (provider mutation ledger with idempotency key and `pending/applied/uncertain`).

## Flow

1. **Checkout** (`POST /v1/account/billing/checkout`, owner switch `billing_checkout`): account is the signed-in account; the
   price is the one configured plan; quantity 1; URLs are fixed. Customer creation and the session use durable idempotency keys
   (`cust-<account>`, `chk-<account>-<plan>-<n>`); a duplicate click returns the same open session; an outage leaves the operation
   `uncertain` and the retry reuses the same key so the provider returns the original object.
2. **Webhook** (`POST /v1/billing/webhook`): size cap, per-source rate limit, HMAC-SHA256 over `timestamp.rawbody` with 5-minute tolerance, any active
   secret accepted (rotation), non-`v1` schemes ignored, live-mode events refused, event stored (event id primary key) **before** `200`.
3. **Worker** (`manage.py billing_worker`, timer unit prepared): leases stored events, **fetches the canonical object** (never trusts the
   payload or its order), maps customer → account only through rows this platform created, recomputes access, writes the entitlement
   idempotently, audits changes, retries provider outages with exponential backoff, dead-letters permanent failures after 8 attempts or
   immediately for unmapped objects, and clears the stored payload once applied.
4. **Billing page** (`/account/billing/`): plan, status, grace/cancel dates, confirmed-by-provider vs held-estimate usage from the
   Phase 5 ledger, invoice links, hosted portal for payment recovery and cancellation.

## Configuration (all private files; nothing secret in settings, logs or responses)

`AGENTAI_BILLING_SECRET_KEY_FILE`, `AGENTAI_BILLING_WEBHOOK_SECRET_FILE` (one `whsec_` per line), `AGENTAI_BILLING_API_VERSION` (pinned
`Stripe-Version`), `AGENTAI_BILLING_PRICE_ID`, `AGENTAI_BILLING_PLAN_FILE`, `AGENTAI_BILLING_PUBLIC_ORIGIN`. `deploy/billing_install.py`
validates and installs them and records only the owner-switch facts it verified.

## Events subscribed

`checkout.session.completed`, `customer.subscription.created|updated|deleted|paused|resumed`, `invoice.paid`,
`invoice.payment_failed`, `invoice.payment_action_required`, `invoice.finalized`, `charge.refunded`,
`charge.dispute.created|updated|closed` (`REQUIRED_EVENTS` in `billing.py`).

## Not done / by design

No SDK dependency: a small stdlib client with a pinned API version replaces it. No live keys, no live payment, no tax or
refund-term decisions (open legal items in `product/CONTRACT.md`). Agent purchasing authority is separate and untouched.
Production deployment of migration 0013, the routes and the worker is a later, owner-authorized step; the code is not on the server.
