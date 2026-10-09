# Optimization transport boundary review (Phase 12) — design reviewed, NOT activated

Applies to both optional tracks (browser action selection, research fetch decisions). Nothing here is
connected; every layer below defaults closed.

## Who talks to TypeSafe

- **Only a host-side adapter inside the customer's own cell boundary** sends requests. Browser-worker and
  researcher agents never hold a TypeSafe credential, never choose an endpoint and never see a raw response.
- The credential is a **per-account TypeSafe key held in custody** (same account-bound custody contract as
  connectors). The owner's disposable `phase4a-jev-eval` key and its `/run/secrets` file are owner-runtime
  only and must never be mounted into a customer cell. (Found present in the owner Gateway on 2026-10-09.)
- Egress is limited to one pinned host (`api.typesafe.ai`, HTTPS 443) with the connectors SSRF guard; or the
  LiteLLM `/typesafe/v1/systemone` pass-through **only after** per-key budget enforcement for that provider is
  proven (unconfirmed; the pinned proxy predates the documented pass-through).

## What may be exported

- Browser: the current accessibility snapshot lines, a page-text excerpt (<= 24,000 chars) and the subgoal.
  Never: password field values, cookies, headers, authenticated/connector pages, or any page reached through
  a credentialed browser profile. Pages containing password inputs stay on the baseline route.
- Research: the fetched public page text (<= 16,000 chars) and the public research question, only for URLs that
  pass the public-URL gate and have a trusted provenance record. Login-adjacent URLs, private addresses and
  connector content are ineligible.
- Request/response bodies are never logged or retained by AgentAI; only decision metadata (question id,
  outcome, confidence, token counts, latency, cost, fallback reason).

## Gates in order (all must be open; any failure = baseline route, nothing sent)

1. Server kill switch, re-read on every call, unreadable => off (`browser-opt/config.json`,
   `jev-research/config.json`).
2. `OptimizationGate.check`: per-account activation, recorded data-handling approval, recorded transport
   review, TypeSafe account reference.
3. `OptimizationGate.reserve_call`: upper-bound reservation against the Phase 5 task allocation (including
   open holds), idempotent by call id; receipt written on completion; timeout after send => uncertain, hold kept.
4. Route-level caps: deadline, action cap, loop detection, cancellation, fresh-target re-check, sensitive
   controls to the baseline approval path.

## Not reviewed / needs the owner

- TypeSafe legal terms (DPA, privacy, zero-retention tier) were not reviewed; a recorded data-handling
  approval is required first. English-first, text-only model: other languages degrade.
- Whether a TypeSafe account for this product exists; no key is provisioned for any customer.
