# Verification

From `openclaw-project/lumina`:

```sh
GEN_WRITE=1 npx vitest run src/gen/export.test.ts
npm test
npm run build
python3 tests/preview_chat.py
../platform/.venv/bin/python tests/preview_genui.py
```

The registry export test guards generated server schemas, examples, catalog and shared parity fixtures. Every registered capability has a fixture and renderer. `extended.test.tsx` checks numeric operations, what-if updates, event submission, restored input, autosave, checklist, editable cells, Kanban, rule editing and sandboxed previews. Existing suites cover table filters, tab keyboard behavior, native approval confirmation, parser bounds, stream ordering, sanitization and historical adapters.

From `openclaw-project/platform`, use the project virtual environment:

```sh
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python manage.py test accounts
```

Django tests require a private temporary `AGENTAI_STATE_DIR` and generated `AGENTAI_SESSION_SECRET`, as in the existing account test harness. The system Python may lack Django/cryptography; use `.venv`. Package-root discovery (`-t .`) is required for relative imports.

`test_gen_artifacts.py` covers create -> submit -> admitted request -> update the same artifact, user-state recovery, duplicates, stale versions, malformed documents, authorization, native approval gating and usage provenance. `accounts/test_genui.py` covers authenticated endpoints, CSRF, schema discovery, compare-and-swap, cross-account isolation and corrective errors. Shared parity fixtures validate every capability in both languages, including invalid dates, graphs, charts and forms.

The registry-generated gallery is `/app/gen-gallery`; fixtures are explicitly labeled and sandbox actions have no production effects. Its selector exposes each component plus normal/loading/empty/error/disabled states. At 1440px and 390px, inspect working/completed/long/multiple chat fixtures, with both motion settings. Require `document.documentElement.dataset.layoutCheck === 'passed'` and no `layoutFailures`; inspect real chart/table/code overflow and dialog focus.

The interactive fixture on port 5179 uses the production bundle and the real artifact store, request queue and driver with a disposable synthetic account/model. It supports table filtering, scenario recalculation, form submission, in-place updates and refresh recovery. A synthetic gateway proves the application loop deterministically. A live-model run requires a provisioned account, admitted model route and running cell bridge. Partial-token delivery additionally requires the upstream gateway to expose drafts/deltas; Lumina never simulates streaming or execution progress. External providers must be tested against real credentials before claiming live capabilities.


Launch regression tools (start both `preview_chat.py` and `preview_genui.py` after building):

```sh
node tests/launch-genui.mjs chromium
node tests/launch-genui.mjs firefox
node tests/launch-genui.mjs webkit
```

`PLAYWRIGHT_MODULE` can point to an installed Playwright `index.mjs` when the browse runner's older dependency cannot control the installed browser. Install test browsers outside the repository with `PLAYWRIGHT_BROWSERS_PATH`. `tests/audit-genui.mjs` additionally takes `AXE_MODULE` pointing to `@axe-core/playwright/dist/index.mjs`; it checks representative families at two viewports, modal Escape/focus, tab keyboard behavior and the maximum composition/dataset. Results and illustrative screenshots are written to `/tmp/lumina-ui-launch-evidence` by default. Do not rebuild `dist` while a fixture browser is loading its assets.

The bounded real-model operator command is `manage.py verify_interactive_ui --run-live` with the normal production app environment. It uses only the configured owner account and existing admission/caps, sends two model turns, checks same-artifact continuation, retained answers, the expected computed value, and a duplicate event replay. Preserve its result and owner conversation as evidence. Do not increase limits or enable switches to make it pass. See [launch-readiness.md](launch-readiness.md) for current blockers and exact supported scope.
