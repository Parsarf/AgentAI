# Legacy AgentAI revised phase prompts: 5–7

For the new single-owner OpenClaw plan, use
[openclaw/README.md](openclaw/README.md). This file documents the older
multi-user Python service; its Phase 6 purchase work remains disabled and
Phase 7 is unfinished.

Use these in order, one per coding session. Phases 1–4 are already built;
these prompts extend that implementation. These are now the only phase 5–7
prompt files.

| Phase | Revised prompt | Main change |
|---|---|---|
| 5 | [phase-5-lean-billing.md](phase-5-lean-billing.md) | Accurate SDK metering, concurrent budget enforcement, flat Stripe subscriptions |
| 6 | [phase-6-lean-payments.md](phase-6-lean-payments.md) | One supported provider, preflight before approval, durable retry-safe purchases |
| 7 | [phase-7-lean-tests-ops.md](phase-7-lean-tests-ops.md) | Reuse pytest, one app process, disposable restore verification, cheap load tests |

Paste an entire phase prompt from the workspace root. Each prompt explains its
intentional changes to the build spec and has its own acceptance rules.
Read the latest build notes before executing; this review did not implement any
of the phases or re-run application tests.

## Why these changes

The review used the original prompts, relevant spec sections, current code,
and build notes through Phase 4. These are proposed implementation improvements,
not measured savings or a claim that the current application is production-ready.

| Change | Benefit | Boundary retained |
|---|---|---|
| Flat subscriptions first; defer usage-based overage invoices | Less billing state and fewer provider calls | Real cost ledger, usage display, hard caps |
| Meter the actual SDK path, including cache usage | Avoid missing costs and misleading budgets | Verify actual SDK messages; unknown usage isn't zero |
| Atomic reservations for concurrent paid work | Stops concurrent tasks spending the same remaining budget | Short DB transactions; no new infrastructure |
| Indexed usage queries; optimize only after measurement | Avoid premature counters/cache invalidation | Durable ledger remains authoritative |
| Deduplicated warnings and bounded retries | Less notification noise and wasted calls | Clear refusal and visible failures |
| Reuse watcher checks/skills; no LLM in accounting | Lower cost and latency without quality guesswork | Existing worker quality stays the default |
| Validate the purchase provider's actual capabilities | Avoid building a payment flow that cannot buy the intended item | No fake production success; unsupported spending stays disabled |
| Reject invalid purchases before generic approval | Fewer pointless approval interruptions | Job approval floor and all hard denials remain |
| Persist purchase identity and unknown outcomes | Prevent duplicate purchases after timeout/restart | One small state machine, not a workflow platform |
| Hosted connection, one provider/currency | Smaller secret surface and fewer edge cases | User opt-in and own funds only |
| Pytest-backed scenario manifests | Avoid a second testing language/runtime | Critical failures and missing evidence still block release |
| One app process including Telegram | Fits the current in-memory event bus | Document capacity limit; don't pretend workers share state |
| Fake external boundaries for normal/load tests | Repeatable, cheap verification | Real DB/container/provider checks remain separate |
| Disposable, encrypted backup/restore proof | Verify recovery without risking working data | Include profiles, keys required separately, tenant checks |

## Existing-code issues the prompts explicitly address

- `agent/core/orchestrator.py` invokes SDK `query()` directly; a router-only
  billing check cannot cover that path. SDK result handling currently updates
  task cost rather than inserting its usage into `api_costs` there.
- `agent/tools/base.py` can request high-risk approval before invoking a
  payment handler. Handler-only opt-in checks would run too late.
- `agent/core/events.py` stores subscriptions in process memory. Splitting the
  bot and app into separate services would need additional communication work.
- `agent/tests/conftest.py` resets a schema. Test-target guards come before
  broader verification, and restores never wipe the working database.
- Build notes document placeholder model prices and pending Docker production
  checks. Revised prompts require evidence instead of inheriting a DONE label.

Stripe-specific changes use its official [webhook guidance](https://docs.stripe.com/webhooks),
[idempotency behavior](https://docs.stripe.com/api/idempotent_requests), and
[connected-account payment-method flow](https://docs.stripe.com/connect/direct-charges-multiple-accounts).
Implementation must still verify the selected provider and pinned SDK APIs.

## Intentionally deferred

Metered overage charging, automatic model cascades, shared answer caches,
multi-agent execution, a new queue/broker, multi-process deployment, a custom
eval DSL, multiple payment providers/currencies, and large monitoring systems.
Add these only for a demonstrated requirement with a small measurable benefit.
The concurrency and retry protections included here are necessary money
correctness, not optional performance tuning.

Phase 6 may reveal a genuine missing provider decision. Its local work can
still finish, and Phase 7 can validate the core service with purchases disabled.
That is explicitly a partial capability release, not completion of all seven
phases. Provider mocks and skipped Docker checks never count as live proof.
