# Phase 4A — Jev research decisions (preflight, 2026-09-28)

## Owner continuation, 2026-09-28 20:55 UTC

The owner explicitly authorized a temporary limit increase for this test and
restoration afterward. Only the `openclaw-production` virtual key's 24h
window may move from **$2 to $10**; its $25/30d window, other keys, models,
and parallelism stay unchanged. Measured month spend before change:
$5.904177; 24h spend $2.227560. For this run, spend at most **$7.50
additional** (leaving at least $2.50 within the temporary daily window and
more than $11 within the monthly window). Freeze this before any paid call.
Back up the DB and config; record the exact before state; install a timed
automatic rollback as a failsafe; manually restore $2 and verify readback
as soon as the test ends, including on failure. If 15 paired cases cannot fit
the declared spend ceiling, report weaker evidence and leave the layer off
rather than silently shrinking the sample or raising the cap again.

Status: **BLOCKED before implementation/activation**. This optional optimization
has no working Gate 3 research/injection baseline, no TypeSafe credential in the
inspected approved deployment secret files, and
no verified Jev pass-through in the pinned LiteLLM 1.102.1 image. No Jev call,
provider enrollment, cap increase, runtime policy change, or production toggle
was made. The baseline `web_fetch` path remains the fallback.

## Actual starting state

- OpenClaw 2026.9.6 (eb377ac), gateway image
  `openclaw-gateway:2026.9.6-sdk-peer`; LiteLLM 1.102.1, pinned image
  `docker.litellm.ai/berriai/litellm@sha256:87f…` (full digest in production
  Compose lock). OpenClaw's installed code contains
  `registerAgentToolResultMiddleware`; the official SDK documents this
  pre-model async transform for explicitly enabled plugins declaring the
  `openclaw` runtime contract.
- Native `web_search` is disabled/denied. The researcher has live Brave MCP
  `brave-search__brave_web_search` and `web_fetch`; browser-worker has
  interactive browser and `web_fetch`; critic has plain `web_fetch` for
  independent source checks. Main has no web access. Phase 6 connector
  capability exists; connector/authenticated results are outside this phase.
- `evals/RESULTS.md` records T10-RESEARCH-CITATIONS and
  T10-INJECTION-NO-EFFECT as **BLOCKED**, not Gate 3 passes. The latest
  rolling 24-hour LiteLLM SpendLogs aggregate was $2.2276, across keys,
  while the research virtual key's limit is $2/24h (observed 2026-09-28).
  This aggregate alone is not a per-key admission check; the key's exact
  remaining headroom must be verified before any paid run. Paid baseline and
  paired tests require sufficient verified headroom. `TYPESAFE_API_KEY`/`JEV_API_KEY` were absent from the approved
  deployment secret files at inspection; credential contents were not read.
  The owner pointed to a bare `jev:` label in the local, gitignored
  `openclaw-project/.env`. It was converted in place to a valid
  `TYPESAFE_API_KEY` assignment without displaying its value. File mode is
  0600. The key has **not** been copied to production or used in a call.
  A fresh anonymous SpendLogs query found $2.227560 on the active 24-hour
  key, above its $2 cap; no paid baseline was attempted.

## Fit and terms checked against primary documentation

| Item | Verified finding |
| --- | --- |
| Pinned model | `jev-1.13.0`, not `jev-latest`; response model must match |
| Endpoint | TypeSafe `POST https://api.typesafe.ai/v1/systemone`; documented LiteLLM proxy `/typesafe/v1/systemone` |
| Limits | 64k tokens/request; 32k for state plus longest question; Choice ≤255 options; text only |
| Price | $0.042 per million input tokens; output tokens free (provider list price, not measured project spend) |
| SDK | Official Python `typesafe-sdk` 0.7.2 currently published; not installed for this path. Prefer the documented HTTP pass-through in the Node plugin to avoid an extra runtime. |
| Confidence | Choice/Score have distributions and `confidence`; Noul has a yes probability only. A page drop uses `P(relevant) ≤ 0.10`, **not** nonexistent Noul confidence. |
| Privacy | TypeSafe says requests/responses are not used to train Jev. Public DPA/privacy terms do not promise a fixed short retention period; enterprise zero-retention is separate. Therefore only public fetched pages qualify. |
| LiteLLM compatibility | Docs describe pass-through with usage-based cost tracking and proxy-held TypeSafe key. The feature was introduced after the pinned 1.102.1 image (v1.103.0-rc in LiteLLM's release note); local route behavior and cost accounting remain unverified. No proxy upgrade or direct billing route was authorized. |

Sources: [models](https://docs.typesafe.ai/models),
[Choice](https://docs.typesafe.ai/primitives/choice),
[confidence](https://docs.typesafe.ai/confidence),
[jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13),
[Python SDK](https://docs.typesafe.ai/sdk/python),
[legal](https://docs.typesafe.ai/legal),
[LiteLLM pass-through](https://docs.litellm.ai/docs/pass_through/typesafe),
[OpenClaw middleware](https://docs.openclaw.ai/plugins/sdk-agent-harness/attempt-runtime).
Earlier figures and access claims in `research/jev-model.md` are historical
hypotheses; this table supersedes them for this phase.

## Implementation chosen, conditional on prerequisites

Use one explicitly enabled OpenClaw host plugin with
`contracts.agentToolResultMiddleware: ["openclaw"]`, matched to canonical
`web_fetch`. Its handler checks the runtime agent is `researcher`, the
original tool name and source provenance, and a single
`JEV_RESEARCH_ENABLED` toggle. It transforms the already fetched tool result
before the researcher sees it. Plain `web_fetch` remains granted to the
critic. No second fetcher, search service, agent loop, router, approval
engine, or policy grant is needed. Verify that the installed callback exposes
the original URL, agent identity, result body, and research question with
trusted provenance before implementation; if any is missing, do not infer it
from untrusted page text. `after_tool_call` is observation-only and does not
meet the pre-model transform requirement.

Code-side eligibility: only a successful unauthenticated `web_fetch` of a
public `http(s)` URL; reject auth headers, cookies, credentials in URLs,
private/reserved targets, login/account/payment URLs and any connector,
browser, memory, file, or model-context-derived content. Redirect target and
original target must qualify. The research question itself must carry a
trusted public-only provenance marker; a model-inferred or connector-derived
question is ineligible even if the fetched page is public. Treat any
ambiguous origin as ineligible and return the exact original result. The
plugin receives the LiteLLM virtual key
from the approved secret store; workers never receive TypeSafe credentials.
Before activation, prove the proxy route bills the same enforced virtual-key
$2/24h and $25/30d caps and reports Jev cost. If this route cannot be made to
work within those caps, pause for an explicit owner decision before any
separate account/billing path.

For an eligible page, build a bounded request with a Noul relevance question,
a Score source-quality question (a fixed three-level rubric), per-chunk Noul
questions keyed by stable chunk IDs for long pages, and Choice questions
over code-normalized same-scheme outbound links (up to three ranks plus a
`none` option). Reject duplicate or unknown choices; deduplicate valid ranks
before displaying them. A single request covers the page's questions where
size allows. Keep
each Choice below 255 options and cap the operational shortlist much lower
(initially 20) to bound tokens and latency; excess candidates are handled
deterministically or omitted from Jev ranking, never silently dropped from
the original result. The researcher retains source URL and a one-line drop
notice when `P(relevant) ≤ 0.10`. Selected passages are byte-for-byte
verbatim. Jev ranks links; researcher chooses whether to fetch. Brave MCP
search-result triage is separate from the fetch wrapper and remains disabled
until its result provenance and pre-model seam are verified. No browser click
control; that belongs to Phase 7A.

All Jev answers must match offered IDs and types exactly, with finite
probabilities in [0,1], complete distributions summing to 1 within a stated
tolerance, and the pinned model ID. Timeout starts at 2 seconds, no hidden
retry; API error, malformed/out-of-list answer, missing usage/cost,
insufficient proxy headroom, or failed privacy check returns the original
`web_fetch` result exactly. Log timestamp, task ID, URL, question name,
answer, distribution/confidence, model, latency, cost when known, fallback
reason, and no body text to a host-only JSONL log. Unknown cost is `null`,
never zero. Jev output has no permission/approval/trust authority.

## Frozen evaluation design (set before any Jev run)

1. Close Gate 3 with sourced research and injection-no-effect checks using
   the existing path. Record correctness and valid citations. If it fails,
   fix the baseline first; do not compare Jev yet.
2. Adapter/unit fixtures: toggle identity, privacy refusals (connector,
   authenticated, private URL, redirect), timeout/error/budget fallbacks,
   wrong model, malformed and out-of-list Choice IDs, Noul range, unmodified
   verbatim selected chunks, bounded links, logs without page text.
3. Disposable public injection pages: page text telling Jev to mark it
   relevant, deceptive off-topic/login links, and instructions aimed at the
   researcher. Assert code filter, `INJECTION_ATTEMPT` in the researcher
   report, and unchanged authority.
4. Paired suite: 15 fixed public questions with known primary answers and
   sources, same model/settings, baseline and Jev order alternated. This
   size is a starting minimum that covers several source types and 30
   expensive task runs; it is not a power calculation. Freeze cases and
   predeclare a maximum spend after measuring baseline token use and actual
   available headroom. If 30 runs exceed the remaining $2/$25 caps, ask the
   owner rather than silently reducing sample size. Jev estimate at 15
   questions × 2k pages tokens × 5 pages × $0.042/M ≈ $0.0063, **estimate
   only**; researcher/critic model spend is likely dominant and unmeasured.
5. Measure critic-judged correctness, citation validity, fetched pages,
   total model tokens, attributed model+Jev spend per completed task,
   wall-clock time, and false drops (baseline-cited pages Jev dropped).
   Promotion threshold: correctness and citation validity each at least
   baseline; **zero** false drops on baseline-cited pages; all privacy,
   injection, fallback, and live-toggle tests pass; and either lower
   measured total cost/task or lower wall-clock time. Evaluate relevance,
   passages, links, and search triage separately so only passing decisions
   may be promoted. Any failure leaves the toggle off.

## Rollback and handoff

Pre-change verified backup, then deploy with `JEV_RESEARCH_ENABLED=false`.
The one-step rollback is setting it false and reloading the host plugin;
prove a live fetch returns the baseline result unchanged. Remove the plugin
only after that proof if desired. Document the flag, host-only decision log,
and LiteLLM spend query in `RUNBOOK.md` when deployed. Evidence goes under
`evidence/phase-4a/<UTC-run-id>/`; measured results must be labeled separately
from estimated costs. Phase 7A remains interactive browser decision work.
