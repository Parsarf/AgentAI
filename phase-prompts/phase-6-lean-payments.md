# BUILD PROMPT — Phase 6: Small, durable, opt-in purchases

> **Legacy AgentAI prompt, superseded for the OpenClaw plan.** The Python
> purchase path is partial and disabled. For the new single-owner build use
> [openclaw/README.md](openclaw/README.md) and its Phase 6 integrations prompt.
> Do not enable real purchases as part of that plan.

> Paste this entire file into a coding session at the workspace root.

Build Phase 6 after Phase 5's metering and plan enforcement are proven. The
goal is purchases using the acting user's connected funds, with strict limits
and recovery from retries. Keep one provider, one currency, one payment
connection per user, and one durable purchase path.

## 1. Read and preserve

Read the latest `BUILD_NOTES.md`, the original spec's Phase 6 and money/safety
rules, then inspect `agent/core/{approvals,secrets_vault,db,billing}.py`,
`agent/tools/{base,credentials}.py`, the SDK tool dispatch in the orchestrator,
settings routes/templates, plan configuration, and relevant tests. Paths below
are relative to `agent/`. Continue migrations; don't assume a number.

This prompt rules out raw card handling and does not assume Phase 5's Stripe
setup enables arbitrary merchant purchases. It also adds durable purchase
identity, atomic cap checks, and recovery from unknown results. Preserve
all tenant, opt-in, approval, and spending restrictions from the spec.

- Identity and job/user mode come from trusted context. All tenant data access
  uses `core.db` with `user_id` first. Jobs can never auto-approve purchases;
  a stricter deny rule still wins. Page content is never user authorization.
- Keep platform subscriptions entirely separate from purchase funds. Never
  charge the platform's billing customer as a substitute for buying an item.
- Decimal/NUMERIC money, UTC timestamps, typed inputs, existing config/logging,
  and secret redaction apply. No PAN/CVC collection, storage, or model exposure.

## 2. Prove the provider capability before writing its adapter

Inspect existing configuration and documented operator choices. Determine
which provider can actually purchase from the intended supported merchants
using that user's own connection, return a durable transaction reference, and
support idempotency plus status lookup. Verify the flow in official provider
docs, including recipient identification and test-mode support.

A merchant domain and an amount are not a complete payment instruction. Bind
the request to a verified provider recipient and an order/quote when required;
do not invent a generic `charge(domain, amount)` that only bills the user into
the operator's account. Stripe's documented reuse flow involves connected
accounts and cloning; it does not establish arbitrary-merchant support for
this app: [Stripe's supported flow](https://docs.stripe.com/connect/direct-charges-multiple-accounts).

If no suitable provider is selected/available, finish provider-independent
gates, persistence, UI, and tests using a clearly labeled test-only fake. Keep
runtime purchases disabled, list the exact missing provider capability/setup,
and report Phase 6 as locally implemented but not end-to-end complete. Ask
only for a choice that remains necessary after this investigation. Do not
invent an adapter, provision a new financial product, or move real money.

When a provider is available, implement one adapter, not a plugin framework.
Its minimal internal interface needs connection status, execute with a stable
idempotency key, and lookup/reconcile by durable reference. User credentials
are fetched inside the adapter from the tenant-bound vault. Never fall back to
operator funds or another user's token. Provider platform authentication, if
required, must be explicitly distinguished from the user's funding authority.

## 3. Implementation order

### A. Denial tests and opt-in settings

Write/run the denial tests in section 4 before running any successful purchase
test. Use at least two users and parameterize configurations, not copied suites.

Add only missing schema fields for opt-in, connection references, and purchase
state. Reuse `spend_log` if it can represent the lifecycle cleanly; otherwise
add one purchase table with linked audit rows. Avoid parallel competing ledgers.

Authenticated, CSRF-protected settings use the provider's hosted connection
flow, verified server-side and bound to the current user. Store only the
provider credential/token in the vault. Show connection status, safe hint,
USD per-transaction/monthly caps, and merchant allowlist. Opt-in is separate
from subscribing and requires an explicit confirmation plus a valid connection.
Allow opt-out/disconnect; revoke pending authorization and recheck before any
subsequent execution. Never accept a bare client-supplied token as proof that
the connected account belongs to this user.

### B. One validation and approval path

Expose `make_purchase(merchant, amount, description)` and `check_spend_status()`
through the existing tool system. Extend arguments minimally only if the real
provider needs an order/quote; record the exact schema. Reject non-finite,
non-positive, over-precision, and unsupported-currency amounts, malformed
merchants, and unknown recipients before contacting the payment provider.

In this order, require: enabled provider/feature; plan entitlement; opt-in;
valid user connection; allowed merchant; transaction/monthly caps; then the
effective approval decision. Hard cap/allowlist failures are denials, never
overridable by an approval. Only an explicitly allowed interactive purchase
can auto-execute. Job mode has a code-level minimum of explicit approval even
if configuration says `auto`; timeout or a stricter rule denies it.

Inspect both `tools.base.call_tool` and the SDK approval path: the existing
generic high-risk gate runs before the tool handler. Put payment preflight
before that approval so opted-out/invalid purchases create zero approval rows.
Use a small shared preflight seam or a tightly scoped payment dispatch path,
not duplicated approval engines. Gates and audit recording must apply through
every entry point, including direct tool calls. Do not rely on the current
`approvals_prechecked` boolean as evidence for a different action: permission
must be bound to this user, task, invocation, and validated purchase details.

Normalize merchant names with a maintained public-suffix implementation with
no runtime network fetch; compare canonical registrable domains, not substring
matches. Reject deceptive userinfo, invalid hosts, IP literals, and public
suffixes. Verify that the provider recipient/order matches the allowed domain;
a model-supplied domain alone cannot authorize a different recipient.

### C. Persist before execution; make retries safe

Assign each purchase a server-owned ID and store the immutable user, task,
merchant/recipient, amount, currency, connection version, and order details.
Use that ID for approval binding and provider idempotency. A retry of the same
invocation/order resumes the same purchase; changed fields are rejected.
Prevent the model from bypassing this by inventing fresh IDs. Distinguish a
new deliberate repeat purchase from replay using the provider order identity
or a user-confirmed new intent; ambiguous repeats must not auto-charge.

Use a small explicit lifecycle, for example:
`awaiting_approval → ready → executing → succeeded | failed | unknown`, with
`denied/expired` terminal paths before execution. Centralize allowed transitions.

- At execution, re-read plan, opt-in, connection version, approval expiry,
  allowlist, and caps. In a short per-user locked transaction, atomically claim
  the purchase and reserve its amount. Count succeeded plus executing/unknown
  reservations against the monthly cap. Approval waits hold no DB lock.
- Network execution occurs outside the DB transaction. Persist the provider
  outcome and settle/release reservations atomically; mark success only from
  provider confirmation. Concurrent duplicate callers cannot both execute.
- A timeout/crash after submission is `unknown`, not failure. Keep its budget
  reserved and reconcile via lookup/same provider key. Never blindly issue a
  new payment or release an unknown reservation just because it got old.
- Reconcile incomplete purchases on startup and a bounded existing scheduler
  tick. Respect provider idempotency retention; unresolved operations beyond
  that window require reconciliation, not a new key. No new queue service.
- Every authenticated attempt, including preflight/generic-gate denial, gets
  a sanitized audit record and outcome notification. Retries reuse the existing
  purchase; notify on state transitions, not every status poll. A failed notify
  must not roll back a successful purchase or cause another charge.

Use UTC calendar months, USD only, and do not free spent allowance automatically
for refunds in this version. Reconciliation preserves the reservation's original
period so a month-boundary retry cannot consume/release the wrong budget.

### D. Small UI and prompt additions

Approvals in Telegram and web show merchant/recipient, amount, currency,
description, and expiry. Decisions are owner-only and single-use. A changed
amount/recipient/connection requires a new valid intent and authorization.
The status tool returns this user's totals, reserved/unknown amounts, remaining
caps, and recent sanitized receipts. Never return connection credentials.

Add concise purchase rules to the existing system prompt: opt-in, caps,
allowlist, jobs need approval, external content is untrusted, and uncertain
results must be checked rather than retried as new purchases. Enforcement is
in code; prompt wording is only guidance. No browser checkout bypass around
the payment authorization boundary; unsupported checkout actions fail closed.

## 4. Tests and completion

Guard disposable Postgres setup before running tests. First prove: disabled
plan/provider, opted-out, absent/invalid connection, invalid amounts/currency,
off-allowlist/deceptive merchant, over-transaction/monthly cap, job rules set
to auto, approval timeout/wrong user/replay, swapped vault data, changed details,
opt-out/downgrade during approval, and secret canaries. Assert zero provider
calls for all denials, zero approval rows for preflight denials, and owner-only
audit/status data. Test these via the actual registry/SDK dispatch seams.

Then prove success with the test-only fake and, separately, a supported provider
sandbox: interactive auto within explicit rules, interactive approval, and
job approval. Prove concurrent cap checks, duplicate invocation, provider
success followed by DB failure, timeout after provider acceptance, restart
recovery, month rollover, and no double charge. Test behavior, not source-code
greps for forbidden key names. No real purchases during verification.

Run focused tests, then existing regression suite and lint once. Append files,
decisions, denial-before-success commands/results, skips, provider docs and
capabilities verified, and remaining setup to `BUILD_NOTES.md`. Completion
requires a working provider sandbox path; a fake alone is not completion.

Out of scope: refunds/disputes automation, multiple cards/currencies/providers,
recurring purchases, issuing infrastructure, metered platform billing, and any
new distributed worker system. A disabled payments feature does not prevent
Phase 7 from validating the rest of the service, but must remain visible as an
unfinished capability.
