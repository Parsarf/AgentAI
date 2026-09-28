# Phase 9 — Build optional browser optimization

Build phase 3 of the remaining sequence, optional. Execute only if the owner
selects this optimization; otherwise record EXCLUDED and finish the build stage.
Read the [execution contract](execution-contract.md), current browser-worker
configuration, remaining-build inventory, Phase 7–8 build artifacts and
[existing research](../../openclaw-project/research/jev-model.md).
No accepted evaluation gate is required merely to implement a disabled adapter.

## Required result

A narrowly scoped supported TypeSafe/Jev integration or small browser-worker
adapter, explicit action validation/permissions, fallback/kill switch, pinned
configuration, and runnable comparison fixtures. The optimized route remains
disabled during build; the existing browser route is preserved. No paid API
probes, confidence calibration, benchmarks or rollout until Phase 11 is selected
and authorized. Missing API access does not prevent independent adapter/config
work, but no invented model IDs, schemas or endpoint promises are acceptable.
The optional provider's account, data handling and spend are separate choices;
this prompt does not authorize new paid accounts or raised limits.

## 1. Establish fit, integration and billing

Check current primary sources and installed-version support:

- [TypeSafe models and pricing](https://docs.typesafe.ai/models)
- [Known Jev failure modes](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- [Confidence semantics](https://docs.typesafe.ai/confidence)
- [Confidence routing](https://docs.typesafe.ai/patterns/confidence-routing)
- [OpenClaw browser](https://docs.openclaw.ai/tools/browser)
- [OpenClaw security](https://docs.openclaw.ai/gateway/security)

Discover the actual supported model version, API/SDK, access, prices, token
limits, input/output types, privacy/retention terms and provider spending
controls. Pin the tested model and SDK/dependency versions. The previously
quoted $0.042/M input and free output are dated hypotheses to recheck; the
71× input-price ratio and illustrative 99% savings are not workflow results.

Prefer a supported native provider/plugin path if it preserves Jev's typed
decision API. Do not assume an ordinary chat-model alias can serve its API.
If a gap remains, document it and implement only the smallest adapter inside
the existing restricted browser-worker path. Verify the actual API schema;
never invent a model ID, endpoint, confidence field or OpenClaw config key.

Keep the TypeSafe credential server-side through the supported protected
secret path, inaccessible to page scripts and project execution. Confirm the
approved account and separate billing limits before live calls; Anthropic
proxy caps and ChatGPT quotas do not cover TypeSafe. Enforce an admission
budget for Jev plus planner/fallback calls and retries. Missing budget tracking
must stop the optimized route. Account for concurrent requests and in-flight
spend; label a local estimate as such, not as a provider-enforced hard cap.
Develop with synthetic pages and credentials' presence only. Private-site
deployment needs approved data handling and data minimization first.

## 2. Design the action loop and enforce its authority

Document the data flow and boundaries in `plans/phase-9.md`:

1. The existing planner supplies a bounded subgoal, allowed destinations and
   completion assertions. It owns long reasoning, new text/form values and
   screenshot interpretation. Jev receives only the focused subgoal, necessary
   sanitized page text/accessibility state and typed action candidates.
2. Code creates candidates from a fresh snapshot: stable reference, permitted
   action type, target label/role and relevant context. Include explicit
   `escalate`, `stop` and `no valid action` outcomes. Use deterministic code
   directly when the next step is unambiguous; not every click needs a model.
3. Jev chooses among those candidates. Validate the entire response against
   the pinned schema, requested IDs, finite probability values and candidate
   membership. Malformed/unknown outputs execute nothing. Never turn output
   into arbitrary selectors, shell commands, JavaScript or generated tool calls.
4. Code checks the current target identity, visibility/enabled state, current
   page/snapshot and effective native permission before executing one action.
   A changed page invalidates the old selection; do not reuse stale references.
5. After execution, observe and verify the expected state change. Read back
   values/navigation/task state; a plausible model answer is not success.
   Exact arithmetic, date comparison, counting and equality stay in code.
6. Escalate on ambiguous choices, low measured confidence, unsupported visual
   content, no progress, repeated actions or conflicting state. Use the existing
   authorized planner/browser path with a bounded factual summary. Do not
   copy raw hostile page instructions into privileged instructions.

Preserve the dedicated sandbox browser, authenticated control relay, native
approvals, destination restrictions and worker tool ceiling. Jev has no direct
browser/control credential, filesystem, messaging, scheduling, spawn or policy
authority. Confidence never grants permissions or substitutes for required
owner approval. Block unauthorized actions even when either model recommends
them with high confidence. Treat page content as untrusted data: TypeSafe
explicitly documents susceptibility to adversarial state.

Set per-task action/time/cost limits, loop detection, API deadlines, bounded
retries and cancellation. Handle provider outages, invalid responses, quota
exhaustion and fallback outages explicitly. Never silently switch to an
unapproved billing route. Reconcile uncertain submissions before retrying;
fallback must not duplicate effects. Retain the existing owner approval path
for consequential operations. Initial rollout covers approved routine actions.

## 3. Prepare fixtures and the comparison runner

Build deterministic synthetic sites with asserted goals: navigation, search,
filters, pagination, forms with fixture values, duplicate labels, disabled
controls, delayed render, stale targets, redirects, empty/error states and
missing accessibility data. Separate development/calibration fixtures from
frozen held-out evaluation scenarios; do not tune to the evaluation set.

Prepare route selection, reset/cleanup, paired execution, usage accounting,
whole-task latency/error reporting and trace correlation using Phase 7's native
runner. Author forged-action, injection, malformed-response, budget/outage,
cancellation and uncertain-effect/fallback cases. Do not run the paid calibration
or30-scenario benchmark in this build. Initial confidence thresholds are
explicit provisional settings; they are not measured reliability claims.

## 4. Lightweight setup checks and delivery

Check code syntax/type/build, dependency locks, native config schema/readback,
static action schema membership checks and the disabled route setting.
No provider call, benchmark, active browser objective or rollout. Credentials
remain behind the protected boundary; missing ones are documented, not copied
into fixtures. Build the rollback/kill-switch procedure without claiming it
has passed a live mid-task drill.

Produce `plans/phase-9.md`, adapter/config/source locks, development and held-out
fixtures, prepared runner, provisional thresholds, fallback/disable instructions
and `evidence/phase-9/<UTC-run-id>/` build manifest. Update architecture/runbook.
Build status READY/PARTIAL/BLOCKED; optimization acceptance DEFERRED to Phase 11.
All selected build phases now precede testing. Stop unless the owner explicitly
authorizes [Phase 10 system evaluation](phase-10-system-evaluation.md). Earlier
requests to defer tests remain in force; finishing code is not test permission.
