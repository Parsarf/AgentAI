# Interactive UI launch contract and acceptance

Updated 27 October 2026. This is the support contract for the registry-based interactive UI, not a claim that the whole Lumina service is ready for commercial launch.

## Supported launch behavior

Interactive answer style enables validated forms, buttons, charts, tables, local calculators, saved artifact edits and native task/plan controls. Basic stays plain text; Medium supports information and local exploration. Explicit Text mode overrides the answer style and intentionally does not request composed UI.

A form submission becomes a normal admitted request under the account's existing queue, entitlement and spending limits. Its continuation can replace the same versioned artifact. Inputs with compatible stable node ids survive replacement; incompatible fields reset. Local operations do not spend model money. A sent form means its request was accepted, not that its work finished.

## Saving and recovery

- Saves are serialized and drain newer edits before submission. Saving, saved and unsaved states are visible.
- Network failures retain answers in memory with retry and explicit JSON download. State and submission calls have bounded timeouts, including CSRF acquisition. A lost submission response retains the event id so a retry resolves the same admitted request.
- Disjoint edits from another tab merge against the last saved state. Overlapping edits require **Keep my edits** or **Use saved edits**. A second race still fails its compare-and-swap instead of overwriting silently.
- Agent document updates never accept an old document version's write. Earlier unsaved answers remain downloadable; the user can explicitly discard them.
- Route changes flush pending work and preserve the draft while this application is open. Hidden pages and restored connections trigger saving. Closing/reloading with unsaved work asks the browser to warn; browsers may suppress this warning. Download before closing when saving is unavailable.
- Session expiry hides and pauses drafts. Signing back into the same account restores them; explicit logout or signing into another account clears them. Nothing from these drafts is written to localStorage, sessionStorage or IndexedDB. Unsaved drafts cannot survive a browser crash or a forced reload.

## Forms, accessibility and errors

Client and server validate required values, numeric bounds/steps, real dates, ordered ranges, times, colors and options. Hidden conditional fields are not submitted; server-side conditions account for defaults. Invalid values do not queue work. Inline errors are associated with controls and the first invalid control receives focus. Submission locks the form while pending and announces its state.

Fixed messages distinguish session expiry, permission changes, unavailable tasks, conflicts, full queues, allowance denials, rate limits, network errors and service outages. Backend exception text and user inputs are never echoed as generic UI errors. Generated dialogs retain native focus behavior and the native closed state.

## Operations and release

`POST /v1/genui/artifacts/{id}/diagnostics` accepts only a version and fixed kind/category enums. It requires account membership, artifact ownership, CSRF and rate limits. No document, input, labels, exception text or URLs are accepted. Client reports are deduplicated for a minute; the server records them in the existing audit log. Support diagnostics include per-account hashed `ui_failures_24h` counts for only the known enum combinations. Model document rejection logs contain fixed categories, not content. Treat these as client-observed signals, not authoritative proof of a server fault.

No database migration is required for this hardening change. Deploy the backend and matching frontend together using the existing canary/backup release mechanism. Preserve the previous app and UI bundles. Do not restore the database for a binary-only rollback when the schema is unchanged. GitHub publishing is currently unavailable due to the repository owner's account suspension; a Git push is not proof that the VPS code was deployed.

## Acceptance gates

The source changes add regression coverage and repeatable browser/owner-model acceptance tools. Evidence for this change belongs in `../../evidence/interactive-launch/20261027/`.

1. Frontend tests, type checks, design-token checks and production build.
2. Backend artifact/document tests, authenticated API and contract checks, and full platform regression suite.
3. Browser flow at desktop/phone widths and both motion settings: invalid field focus, calculation, real artifact event/queue/driver continuation, refresh, save failure/retry and two-tab conflict.
4. Keyboard dialog/tab checks, automated accessibility checks across representative component families, and the maximum 24-block/500-row composition. Automated checks do not certify all accessibility requirements or physical devices.
5. A real-model owner run through normal admission. Run on the server, with the app's normal environment: `manage.py verify_interactive_ui --run-live`. This creates a clearly named owner acceptance conversation, preserves billing receipts and evidence, and changes no safety switches or allowances. Model execution costs apply. No customer is provisioned and no external site, booking, message or purchase is requested.
6. Publish the verified backend/UI pair, check source/bundle identity and health/readiness, then repeat the admitted owner workflow on the released version.

The live-model gate is currently blocked by the owner's normal allowance denial. An initial pilot mistakenly used Text mode, so its descriptive response is not evidence of an interactive loop. The corrected harness uses Auto + Interactive. Neither that pilot nor a deterministic model fixture passes the real-model gate.

WebKit automation on this macOS host currently crashes in native text-input handling (`textInputClientDidUpdateSelection`) with both tested WebKit builds. Safari/iOS acceptance remains unverified; do not interpret that harness crash as a verified application defect or advertise it as a passing browser test. Manual screen-reader and physical-device acceptance remain explicit checks.

## Features outside this launch contract

Coordinate maps and sourced result displays are supported; live basemaps, street imagery, geocoding, road routing and specialized live feeds require configured providers and separate acceptance. Their absence is labeled. Reservation selection does not book; recurrence editing does not publish a job; editable-table changes do not write to an external database. First-token streaming and complete token totals need upstream runtime support. Ultra remains unavailable. None is presented as a working external operation by the current UI.

Verified for this change: 360 frontend tests; 985 platform tests (2 skips); 14 affected authenticated API/contract checks; production build and type/design checks; Chrome and Firefox acceptance; 13-family accessibility scan with zero automated violations; maximum fixture 314 ms mount / 46 ms filter; production canary dry run with binary rollback compatibility. The live code has not been switched.

Browser forensic follow-up: the initial UI pilot's browser activity belonged to an older shopping session and cannot count as UI acceptance. The pending browser ownership/reliability fixes and their separate validation are documented in [browser-reliability.md](../browser-reliability.md). The earlier UI canary evidence describes its original package; it is not proof that these later bridge/worker changes are deployed.
