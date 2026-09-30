# Phase 19 — Optional later release: customer-funded purchases

**Stage:** Optional follow-on build and acceptance. **Dependencies:** accepted
baseline Phases 15–18, explicit selection of this separate release, supported
provider/funding connection and verified native authorization boundary.
This preserves unfinished legacy purchase requirements; it is not a baseline
launch dependency and remains disabled unless separately selected/authorized.

## Paste this prompt

Execute only the separately selected Phase 19 release. Read the shared execution
contract, coverage ledger, product contract, current BUILD_LOG/architecture/runbook
and provider documentation. Preserve the baseline and do not restore retired
Python payment code or invent a second agent approval engine.

## Work and completion criteria

1. Verify a provider can buy the intended supported item for a verified merchant/
recipient/order using this customer's own connected funds, with durable receipts,
idempotency and status lookup in a sandbox. Platform subscription checkout does
not prove arbitrary-merchant purchase support. No fallback to operator funds or
another account. Missing capability leaves purchases disabled while independent
preflight/persistence/UI work can continue with a clearly test-only fake.
2. Keep one supported provider, one currency (legacy default USD), one funding
connection/account and one durable lifecycle. Use exact decimal monetary units.
Never collect/store/model-expose PAN/CVC. Hosted connection proof is server-side,
account-bound and separate from subscription/opt-in. Expose only status/hints,
merchant allowlist, transaction/monthly caps and explicit opt-in/out/revoke.
3. Validate provider enabled, entitlement, opt-in, funding identity/connection,
merchant/recipient/order, finite positive precision/currency and hard caps before
requesting approval. Invalid preflight creates no approval and no provider call.
Canonicalize merchant registrable domains with a maintained suffix list; reject
userinfo tricks, public suffixes, IP hosts and recipient/domain mismatch. Native
approval binds account/task/invocation/order/amount/currency/connection/expiry.
Unattended purchases require explicit approval; stricter denial always wins.
Default all purchases to explicit approval unless an exact interactive rule is
separately authorized and natively enforceable. If no supported enforcement path
exists, do not expose purchase tools or browser checkout authority.
4. Persist a server-owned immutable purchase ID and intent/order identity before
execution. Changed details cannot reuse approval/idempotency. Atomically claim
and reserve succeeded/executing/unknown amounts against customer caps; release
DB locks before network calls. Recheck opt-in/entitlement/connection/expiry/caps
at execution. Model-created new IDs cannot turn a replay into a new purchase.
5. Use awaiting-approval/ready/executing/succeeded/failed/unknown/denied/expired
states with audited legal transitions. Timeout after submission remains unknown
and reserved. Reconcile by receipt/same provider key at restart; idempotency-key
expiry never authorizes a new charge. Preserve original UTC calendar-month
allocation across rollover; refunds do not automatically free allowance in the
initial release. Outcome notifications are deduplicated state transitions; failed
notification cannot undo a charge or cause another one.
6. Show scoped status/receipts and approval payload/expiry through verified
surfaces. Deny browser checkout bypass. Test disabled/opted-out/invalid funding,
deceptive merchants, caps, job-auto rules, replay/wrong-user/changed payload,
opt-out/downgrade while waiting and secret canaries with zero provider effects.
Then test authorized sandbox success, concurrent cap admission, duplicate calls,
provider-success/DB-failure, acceptance timeout, restart, month rollover and
no double charge through the real native/tool dispatch boundary.
7. Run paid/provider evaluation only under explicit resumption and budget; use
no real purchases to verify. Prepare a separate release checklist/security review,
customer disclosures, disable/rollback and activation diff. Live funds require
explicit authorization for that operation. Baseline launch remains usable while
this optional feature is blocked. Refund/dispute/recurring/multiple-provider
expansions remain explicitly later scope rather than implicit capability.

Deliver provider capability evidence, safe disabled preflight/state/UI, sandbox
results, separate caps/ledger/audit, review and release/rollback package. Done when all denial/recovery assertions and a real supported provider sandbox path
pass, and any separately authorized rollout is observed. A fake-only build is
READY/PARTIAL with acceptance BLOCKED, not completed purchases.

## Required close-out

Use `plans/product/phase-19.md` and `evidence/product/phase-19/<UTC-run-id>/`;
update the requirement ledger, contract/runbooks and BUILD_LOG. Report real
provider proof versus mocks, cost/unknowns, disabled state, blockers and rollback.
Stop after this separately scoped release unless further work is authorized.
