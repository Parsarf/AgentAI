# Generative UI implementation report

Verified locally on 2026-10-27, branch `product-phases-6-11`.

## Delivered

The shared registry now contains 205 capability IDs, each with a validated schema, renderer, example, selection guidance and gallery entry. Aliases reuse registered implementations; complex families load lazily. The generated server registry and offline validator come from the same source as the browser schemas. The agent receives a compact index, reads the specific component schema/example when needed, validates its document, and emits `lumina-doc`.

Removed the active legacy card producer, remote image enrichment, old renderer and old agent card instructions. Historical stored cards remain readable through a small adapter into the replacement renderer, with readable JSON fallback when migration fails. Answer-style settings from the handoff are included and enforced per request.

Artifact events carry stable artifact/node/action IDs, document versions and validated submitted values. Account/conversation authorization, stored action binding, idempotency, stale-event checks and independent state revisions are enforced server-side. Form submission admits a normal agent request; its response can update the same artifact. Compatible local state survives updates and refresh. Native approval and retry components delegate to the existing backend mechanisms; displaying an approval grants no authority.

Execution views consume runtime task/activity/plan data. Cost views use provider receipts, distinguish estimates, and display missing token counts as unavailable. Asset access is scoped to the stored document, account and project; active previews and generated diagrams are sandboxed. Maps and domain adapters distinguish supplied presentation data from external integrations.

## Verification

- Frontend: 326 tests, including local calculations, editable tables, Kanban, rules, matrix reweighting, persistence and submission flushing. Registry export/parity checks pass.
- Production build, TypeScript and design-token checks pass. Mermaid's optional lazy ELK chunk produces the existing size warning; it is not in the initial application bundle.
- Platform: full suite passed 969 tests with 2 skips; subsequent affected-module run passed 68 tests.
- Django: full accounts run passed 225 tests; the expanded generative UI API/asset module subsequently passed all 3 tests.
- Dependency audit: no known vulnerabilities at verification time.
- Real browser: working/completed/long/multiple chat layouts passed at 1440px and 390px with animations enabled and reduced motion. Fixed mobile composer/navigation overlap. Inspected sandboxed, theme-aware Mermaid rendering and interactive matrix scores.
- Real browser application loop, using a disposable synthetic account/model with the production bundle and actual artifact store, request queue and driver: filter comparison to Beta; change local scenario quantity to 5 (result 50); submit form quantity 4; observe the same artifact update to $40; refresh and verify quantity, filter, scenario and result persist with exactly one document. Screenshots are in `../../evidence/generative-ui/`.
- Backend integration tests also cover authoritative activity data, native approval gating, unauthorized access, malformed updates, stale versions and duplicate submissions.

## External limits

A live-model test could not run: this workspace has no running cell bridge/provisioned model route. The deterministic browser fixture exercises the real application loop but uses a synthetic gateway. The upstream `chat.history` path exposes finalized messages rather than drafts/deltas; the incremental parser handles partial input safely, but first-token delivery requires gateway support and is not claimed here.

Street imagery, map tiles, geocoding, road routing, live domain data, bookings and schedule publishing require configured external providers/credentials. Their validated presentation/editor components exist and explicitly identify unavailable services. Selecting a reservation does not book it, and editing recurrence does not create a scheduled job. No sample data is presented as live. Token totals remain unavailable until the runtime supplies them. The pre-existing Ultra answer-style option remains planned/unavailable.

Changes were implemented and checked locally; no push or deployment was performed.

## Launch hardening follow-up

See [launch-readiness.md](launch-readiness.md) for saving/conflict recovery, structured form errors, operational diagnostics, repeatable acceptance tools and the current release gates. That document distinguishes local implementation from live-model acceptance and production deployment.
