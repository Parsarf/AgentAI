# Phase 9 — browser optimization build plan (2026-09-27)

Owner selected the optional optimization. **The optimized route stays
disabled; the existing browser-worker route is preserved untouched.** No
provider call, no calibration, no benchmark in this build (Phase 11 scope,
needs separate owner authorization).

## Primary sources checked (2026-09-27)

- docs.typesafe.ai/models: model `jev-1.13.0` (alias `jev-latest`), endpoint
  `POST /v1/systemone`, **$42 per Btok = $0.042 per Mtok input, output
  free** (re-checked; matches research), 250k tok/s + 1200 req/min dynamic
  rate limits, 64k request / 32k state+longest-question context, text-only
  input, English-first, not trained on customer data, ZDR enterprise-only.
- docs.typesafe.ai/confidence: `confidence` (0–1, derived from
  `probabilities`) is returned on **Choice and Score answers only**; Noul
  carries no confidence. Three-range routing (act / caution / do-not-act)
  with risk-scaled thresholds; start conservative; thresholds are
  provisional settings, not measured claims.
- docs.typesafe.ai/model-jaggedness/jev-1.13 and /patterns/confidence-routing:
  not fetched this run (token budget) — flagged for Phase 11 calibration
  prep. OpenClaw browser/security docs: the authoritative in-repo record is
  the Phase 4 pinned browser sidecar config; no change made.
- The "71× input-price ratio" and "99% savings" figures remain unverified
  marketing hypotheses and are not used anywhere here.

## Transport gap (honest)

Workers are sandboxed without network; `main` is denied web tools. A
gateway/host transport for the adapter's single HTTPS call (host service on
the dashboard pattern, bridge-IP allowlist, or a native plugin) is **not
installed** — it needs its own isolation review. Implemented instead: the
complete adapter as a library with a pluggable transport function, offline-
testable, plus the service/hosting gap recorded in
`plans/remaining-build-items.md` (#9). No endpoint, schema, or config key is
invented beyond the two verified TypeSafe doc pages above.

## Data flow (design, disabled)

planner (existing) → bounded subgoal + allowed destinations + completion
assertions → adapter builds typed action candidates from a FRESH snapshot
(`[ref] <tag> "label"` format, deterministic code, cap 20) → Jev
(`jev-1.13.0`) receives only subgoal + sanitized state + candidate ids, and
answers one Choice (candidates ∪ escalate/stop/no_valid_action) + one Noul
("state sufficient?") → full response validation (pinned model id, schema
keys, candidate membership, finite probabilities summing ≈1, argmax
consistency, finite confidence on the Choice) → any malformed/unknown field
executes nothing → code re-checks target identity/visibility/page version
before executing one action → verify observed state change (read-back, not
model claims) → escalate to the existing planner path on low confidence,
ambiguity, no progress, repeated actions, or unsupported content.

## Authority and safety

Jev holds **no** credentials, filesystem, messaging, scheduling, spawn or
policy authority; it cannot generate selectors, shell, JS or tool calls —
its entire power is picking among code-created candidates. Confidence never
grants permissions; owner approval for consequential actions is unchanged.
Page content is untrusted data (TypeSafe documents adversarial-state
susceptibility); no page text is ever copied into privileged instructions.
Exact arithmetic/counting/equality stays in code.

## Billing (pending owner)

No TypeSafe account exists. Account creation, data-handling decision and
spend controls are **separate owner choices** — nothing authorized here.
The adapter carries a **local estimate** budget (per-task action cap)
explicitly labelled as not a provider-enforced cap; losing budget tracking
stops the route. Anthropic proxy caps and ChatGPT quota do NOT cover
TypeSafe.

## Provisional thresholds (settings, not claims)

floor 0.5 (below → escalate), act 0.7, deadline 5 s, 1 bounded retry on
transient errors only, max 40 actions/task. Pinned `model: jev-1.13.0` (not
the alias); response `model` mismatch → reject.

## Kill switch / fallback

`config.json: "enabled": false` is the master switch; the runner additionally
refuses optimized runs without `--enable-optimized`. Fallback is the existing
browser-worker path (no duplicate effects: fallback fires only when the
optimized route produced no executed action). Rollback = delete
`browser-opt/` — the runtime never loaded it.

## Deliverables

adapter (`jev_adapter.py`), pinned `config.json`, offline unit tests
(malformed/unknown/forged/injection candidates, budget, outage, fallback),
`fixtures.yaml` (10 dev + 10 held-out synthetic scenarios), 
`compare_runner.py` (paired scaffold, refuses disabled route), evals cases
(`T11-*`), docs updates, evidence manifest.
