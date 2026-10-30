# Current findings and verification limits

Rebuilt 29 October 2026 from the checked-in source at `8c10824` and the
verified deployment record. This is a code/documentation inspection, not a new
runtime acceptance test or server inspection. Last verified platform release:
`20261030T022448Z-webhook-0c48ade`, source `0c48ade`; supervisor remained on
`20261028T212308Z-tool-origin-v2`. See the [deployment evidence](../../../docs/codebase-audit/DEPLOYMENT_2026-10-29.md).

This replaces the pre-native execution findings report. Finding IDs below
refer to the [technical-debt register](../../../docs/codebase-audit/TECHNICAL_DEBT.md);
[implementation progress](../../../docs/codebase-audit/IMPLEMENTATION_PROGRESS.md)
is the owner for completed changes and decisions. Historical pages retained
at the owner's direction may still link here; their old prose is not silently
made current by that link.

## Open behavior and product gaps

| Finding | Rechecked evidence | Meaning now |
|---|---|---|
| M-01 / BE-006 | `RequestQueue.cancel()` changes waiting state without settling its task/reservation. `ChatService.send()` submits before a separate `BudgetLedger.admit()`. | Waiting cancellation and the claim/admission race remain unfixed. The admission-hold schema decision is pending; no `admitting` column has been added. |
| AG-005 | `ChatDriver.check_parked()` returns `ended` after its park limit; `_parked_tick()` calls `_run()` and supervision can observe the same human wait again. | Do not claim a verified hard stop at the park timeout. |
| AG-007 | `_over_budget()` returns false when usage is missing or snapshot reads fail. | The repeated-unreadable-usage stop policy is not implemented. |
| M-02 | `JevChooser.choose()` / `choose_picture()` construct image assets; `service_main.jev_for()` supplies no image privacy gate. | Source-supported screenshot egress risk. Owner explicitly left screenshot behavior unchanged; cleanup does not alter it. Actual wire payloads were not captured. |
| FE-002 | Browse service has `_ask_gate()`/`answer()`; shipping frontend has no fork question/vault answer components. | Complete the UI or define unreachable/retired behavior before removing the retained fork. Runtime question reachability is not a finished customer experience. |
| BE-002 / M-04 | SSE route exists with one sync Gunicorn worker. Caddy overwrites client identity with its peer address. | Streaming can occupy the web worker; per-client proxy identity needs a separate verified design. Neither was fixed by the webhook release. |
| BE-007 | Telegram factory builds an unpriced ChatService without the primary chat gateway wiring. | A working ingress size check does not finish Telegram execution/result delivery. |
| BG-008 | Restore table policy includes memory/saved choices as backup-winning rows. | Forgotten data can be resurrected; keep restore/schema work separate from file cleanup. |
| M-05 / M-06 | Disabled routes, test/schema-backed parked modules, retained frontend fork and prototypes remain. | “No caller” is not retirement approval. Keep the product decisions visible; Batch D was explicitly left alone. |

## Corrections to old reports

- **Goal cap configuration:** the current `build_worker()` passes
  `goal_chain_limit=settings.GOAL_CHAIN_LIMIT` into `ChatDriver`. The older
  blanket claim that the environment setting has no effect is not supported
  by this source. `GoalChain.limit` itself is still not read in that class;
  distinguish an unused field from a disconnected effective driver setting.
- The host browser runner is the recorded production engine. The native
  browser is an implemented, rollout-gated alternative, not a completed cutover.
- Tool ownership uses the runtime hook and a one-use proof, not transcript
  timing as authority. `tools.active` still reads runtime state for a separate
  active-turn inventory; that is not proof authorization.
- Parking releases the request slot, not the cell/reservation, and does not
  guarantee cross-account fairness. Request/task/delivery/browser states are
  distinct; see [state and recovery](state-and-recovery.md).
- Old “unused task states” claims predate actual park/task-state writers.
  Read current queue/driver/event code before treating enum values as dead.

## Completed versus still pending

| Item | Evidence/status |
|---|---|
| Tool-origin source custody (AG-006) | Four owner-reviewed commits preserve the already-deployed protocol-2 source. It is not new functionality from this cleanup. |
| Webhook size boundary (BE-004, ST-018) | `98d091a`, deployed as `20261030T022448Z-webhook-0c48ade`; live public boundary checks passed. Signature/secret verification remains required. |
| CI expansion (M-10) | `671f121`: 25 required platform modules, 48 report-only, frontend/plugin/browser checks. Local coverage passed; first GitHub/Linux run still awaits a push. |
| Runtime end-to-end verification | Earlier heavy run hit local disk exhaustion. All 73 CI-selected platform modules subsequently passed locally (980 tests, 2 skipped); that does not clear the heavy runtime suite. |
| SSH/off-server recovery/retention | Last server audit identified password login and local-only backup configuration. No new host audit or change was performed for this document rebuild. An encrypted restore drill/off-server copy remains unverified. |
| Cleanup decision | A: delete three prompts. B: replace main reports/diagrams, remove superseded reports. C: restore four evidence files. D: no changes. No feature activation or production deployment is implied. |

## Verification boundaries

This rebuild re-read routes, factories, queue/ledger/driver control flow,
proof authorization, browser selection/payload construction, schema sources,
edge/release configuration and client entry/polling code. Diagrams are rendered
from the checked-in Mermaid and source links are checked. It does not claim
that all source paths were audited or that tests were rerun for documentation.

Still unverified here: live running-cell isolation, actual TypeSafe outbound
payloads, a complete browser-question user flow, real Telegram completion,
remote GitHub CI, encrypted backup restore and post-audit host hardening state.
No customer messages, URLs, screenshots, secrets or raw sensitive logs were
used as examples in the rebuilt reports.

## Evidence

- [RequestQueue](../../platform/agentai_platform/request_queue.py), [ChatService](../../platform/agentai_platform/chat.py), [BudgetLedger](../../platform/agentai_platform/budget.py).
- [ChatDriver](../../platform/agentai_platform/chat_driver.py), [RequestWorker](../../platform/agentai_platform/request_worker.py), [worker factory](../../platform/accounts/management/commands/request_worker.py).
- [Browser chooser](../../platform/agentai_platform/browse/ladder.py), [factory](../../platform/agentai_platform/browse/service_main.py), [service](../../platform/agentai_platform/browse/service.py).
- [Telegram factory](../../platform/accounts/telegram.py), [stream route](../../platform/accounts/streams.py), [Gunicorn](../../platform/deploy/gunicorn.conf.py), [Caddy](../../platform/deploy/caddy/Caddyfile.getlumina).
- [Restore policy](../../platform/agentai_platform/ops/restore.py), [frontend routes](../../lumina/src/App.tsx).
- [Historical server verification](../../../docs/codebase-audit/PRODUCTION_VERIFICATION_2026-10-29.md), [current release verification](../../../docs/codebase-audit/DEPLOYMENT_2026-10-29.md).
