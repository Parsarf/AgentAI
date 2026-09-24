# BUILD PROMPT — Phase 5: Lean billing and trustworthy cost limits

> Paste this entire file into a coding session at the workspace root.

Build Phase 5 on top of the completed Phases 1–4. Optimize for low operating
cost, predictable behavior, and few moving parts. Implement the work, test it,
and report evidence. Do not rebuild earlier phases or merely produce a plan.

## 1. Scope and precedence

The application is a multi-user Python/asyncio agent using asyncpg/Postgres,
FastAPI/Jinja, Telegram, the Claude Agent SDK, and per-user tools and secrets.
Application paths below are relative to `agent/`; prompts, the original spec,
and `BUILD_NOTES.md` live at the workspace root.

Read the latest Phase 4/3 entries in `BUILD_NOTES.md`, the original spec's
Phase 5 and shared safety context, then inspect only the relevant code:
`core/{router,orchestrator,db,config,approvals}.py`, `tools/{base,web}.py`,
`gateway/web_app.py`, `gateway/templates/usage.html`, `main.py`, plan config,
and their tests. Expand inspection when a dependency requires it.

This prompt chooses **flat subscriptions plus hard usage caps** instead of
metered overage. The original spec allows flat tiers. Other safety requirements remain.
Keep completed-phase behavior unless a focused fix is required for this phase.
Continue migrations from the actual directory; 0005 exists as of this review.

Non-negotiable rules:

- Trusted task/session context supplies `user_id` and `task.source`; model or
  browser content cannot set identity, plans, prices, or authorization.
- Tenant queries go through `core.db`, with `user_id` first. Document narrow
  service-only exceptions for verified Stripe-customer lookup and maintenance.
- Platform billing is separate from agent purchases. Build no purchase tool.
- Money uses Decimal/NUMERIC; timestamps are UTC-aware. Configuration comes
  from `core.config.settings`; redact secrets in all output and fixtures.
- Critical accounting is awaited and committed to Postgres. Use the existing
  event bus for notifications after commit, never as the accounting ledger.

## 2. Keep the implementation small

Use existing modules, templates, asyncpg, and the pinned Stripe SDK. No Redis,
queue service, microservice, new ORM, frontend framework, or general billing
engine. Keep a single app process. Prefer direct typed functions for required
results and events for notifications. Do not upgrade dependencies wholesale.

Missing Stripe keys block provider validation, not local implementation or
tests. `billing.enabled=false` disables Stripe flows but still enforces caps.
Enabled billing with missing/invalid configuration must fail clearly. Default
to test mode; live mode requires an explicit production setting and credentials.
Do not print or inspect secret values in reports.

## 3. Implement in this order

### A. Fix metering on the actual execution path

Trace one task from submission through SDK completion and a search tool call.
The current orchestrator calls SDK `query()` directly, not `router.call()`;
it updates `tasks.cost_usd` without itself inserting SDK usage in `api_costs`.
Its `_usage_cost()` also assumes attribute-shaped usage. Prove and fix these
paths using the installed SDK's actual message types and local package source.
Check current official SDK/provider docs only where local evidence is lacking.

- Give every billable operation a stable server-owned identifier and make
  recording it idempotent. A retried completion must not add its cost twice.
- Normalize actual SDK usage, including per-model and cache usage when
  supplied. Do not count cumulative totals as fresh usage or count SDK and
  router records twice. Include search and other configured paid operations.
- Persist measured usage for errors/cancellation whenever available. Missing
  usage is an explicit unresolved accounting state, never silently zero.
- Validate configured prices for every enabled model. Record their source and
  verification date; existing prices are documented placeholders. Keep provider
  cost distinct from the flat price charged to the customer. Round once at the
  accounting boundary and convert currency minor units only at provider APIs.
- Keep `api_costs` the durable cost ledger; make `tasks.cost_usd` and reporting
  summaries agree with it. Do not introduce another independent cost truth.

### B. Enforce budgets before paid work, including concurrent tasks

Implement `core/billing.py` with typed summaries and limit decisions. Reuse
the current public interfaces where practical:

```python
usage_this_period(user_id) -> UsageSummary
check_within_limit(user_id) -> LimitCheck
```

Use UTC calendar-month usage windows `[start, next_start)` to preserve current
behavior. Stripe subscription renewal dates are separate and must be labeled
as such. A plan change never erases current-month usage.

- Check at task admission, after waiting for a concurrency slot, and before
  paid work. Cover SDK calls as well as `router.call()` and paid search.
- Use a small persisted reservation record per billable operation or bounded
  SDK run. Within a short transaction, lock the user's budget row, check
  `settled cost + outstanding reservations + requested reservation <= cap`,
  and reserve. Different users must not serialize behind a global lock.
- Settle actual cost and release the remainder atomically and idempotently.
  Keep unresolved reservations after ambiguous failures until reconciled;
  expiry alone must not declare a possibly billed call free. Never hold a
  transaction/DB connection open through a model call or approval wait.
- Use verified SDK budget/turn controls and bounded inputs/outputs. A tool
  permission hook alone does not limit internal model calls. If the SDK cannot
  enforce the required boundary, use the smallest supported bounded execution
  change and test it. Report any measured overshoot and stop claiming strict
  hard-cap enforcement until the bound is proven. Do not rewrite the agent loop
  speculatively or release paid billing with an unbounded path.
- On exhausted budget, refuse clearly with the plan and `/usage` link; do not
  silently change model quality. Other users continue normally. Actual charges
  above a reservation still get recorded and block further paid work.
- Send the 90% warning once per user/period/threshold, not once per call.
  Show reserved versus settled usage clearly when relevant.

Use indexed tenant-and-period queries initially. `usage_periods` is a reporting
snapshot, not permission to spend from stale data. Refresh on demand and, if
needed, for recently active users using the existing scheduler. Add a cached
counter only if measurement shows the indexed query is a bottleneck; it must
update in the ledger transaction and be rebuildable from the ledger.

### C. Flat Stripe subscriptions and a small billing page

Use one configured recurring price per paid plan, Stripe Checkout for signup,
and the Billing Portal for management. No overage meters, invoice generator,
card-entry form, coupons, or tax engine in this phase. Label any internal
allowance excess as usage, not a charge; the configured hard cap is the limit.

- Authenticated, CSRF-protected POST actions start checkout/portal sessions.
  Resolve customer and price server-side; permit only configured plans and
  return URLs. Protect against duplicate customer/subscription creation.
- Use persistent operation IDs/provider idempotency keys for retried creates.
  Verify APIs against the pinned Stripe version and official documentation.
  Prefer native async methods; isolate bounded synchronous calls if necessary.
- Verify raw webhook bodies and signatures. Persist event identity and apply
  entitlement changes atomically; duplicate delivery returns success without
  duplicate effects. Failed processing must remain retryable.
- Handle checkout completion, subscription changes/cancellation, invoice
  failure, and payment recovery. Derive access from verified subscription
  state, not checkout redirects or arbitrary metadata. Resolve out-of-order
  events against current provider state, with bounded calls and serialized
  updates per subscription; old events cannot restore canceled access.
- Define active, canceled, unpaid, and past-due/grace behavior explicitly.
  Store billing state separately from account security status; a payment event
  must never reactivate a suspended account. Enforce any grace expiry locally.
- `/usage` shows this user's usage, cap, reset time, plan, subscription state,
  and hosted upgrade/manage links. The success page waits for verified state.

Stripe references: [webhook delivery and verification](https://docs.stripe.com/webhooks),
[request idempotency](https://docs.stripe.com/api/idempotent_requests).

### D. Live plan enforcement and cheap execution defaults

Re-read current entitlements at execution boundaries: jobs, browser tools,
approvals, paid work, and concurrency admission. A hidden tool is not an
authorization check. A downgrade affects queued work and the next relevant
action without restart; do not kill a completed external action retroactively.

Keep existing worker quality by default. Reuse deterministic watcher checks
and saved skills; don't add LLM calls to billing, approvals, classification,
warnings, or webhook handling. Bound tool output and retries. Retry transient
failures with capped backoff/jitter in one layer; avoid SDK × app retry loops.
Do not retry cap/authentication/validation refusals. Add cheap-model routing
only for a demonstrated narrow workload with a quality regression test; defer
automatic cascades, multi-agent routing, and cross-user response caches.

## 4. Verification and completion

First guard test setup: the existing fixture drops a database schema. Verify a
disposable test DSN distinct from the app DSN before running it. Use a real
Postgres for transaction/concurrency tests; mock only external boundaries.

Cover: real orchestrator-to-ledger wiring; dict/object SDK usage as applicable;
cache costs; duplicate results; search costs; cancellation/missing usage;
month boundary; simultaneous reservations near the cap; task queued during a
downgrade; warning deduplication; invalid/duplicate/out-of-order webhooks;
failure then recovery; customer/route isolation; disabled billing with active
caps; and a tiny task that reaches the actual model boundary. Fixtures must
not fix missing production context or bypass the gate being tested.

Run focused tests during changes, then the existing suite and lint once at
handoff. Separately run a small Stripe test-mode subscribe → use → invoice →
cancel cycle when keys are available. Local mocks are not provider validation.
Do not repeatedly spend on live model tests; use one bounded smoke test when
needed and record the cost. No live customer charges.

Done means the ledger is accurate, concurrent paid work cannot evade the
verified budget boundary, plans tighten live, hosted billing works in test
mode, and existing flows pass. If external validation or a budget guarantee
is missing, report it explicitly as incomplete, while delivering tested local
work. Append changed files, decisions, exact test results/skips, measured
cost/latency where available, and remaining setup to `BUILD_NOTES.md`.
