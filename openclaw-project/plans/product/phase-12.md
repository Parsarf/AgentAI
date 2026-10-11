# Phase 12 — optional Jev/browser and research adapter completion

Status: **OPTIONAL BUILD COMPLETE offline; both adapters remain DISABLED; acceptance pending Phase 16.**
No optimization is required for baseline launch. Nothing was deployed or changed on the server, no
TypeSafe request was made, no key was read, no paid call. Date 2026-10-09.

## Urgent finding (needs your decision)

A read-only readback of the owner Gateway shows `jev-research/config.json` = `{"enabled": true}` and the
disposable `phase4a-jev-eval.key` present in `/run/secrets`. BUILD_LOG (2026-09-28) says the toggle was left
off, and this phase requires adapters to stay disabled server-side. It is not currently spending: the
public-task registry is `{}`, so no fetch is eligible and every one falls back to the baseline. To restore the
documented state use the new **Feature switches** page (see `FEATURE_SWITCHES.md`; it flags this exact mismatch with a
one-click "Turn it off everywhere"), or set that file to `{"enabled": false}`. I did not change it; the page is built but not
yet installed on the server.

## Item 1 — audit and the "middleware did not load" defect

- Manifest and entry were checked against the installed OpenClaw 2026.9.6 loader source: runtime ids are
  `["openclaw","codex"]`, the manifest declares `openclaw`, a plain default export with `register(api)` is
  accepted, and registration only requires the plugin to be explicitly enabled. Middleware owners load
  **lazily** on first tool call, so absence from the startup plugin list is expected and was not evidence.
- Server: plugin `status: loaded`, explicitly enabled, activated. It was copied into `extensions/` rather than
  installed (`trust: record-missing`); the supported path is `openclaw plugins install npm-pack:... --accept-capabilities`.
- A diagnostic that drives the real installed loader and middleware runner (`research-opt/diagnostics/registration_diagnostic.mjs`)
  showed the middleware **is registered**, but when invoked with an unusable state directory it threw, and the
  runner then replaces the tool output with "Tool output unavailable due to post-processing error" — i.e. not
  fail-open. Causes: logging could throw outside the try block, and the state path was hard-coded.
  Fixed: best-effort logging, outermost fail-open wrapper, `JEV_RESEARCH_STATE_DIR`, registration marker.
  Before/after evidence: `diagnostic-before-fix.json` (`not_registered`, passthrough false) vs
  `diagnostic-after-fix.json` (`registered`, passthrough true).
- **Live status unchanged:** the fixed plugin is not deployed; the server still runs the old file (hash equals
  the previous repo HEAD). Why the Sept 28 probes logged nothing remains unexplained on the server; the
  local defect was real but would not trigger there because its state directory exists. Do not call the
  live issue fixed until the plugin is reinstalled and the diagnostic is run on the server.
- Browser transport and research interception are separate integrations and were treated separately.

## Item 2 — TypeSafe recheck (`phase-12-typesafe-pin.json`)

Model `jev-1.13.0` (aliases `jev-latest`/`jev-preview` not used), $0.042 per million input tokens, output free,
64k request / 32k state+question, text-only, endpoint `POST /v1/systemone`, rate limits 100K tokens/s and
80 requests/s: all unchanged from the Sept 27 pin. **A real defect was found:** the Phase 9 browser adapter sent
`questions` as an array with `options` and parsed a `value`/`sufficient` answer; the documented schema is an
object keyed by id with `instructions`/`criteria`, and Noul carries no confidence. Corrected and tested. Legal
terms (DPA, privacy, zero-retention) were not reviewed; a recorded data-handling approval is required first.

## Items 3-4 — browser adapter and route

`jev_adapter.py`: request per documented schema; strict `type: choice`; candidates carry a fingerprint and
sensitivity; snapshot id; `verify_fresh` re-checks the chosen target on a fresh snapshot (renamed, renumbered
or removed targets execute nothing); consequential controls (submit/pay/delete/password...) return
`needs_approval` for the baseline owner path regardless of confidence. New `route.py` adds deadline, action cap,
loop detection, cancellation (before the decision and before executing), per-call budget admission, idempotency
keys and receipts, reconciliation of uncertain effects (applied => counted, never re-sent; none => baseline may
continue; unknown => halt for an operator, no fallback) and fallback only when no effect is outstanding.
Platform side: `optimization.py` (SQL 0012) layers kill switch (read each call, unreadable => off), per-account
activation, data-handling approval, transport review and account reference; every call is reserved against the
Phase 5 task allocation (including open holds) before sending and written as a `typesafe` provider receipt
afterwards; an uncertain call keeps its hold. TypeSafe is billed separately and never inferred from Anthropic
caps. The per-call upper bound assumes one token per UTF-8 byte, capped at 64,000 tokens: **unproven**, to be
validated against observed usage in Phase 16.

## Item 5 — research track

Lossless bypass is observable (every fallback logs a reason and returns the original result). The existing
Python adapter and Node plugin already match the documented schema and are pinned by tests. Content exported is
limited to public pages with provenance (<= 16,000 chars); see `phase-12-transport-boundary.md`. A separate
frozen rubric (`RUBRIC.md`) and paired fixtures with a hash lock were authored; browser reliability results are
explicitly not accepted as research evidence.
**Open design gap (unchanged):** the middleware cannot learn the research question or trusted URL provenance
from the runtime; it relies on a `public-tasks.json` registry written by a trusted caller that does not exist yet.

## Item 6 — fixtures and proofs

Browser: 10 development + 10 held-out scenarios (existing) plus `adversarial.yaml` (10 cases each mapped to a
unit test). Research: 6 development, 6 held-out (hash-locked), 6 adversarial cases. Plugin registration proof
and kill-switch readback proof: the diagnostic above, plus a Node test that flips `config.json` on disk and
observes the behaviour change on the next call.

## Checks actually run

Platform suite 214 OK (2 skipped); Django 66 OK; browser-opt 31 OK; research-opt Python 10 OK; plugin Node 8 OK.
CI extended to run all of them. Read-only server readback only.

## Not claimed

No paired comparison, calibration, savings or accuracy claim. No TypeSafe account, key, data-handling approval or
live transport exists for customers. Thresholds (0.5 floor, 0.7 act, 0.10 drop) are provisional settings.

## Rollback and deployment of the plugin fix (prepared, not applied)

1. Back up the Gateway state; keep `jev-research/config.json` at `{"enabled": false}`.
2. `npm pack` the plugin, `openclaw plugins install npm-pack:<tgz> --force --accept-capabilities`, restart the
   Gateway, run the diagnostic against the server's OpenClaw root.
3. Rollback: reinstall the previous tgz (hash `aa7066bb...` is the previously deployed file), or
   `openclaw plugins` disable `jev-research`; deleting `browser-opt/` removes the browser track. Migration
   0012 is additive.

Evidence: `evidence/product/phase-12/20261009T200000Z/manifest.json`.
