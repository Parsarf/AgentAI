# State, events and persistence (diagrams 8 and 9)

Legend: see [04-current-orchestration.md](04-current-orchestration.md#legend-for-every-diagram-in-this-audit).

## 8. Task state and recovery

Several state machines run side by side. The first is what the customer sees. Details of each transition are in the catalog below.

```mermaid
stateDiagram-v2
  direction LR
  [*] --> waiting: send admitted (P01..P04, P09, P10, P11)
  waiting --> cancelled: Stop, or account revoked before claim
  waiting --> starting: claim, fence+1, lease 120 s
  starting --> running: first heartbeat
  running --> running: heartbeat, lease +60 s
  starting --> uncertain: lease expired
  running --> uncertain: lease expired or driver raised
  running --> completed: finish(receipt completed)
  running --> failed: finish(receipt failed)
  running --> cancelled: finish(receipt cancelled)
  uncertain --> completed: reconcile found a finished reply
  uncertain --> failed: nothing was sent, or abandon after 1800 s
  completed --> [*]
  failed --> [*]
  cancelled --> [*]
  failed --> waiting: Retry creates a NEW row (retry_of)
  cancelled --> waiting: Retry creates a NEW row (retry_of)
```

```mermaid
flowchart TD
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef bad fill:#2a1616,stroke:#ef6a6a,color:#f5d0d0
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0

  F0["Failure or interruption"]:::bad
  F1{"What failed?"}:::cur
  F2["Worker process dies or is restarted mid-run<br/>lease expires"]:::bad
  F3["Runtime unreachable or send outcome unknown<br/>delivery = uncertain"]:::bad
  F4["Browse service restarts<br/>job unknown"]:::bad
  F5["Browse service unreachable 60 s"]:::bad
  F6["Run exceeds 900 s"]:::bad
  F7["Customer cancels"]:::cur
  F8["Account revoked"]:::cur
  R1["next claim marks request uncertain<br/>request_queue.py:132"]:::cur
  R2["RequestWorker._tick: reconcile first"]:::cur
  R3{"cell transcript shows a finished reply?"}:::cur
  R4["close completed with that reply<br/>ChatDriver.reconcile"]:::cur
  R5{"older than 1800 s?"}:::cur
  R6["abandon: fail, charge reserved bound"]:::bad
  R7["leave uncertain, global slot stays held, retry next tick"]:::bad
  R8["end request at once: error, nothing left running"]:::bad
  R9["abort run, close failed"]:::bad
  R10["abort or cancel job, close cancelled"]:::cur

  F0 --> F1
  F1 --> F2 --> R1 --> R2
  F1 --> F3 --> R2
  R2 --> R3
  R3 -- yes --> R4
  R3 -- no --> R5
  R5 -- yes --> R6
  R5 -- no --> R7
  F1 --> F4 --> R8
  F1 --> F5 --> R8
  F1 --> F6 --> R9
  F1 --> F7 --> R10
  F1 --> F8 --> R10
```

**Stuck or contradictory states (confirmed in code).**
- While a request is `uncertain` and the runtime cannot be reached, it holds the one global request slot for up to 1800 s; every other customer waits (`request_queue.py:128-131`, `request_worker.py:_tick`).
- `tasks.state` stays `queued` for a request cancelled while still `waiting`; its reservation is not released by `RequestQueue.cancel` (see [08-inconsistencies.md](08-inconsistencies.md), I-06).
- `tasks.state` values `waiting_for_approval`, `paused`, `budget_exhausted`, `blocked` have no writer in application code, although the lifecycle worker and restore tooling read them.

## 9. Persistence, events, polling and frontend updates

```mermaid
flowchart LR
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef dis fill:#1b1c22,stroke:#8a8d99,color:#c9cbd3,stroke-dasharray:5 4
  classDef store fill:#14151a,stroke:#6b6f7e,color:#e6e6ec
  classDef ext fill:#1f1a33,stroke:#a78bfa,color:#e0d6fa

  subgraph WRITERS["WRITERS"]
    API["Django API<br/>send, blocks, control"]:::cur
    DRV["ChatDriver<br/>_emit, _absorb, _close"]:::cur
    LW["Lifecycle worker<br/>progress: waking"]:::cfg
    RUN["PlanRunner"]:::cur
    BRS["Browse service<br/>in-memory job + files"]:::cfg
  end
  subgraph STORE["PERSISTENCE"]
    REQ[("customer_requests<br/>request_slot")]:::store
    MSG[("chat_messages<br/>chat_deliveries<br/>conversations.native_session_ref")]:::store
    TSK[("tasks, task_reservations,<br/>ledger entries, provider_receipts")]:::store
    EVT[("events (per-task sequence)<br/>event_streams")]:::store
    BLK[("ui_blocks, plan_revisions,<br/>plan_phase_runs, data_blocks")]:::store
    BRW[("browse_runs, browse_steps,<br/>browse_sessions")]:::store
    PUR[("pursuit_state")]:::dis
    ART[("artifacts, project_files<br/>bytes in RootStore")]:::store
    AUD[("audit_events")]:::store
    CELLDB[("cell sessions and workspace<br/>(inside the cell)")]:::ext
    FILES[("job folder: live.jpg, screenshots,<br/>trace JSON lines")]:::cfg
  end
  subgraph READERS["READERS AND CHANNELS"]
    P1["GET messages, tasks, blocks<br/>polled every 2.5 s while working"]:::cur
    P2["GET /v1/tasks/ID/events<br/>polled every 2.5 s (AgentThinking)"]:::cur
    P3["GET /v1/tasks/ID/stream<br/>SSE, built, unused by the app"]:::dis
    P4["GET /v1/browse/ID, shot, live ticket"]:::cfg
    P5["Live frame: /v1/live/ID/frame<br/>Caddy to frame gateway (browse service thread)"]:::cfg
    UI["Lumina app<br/>orb, thread, cards, Live view, Activity panel"]:::cur
  end

  API --> REQ
  API --> TSK
  API --> MSG
  API --> BLK
  DRV --> MSG
  DRV --> EVT
  DRV --> TSK
  DRV --> ART
  DRV --> BRW
  DRV -.->|"cfg pursuit"| PUR
  DRV --> AUD
  DRV <-->|"send, history, abort via bridge"| CELLDB
  LW --> EVT
  RUN --> BLK
  RUN --> REQ
  BRS --> FILES
  BRS --> BRW
  REQ --> P1
  MSG --> P1
  BLK --> P1
  EVT --> P2
  EVT --> P3
  BRW --> P4
  FILES --> P5
  P1 --> UI
  P2 --> UI
  P3 -.-> UI
  P4 --> UI
  P5 --> UI
```

**Mechanics (verified).**
- **Events** are appended by trusted host code only (`EventService.append`), with per-kind allow-listed payload keys, recursive secret redaction, 32 KiB and 2000-event caps, 30-day retention (`events.py`). Cursor reads are gap-free by sequence.
- **Transcript** authority: the cell's session is authoritative for execution; `chat_messages` mirrors it by native message identity (`ChatDriver._absorb`).
- **Frontend** updates are pull-based. The chat page polls every 2.5 s while any task is working (`lumina/src/pages/Chat.tsx:56`); `AgentThinking.tsx` polls events every 2.5 s and `lib/orbs.ts:agentActivityFor` maps request state and event kinds to orb state and label; Live view polls steps and fetches frames.
- **SSE** (`accounts/streams.py:stream`, three streams per account, 900 s TTL) is not used by the app.
- **Browse job data** lives in service memory plus a per-job folder; a restart keeps the files (purged after 24 h) but loses the live job (`browse/service.py:385 purge`, `BrowseJobUnknown`).

## State and event catalog

### State machines
| Entity | Column | Values | Written by | Persisted |
|---|---|---|---|---|
| Request | `customer_requests.state` (0004:5) | waiting, starting, running, uncertain, completed, failed, cancelled | `RequestQueue.submit/claim/heartbeat/uncertain/finish/cancel` | yes |
| Request flags | `paused` (0022), `cancel_requested`, `fence`, `lease_until`, `retry_of`, `intent`, `context_json` | n/a | queue, driver | yes |
| Task | `tasks.state` (0001:6) | queued, running, waiting_for_approval, paused, cancelled, failed, budget_exhausted, completed, blocked | `BudgetLedger.admit` (queued), `ChatDriver.execute` (running), `_close` (terminal). The other four: **no writer** | yes |
| Reservation | `task_reservations.state` (0003:4) | active, uncertain, settled, cancelled | `admit` (active), `receipt/settle` (uncertain, settled), restore. `cancelled`: **no writer** | yes |
| Delivery | `chat_deliveries.state` (0005:27) | pending, acknowledged, uncertain, aborted, failed | `ChatDriver._set_delivery` (all but `failed`) | yes |
| Plan block | `ui_blocks.status` (0017:15) | draft, submitted, launched, superseded | `BlockStore.set_status` | yes |
| Plan phase | `plan_phase_runs.state` (0018:8) | pending, running, awaiting_approval, completed, failed, skipped, cancelled | `PlanRunner` | yes |
| Pursuit | `pursuit_state.status` (`pursuit.py:14`) | planning, running, waiting_user, replanning, verifying, verified, unverified_done, blocked, stopped, cancelled, interrupted | `ChatDriver._save_pursuit` (switch on) | yes |
| Verification level | `pursuit.VERIFY_LEVEL` | executed, subgoal_done, appears_complete, verified, unverifiable | `pursuit.verify` | inside pursuit JSON |
| Browser job (service) | in memory | queued, running, paused, asking + finals done, handoff, stopped, blocked, budget, error, cancelled, stuck, max_steps, deadline, replan | `BrowseRunner`, `BrowseService` | `browse_runs.status` is free text, mirrored by the worker |
| Cell | `lifecycle_cells.observed_state` (0002:4) | absent, stopped, running, unknown | lifecycle driver receipts | yes |
| Deployment | `deployments.state` (0001:3) | pending, ready, stopped, failed, deleting, deleted | lifecycle coordinator | yes |
| Operation | `operations.state` / `kind` (0001:7) | pending, running, completed, failed, uncertain / create, start, stop, upgrade, backup, restore, delete | `Coordinator.run` | yes |
| Telegram outbox | `telegram_outbox.state` (0006:63) | pending, sent, uncertain, failed | `TelegramService._try_send` | yes |
| Sign-up | `signups.state` (0021:4) | unverified, pending, approved, declined | `accounts/signup.py`, `signup_admin` | yes |
| Gateway session | derived | `active_run`, history `kind` = `tail` or `reset` | `gateway.history` | not stored by Lumina |

### Event kinds (`events.py:27`)
Emitted by application code: `task_queued`, `task_started`, `plan`, `progress` (also by the lifecycle worker), `activity`, `artifact`, `result`, `error` (all in `chat.py`). **Declared but never emitted:** `search`, `file_change`, `command_result`, `test_result`, `approval_request`, `approval_decision`, `budget`. Tool use is delivered as `activity` items instead (`activity.py:CATEGORY` maps tool names to `search`, `read`, `browse`, `command`, `file` and others).

### Queues and locks
| Queue or lock | Table or object | Ownership | Concurrency |
|---|---|---|---|
| Customer request queue | `customer_requests` + `request_slot` | worker `claim` | one running request in total; 3 waiting per account |
| Lifecycle operations | `operations` | `LifecycleWorker` → supervisor | serialized dispatch, one active cell slot (`lifecycle_slot`) |
| Browse jobs | in memory, `Semaphore(1)` | browse service | one job |
| Cell session | OpenClaw session lane | OpenClaw | one run per session |
| Telegram outbox | `telegram_outbox` | `telegram_worker` | per chat order |
| Billing inbox | `billing_inbox` | `billing_worker` timer | sequential |
| Mail jobs | account mail job table | `deliver_account_mail` timer | bounded |

## Where state could become stuck or contradictory
| Situation | Why | Evidence |
|---|---|---|
| Waiting request cancelled | `RequestQueue.cancel` updates only `customer_requests` | `request_queue.py:86-93`; reservation and task close only in `ChatDriver._close` |
| Request `uncertain` with unreachable runtime | Global slot held until abandon (1800 s) | `request_worker.py` `abandon_after=1800` |
| Browse job lost on restart | Jobs are in memory | `browse/service.py:166`; `BrowseJobUnknown` handled in `_run_browse` |
| `browse_runs` rows left `queued` | Release notes record two stale rows | `RELEASE_NOTES.md` "Known limits" |
| Form block with no creator | `submit_block` exists, no non-test `create_form` | `genui/store.py:61` |
| Reserved task states never written | Schema allows more than code produces | `0001_foundation.sql:6` versus `chat.py:569,612,620`, `budget.py:84` |
