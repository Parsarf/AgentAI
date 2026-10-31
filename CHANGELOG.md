# Changelog

## 2026-10-31 — GitHub catch-up

This update publishes the work accumulated since the previous working-branch
push, `3b2fdbb` (13 October 2026), plus the remaining reviewed local source and
brand assets. At the start of synchronization, 71 commits were unpublished.
The existing pull request to `main` also includes the earlier 40 commits that
were already on `product-phases-6-11` when GitHub access stopped.

### Customer app and presentation

- Add OpenMoji emoji rendering, typed data cards, and richer tables, charts,
  comparisons, forms, diagrams and mathematical content in assistant replies.
- Add the character/film chat stage, captions, pause-animation controls and
  reduced-motion behavior; retain the dark and parchment appearance choices.
- Rebuild the composer Tools menu with working actions. Improve chat history,
  drafts, activity labels and live task presentation.
- Add Lumina's branded thinking orb, continuous activity transitions and preview
  fixtures, while preserving tool-specific states and motion preferences.
- Add the customer-browser switch in chat and pairing/device controls in Settings.

### Native execution, task controls and cells

- Keep native OpenClaw responsible for execution, steering and session goals;
  supervise delivery, progress, recovery, cancellation, usage and final output.
- Add direct-work and plan checkpoints to Active Task; add queue position,
  pause/resume for waiting work and retry controls.
- Reconcile unexpectedly stopped cells and preserve cancellation through recovery.
- Add automatic host enrollment of approval-created cells under a fixed,
  host-owned image/profile/storage/capacity policy. Existing bindings cannot be
  overwritten. Queue cell creation atomically with approval, and wake an existing
  cell when that account has a waiting prompt.
- Add the push-release helper and a 45-minute idle default in source. The latest
  cell-only production rollout deliberately preserved the host's previous
  15-minute idle setting; source history and deployed configuration differ here.

### Browser execution and customer Chrome

- Rework JEV decisions around `jev-1.14.0` screenshots and control choices; add
  deterministic escalation to the assistant for complex/stuck pages.
- Improve hit/state checks, scrolling, fingerprints, popup/tab handling, takeover
  responsiveness, sign-in/verification handover and live frame delivery.
- Add browser-call diagnostics, redacted execution traces, timing and decider
  statistics, one retry for replies missing JSON, retention and capture guards.
- Bind browser tool calls to admitted native runs using one-use nonce proofs;
  install the runtime proof hook and verify parallel calls in the E2E harness.
- Preserve the owner-only ultrafast decider experiment behind its timed switch;
  wire that decider onto the standard browser rather than another Chrome engine.
- Add a Manifest V3 Chrome extension with pairing, customer enable/disable,
  DevTools execution, tab ownership, bounded message validation and reconnects.
  Add the account-scoped device store, authenticated WebSocket gateway,
  transport, REST routes, OpenAPI contract, Caddy route and extension packaging.
- Include extension icons, synthetic store screenshots, development adapters and
  regression tests. Chrome Web Store publication is a separate step; this update
  does not claim that a store listing or every extension acceptance gate passed.

### Generated UI and artifacts

- Add schema-validated generated documents, a discoverable component registry,
  durable artifacts, versions/events, action dispatch and a component gallery.
- Connect generated UI to chat, storage and assistant instructions. Run launched
  plan phases through normal admission and request handling.
- Add histogram/gauge components, product images and server-side action auditing;
  preserve historical stored-card rendering.

### Security, operations, integrations and CI

- Propagate rotated Brave credentials to existing assistants and redact them
  from Activity; reduce unnecessary service-classification calls.
- Add vault/saved-choice and browser question flows, safety controls and privacy
  handling recorded in the implementation history and architecture reports.
- Raise the product plan's rolling daily allowance from $5 to $15 in its contract
  and configuration; this records the existing product change, not a new charge.
- Accept signed provider webhooks above the generic ingress cap while retaining
  endpoint verification and dedicated request bounds.
- Expand CI to platform blocking/report-only modules, Django/migration checks,
  frontend tests/build, browser checks and tool-origin plugin checks.
- Preserve audits and deployment evidence summaries, replace superseded
  architecture reports/diagrams and remove obsolete continuation prompts.
- Ignore private keys, root archives, local tooling, experiments, raw host logs,
  editor history and render diagnostics. Preserve private local data in place.

### Prototypes, brand assets and documentation

- Preserve `jev-browser`: a separate screenshot-driven local browser prototype,
  Chrome runner, local dashboard and synthetic-shop tests.
- Preserve `jev-window-core`: a separate macOS selected-window controller with a
  Swift helper, Python model/loop, editable prompts and regression tests.
- Add reusable Lumina animation compositions, finished GIF/MP4 exports, icon
  iterations and a proposed short-form advertising brief. These are creative
  assets/prototypes, not claims of launched advertising campaigns.
- Add the refreshed CBM structural map and the 31 October automatic-cell
  deployment record. Refresh the repository landing page and this change log.

### Validation and deployment boundaries

- UI unit suite and production build: passed during this GitHub catch-up.
- Device/browser backend plus automatic-cell focused checks: 52 passed locally.
- Django device-account checks: 36 passed. Chrome-extension checks: 43 passed
  with Node's `--test-force-exit` to close lingering test-process handles.
- macOS window-core prototype: 11 passed.
- JEV browser prototype: the initial 42-test run had one new-tab timing failure;
  that test passed on an isolated rerun. The initial failure remains recorded; the isolated pass is not a clean
  full-suite result.
- Automatic-cell release `fae3c93` was deployed on 31 October after 151 staged
  Linux tests and application canaries; live health, authenticated supervisor
  socket, runtime settings and firewall-rule checks passed. Full two-live-cell
  adversarial isolation and real new-user provisioning were not exercised.
- The later source/asset catch-up commits are repository updates; they were not
  deployed to the VPS as part of this synchronization. The full repository's CI
  result must be read from GitHub, not inferred from focused local checks.
- Credential-pattern matches in unpublished history were inspected and were
  synthetic test fixtures. No live credential was identified among those matches.
  Real `.env` files, private logs/backups and editor caches remain excluded.

### Chronological commit list since the last working-branch push

The entries below include the 71 previously unpublished commits and the two
source/asset commits made while preparing this update. The documentation commit
containing this report follows them.

- `9ff48d7` (2026-10-14) Emoji in chat show as OpenMoji pictures; JSON cards now accept what the server accepts
- `7dcc3fe` (2026-10-14) JEV chooses the service for each web-related message; the service's output goes to the assistant
- `d67d15e` (2026-10-14) JEV service question: define the browser by listings, near-me searches, menus, prices and ordering
- `1ba204a` (2026-10-14) Dashboard update script also lets the dashboard save switches (it was sandboxed read-only for that folder)
- `99897fb` (2026-10-14) Release notes for live1-live4 (what changed, hand-made server changes, rollback, backups)
- `e4cf975` (2026-10-14) Release notes: correct backup location
- `acfd9f8` (2026-10-14) Thinking label hangs lower-left of the orb on a small curved branch
- `c583407` (2026-10-14) Browser: hand a human-verification wall to the user (after a short wait) instead of guessing; say why a model reply was unusable
- `84d7ec6` (2026-10-14) Browser: clearer verification-wall message
- `90c5277` (2026-10-14) Live view: instant takeover clicks, faster stable picture, human-check walls hand over to the assistant
- `330ba18` (2026-10-14) Live view speed and verification-wall handover: runner, browse service, chat driver, tests
- `f8658ee` (2026-10-14) Runner test: a takeover click returns at once and the next input is not queued behind a slow load
- `c0c7844` (2026-10-14) Remove an accidentally committed node_modules link
- `b2115cb` (2026-10-14) Release notes: live5 and live6 (faster Live view, verification-wall handover)
- `d59e59d` (2026-10-15) Browse safety floor: sign-in pages go to the user before any model; the gate honours the sensitive flag
- `25b776e` (2026-10-15) Browse runner: element state, ready checks before acting, scroll up/down, wait, page fingerprint
- `9dc1f9b` (2026-10-15) Browse ladder: one JEV call decides the whole step (operation, element, option, text)
- `8d8fafe` (2026-10-15) Browse loop: hand-off ladder to Claude (misses, too complex, loops, unchanged pages)
- `f435324` (2026-10-15) Browse service: count who decided each step and keep the totals with the run
- `d07ef1e` (2026-10-15) Release notes: live7 (JEV-first browser agent, live mode), hand-made server changes and rollback
- `02877e4` (2026-10-15) Browse: say why JEV missed and why a model reply failed; ask once more when a reply has no JSON
- `1c42366` (2026-10-15) Release notes: live8 (diagnostics and one retry for replies without JSON)
- `2725903` (2026-10-17) Task control center (Lumina phase 4): queue position, pause/resume of waiting tasks, retry
- `ace5e0d` (2026-10-17) Live view and browser fixes: lost jobs, hand-off windows, closing popups, retention, capture guard
- `65b15c7` (2026-10-17) Service choice: send far fewer ordinary messages to TypeSafe, and say honestly when the browser is unavailable
- `fb7af35` (2026-10-17) Search: a rotated Brave key reaches existing assistants; Brave keys are redacted from the Activity feed
- `285590b` (2026-10-19) Browser runs leave a trace: every JEV call, tier choice, runner command, safety stop and crash, with timings and no page or request text
- `825ecee` (2026-10-19) Browser JEV rework: picture mode (JEV 1.14), no confidence cut-off, Claude takes a page by rules, scroll feedback and hint, live-view status pill
- `f6ce2e3` (2026-10-19) JEV: give a controls-step request 8 seconds (a first call can take about 3)
- `46554f1` (2026-10-23) Chat background: the Lumina film, synced to the assistant's real state
- `033127f` (2026-10-23) Chat stage: the Lumina film gets its own place, captions and a calmer frontend
- `5b9f28e` (2026-10-23) Chat stage: a labelled Pause animation control, polite sleep/wake announcements, a slightly wider stage
- `5596eda` (2026-10-23) Parchment: the whole app moves onto the mascot's own paper, matching the owner's reference
- `4bdf03c` (2026-10-23) Chat film: Caddy serves it from /var/www/lumina-scenes; the frontend deploy refreshes that folder
- `5db9636` (2026-10-25) Dark look is the default again; parchment stays one click away (top bar switch and Settings)
- `b1439f8` (2026-10-27) Generative UI: validated block documents, registry, renderer, action dispatcher, server validation, gallery
- `a6371bc` (2026-10-27) Wire generative UI documents into chat, storage, assistant rules and the JEV display call
- `d95b796` (2026-10-27) Remaining pending work in openclaw-project
- `a7bdfae` (2026-10-27) Generative UI: histogram and gauge, server-side audit of plan actions
- `07fd6b9` (2026-10-27) Replace generative UI with discoverable registry and durable artifacts
- `10efb73` (2026-10-27) Track direct work and checkpoint plans in Active Task
- `a2bb53b` (2026-10-27) Record verified production deployment of generative UI and task progress
- `e700e33` (2026-10-27) Reconcile stopped assistant containers and preserve cancellation
- `2612e41` (2026-10-27) Record browser OOM recovery and verified cancellation hotfix deployment
- `42cb3fd` (2026-10-27) Raise the plan's rolling daily limit from $5 to $15
- `ef2a8ac` (2026-10-27) Harden browser reliability and interactive generative UI
- `03662de` (2026-10-28) Rebuild the chatbar Tools menu as an iOS-style popover with real actions
- `a973add` (2026-10-29) Ignore keys, archives and local tooling output (M-03, GH-002, OP-002, ST-004)
- `cc136cf` (2026-10-29) Keep production experiments private and preserved (GX-024, GX-025, GX-026)
- `82bbdf4` (2026-10-29) Tool ownership: one-use runtime proof hook, installer and proof check (AG-006, GH-005)
- `af10c90` (2026-10-29) Tool relay binds browser calls to admitted runs through nonce proofs (AG-006)
- `6df24da` (2026-10-29) E2E harness installs the ownership hook and checks parallel tool calls (AG-006)
- `6404d90` (2026-10-29) Document how browser tool calls prove task ownership (GH-005)
- `aed66b9` (2026-10-29) Preserve codebase audit and record verified cleanup progress (AG-006, M-03)
- `671f121` (2026-10-29) Run all platform modules and frontend/browser checks in CI (M-10, ST-001, AG-017)
- `f52ba23` (2026-10-29) Record CI validation and local disk-space blocker (M-10, AG-006)
- `98d091a` (2026-10-29) Accept provider webhooks above the default ingress cap (BE-004, ST-018)
- `0c48ade` (2026-10-29) Record webhook fix, green CI baseline and owner decisions (BE-004, M-10, M-02)
- `3bbc3e9` (2026-10-29) Record verified webhook deployment and app experience changes (BE-004, ST-018)
- `8c10824` (2026-10-29) Remove superseded browser and continuation prompts (GH-008)
- `d9e4e9d` (2026-10-29) Rebuild current architecture reports and diagrams; retire superseded audits (AG-016, GH-017)
- `e42bf35` (2026-10-29) Record approved cleanup, restored evidence and current report validation (AG-016, GH-017)
- `2aa3396` (2026-10-30) Add owner-only experimental jev-ultrafast browser engine behind a timed safety toggle
- `2b37c2e` (2026-10-30) Add ultrafast installer, vendored pinned engine, scratch-folder picture copy
- `5625659` (2026-10-30) Document the experimental ultrafast browser and its rollback
- `234975b` (2026-10-30) Run the ultrafast decider on the standard browser instead of a separate Chrome
- `176a8b2` (2026-10-30) Correct the standard_browser switch wording for the shared-browser design
- `fd625e8` (2026-10-30) Record which decider ran in each browse trace
- `e20a9e6` (2026-10-30) Idle sleep for assistant cells: 15 -> 45 minutes; add push-release helper
- `823465a` (2026-10-30) Add a status note: what is deployed, open findings, next step
- `fae3c93` (2026-10-31) feat: enroll approved customer cells automatically under host policy
- `0c7c9d9` (2026-10-31) feat: add paired Chrome browsing and Lumina activity orb
- `517e585` (2026-10-31) feat: preserve JEV prototypes and Lumina brand media sources
