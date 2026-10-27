# Current orchestration (diagrams 1 to 7)

Legend for every diagram in this audit:

| Style | Meaning |
|---|---|
| Green solid box | Current and reachable |
| Amber box | Reachable under specific configuration (owner switch, setting or running service) |
| Grey dashed box | Implemented but disabled, or apparently unreachable |
| Blue-grey box | Legacy but still partially active |
| Red dashed box | Deleted from the tree but recoverable from Git; or superseded |
| Violet box | External or not inspectable |
| Teal box | Test-only, mock, experiment, prototype or documentation-only |
| Orange dotted box | Uncertain |
| **Solid arrow** | Current connection, verified in code |
| **Dashed arrow `cfg`** | Conditional connection (switch or setting) |
| **Dashed arrow `?`** | Uncertain relationship |
| **Arrow labelled `hist`** | Historical connection (not part of current execution) |

Node names carry the path identifier from [02-path-registry.md](02-path-registry.md). Exact functions are in the tables under each diagram.

## 1. Complete orchestration landscap

```mermaid
flowchart LR 
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef dis fill:#1b1c22,stroke:#8a8d99,color:#c9cbd3,stroke-dasharray:5 4
  classDef leg fill:#18222c,stroke:#6a8cb0,color:#d5e3f0
  classDef del fill:#2a1616,stroke:#ef6a6a,color:#f5d0d0,stroke-dasharray:5 4
  classDef ext fill:#1f1a33,stroke:#a78bfa,color:#e0d6fa
  classDef tst fill:#112a2a,stroke:#4fd1c5,color:#d0f2ee
  classDef unc fill:#2b2014,stroke:#ff9a3d,color:#ffe3c2,stroke-dasharray:2 3

  subgraph CUSTOMER["CUSTOMER ENTRY"]
    E1["P01 Auto chat<br/>assistant-first protocol"]:::cfg
    E2["P02 Text mode"]:::cfg
    E3["P03 Plan mode and phases"]:::cfg
    E4["P04 Browse mode"]:::cfg
    E8["P08 Form submit<br/>no creator in wt"]:::dis
    E9["P09 Retry and resume"]:::cfg
    E10["P10 Telegram inbound"]:::cfg
    E11["P11 Classic chat page"]:::cfg
    E12["P12 Classic Requests POST<br/>ends unfunded"]:::leg
    E13["P13 Browser control and answers"]:::cfg
  end

  subgraph ENGINE["SHARED ENGINE"]
    ADM["Admission: queue + budget<br/>ChatService.send, RequestQueue, BudgetLedger"]:::cur
    WRK["Request worker: claim, lease, fence<br/>RequestWorker, ChatDriver.execute"]:::cur
    LOOP["Assistant turn loop and tool steps<br/>_poll, _answer_step"]:::cur
    FIN["P16 finish: files, cards"]:::cur
    REC["P18 reconcile and abandon"]:::cur
    ACC["P19 usage settlement"]:::cur
    EVT["P20 events and polling"]:::cfg
  end

  subgraph TOOLS["TOOL PATHS"]
    T5["P05 browser step<br/>ToolDecider, browse service"]:::cfg
    T6["P06 search step<br/>assistant's own search"]:::cfg
    T7["P07 Pursuit<br/>plan, supervise, verify"]:::dis
    T14["P14 shadow routing"]:::cfg
    T15["P15 JEV display layout"]:::dis
  end

  subgraph CELL["CUSTOMER CELL AND LIFECYCLE"]
    L17["P17 wake, hand-over, sleep"]:::cfg
    A24["P24 OpenClaw assistant loop<br/>tools, sub-agents, cron, approvals"]:::ext
    A45["P45 OpenClaw cron and sub-agents<br/>in customer cells"]:::unc
  end

  subgraph EXTERNAL["EXTERNAL"]
    X43["P43 model path<br/>relay, LiteLLM, provider"]:::ext
    X44["P44 JEV / TypeSafe"]:::ext
  end

  subgraph OWNER["OWNER AND OPERATOR"]
    O21["P21 owner dashboard and switches"]:::cur
    O22["P22 operator endpoints, CLIs, systemd"]:::cur
    O23["P23 billing and sign-up jobs"]:::cur
    O25["P25 owner main orchestrator + workers"]:::unc
    O26["P26 Jev research plugin"]:::unc
    O28["P28 native Claude Code / Codex"]:::dis
  end

  subgraph DORMANT["IMPLEMENTED BUT NOT CONNECTED"]
    D27["P27 browser-opt route"]:::dis
    D29["P29 worker broker"]:::dis
    D30["P30 durable objectives, memory,<br/>schedules, skills, watchers"]:::dis
    D31["P31 optimization gate"]:::dis
    D32["P32 policy check"]:::dis
    D33["P33 legacy stdlib server"]:::dis
    D34["P34 disabled-kind routes"]:::leg
  end

  subgraph HISTORY["HISTORICAL (recoverable from Git or archives)"]
    H35["P35 keyword intent + local forms"]:::del
    H36["P36 ServiceRouter-first routing"]:::del
    H37["P37 legacy AgentAI orchestrator"]:::del
    H38["P38 jev-browser versions"]:::tst
    H39["P39 jev-window-core"]:::tst
  end

  subgraph SUPPORT["TEST, DOC, EVAL"]
    S40["P40 phase plans and contract"]:::tst
    S41["P41 mocks and dev preview"]:::tst
    S42["P42 eval harness"]:::tst
  end

  E1 --> ADM
  E2 --> ADM
  E3 --> ADM
  E4 --> ADM
  E9 --> ADM
  E10 --> ADM
  E11 --> ADM
  E12 -->|"no reservation"| ADM
  E8 -.->|"? legacy rows only"| ADM
  ADM --> WRK --> LOOP
  LOOP -->|"send, history"| A24
  A24 -->|"model calls"| X43
  LOOP --> T6
  LOOP -->|"lumina-step"| T5
  LOOP -.->|"cfg pursuit"| T7
  T7 -.-> T5
  T5 -->|"decisions"| X44
  T5 --> X43
  WRK -.->|"cfg jev_routing"| T14
  T14 --> X44
  LOOP --> FIN
  FIN -.->|"cfg jev_display"| T15
  T15 --> X44
  WRK --> REC
  FIN --> ACC
  WRK --> EVT
  E13 --> T5
  WRK -.->|"cfg wake"| L17
  L17 --> A24
  A24 -.->|"? unknown config"| A45
  O21 -.->|"switches file"| WRK
  O21 -.->|"switches file"| T5
  O22 --> L17
  O25 -.->|"?"| A24
  D27 -.->|"no importer"| T5
  D30 -.->|"no importer, routes disabled"| ADM
  H36 -.->|"hist replaced by"| LOOP
  H35 -.->|"hist replaced by"| E1
  H37 -.->|"hist retired 27 Sep"| E1
```

**Reading.** Nodes with no arrows (P23, P26, P28, P29, P31 to P33, P38 to P42) are in their group because they have no verified connection to the customer engine; their relationships are in [02-path-registry.md](02-path-registry.md). Everything customers can start flows through one admission step, one worker and one driver. The only intelligence Lumina's code has is (a) deterministic rules and (b) small JEV questions to a third party. The assistant (P24) and the browser agent (P05) make the open-ended decisions. A large amount of implemented code (P27 to P33) is not connected to any caller, and several historical engines (P35 to P37) are recoverable from Git only.

## 2. Current end-to-end request flow

```mermaid
flowchart TD
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef bad fill:#2a1616,stroke:#ef6a6a,color:#f5d0d0
  classDef ext fill:#1f1a33,stroke:#a78bfa,color:#e0d6fa

  A["Composer: message + key + mode<br/>P01 to P04"]:::cur
  B["send: auth, rate limit, validate, queue cap, reserve budget<br/>ChatService.send"]:::cur
  C["customer_requests = waiting<br/>events: task_queued"]:::cur
  D["P17 wake cell if stopped"]:::cfg
  E["P18 worker tick: reconcile stuck request first"]:::cur
  F["claim one request, state starting, 120 s lease"]:::cur
  G{"funded and cell active<br/>(browse needs no cell)?"}:::cur
  H["fail unfunded<br/>(this is where P12 ends)"]:::bad
  I["ChatDriver.execute<br/>open or reuse cell session<br/>deliver message with preamble (P01)"]:::cur
  J["Poll transcript 1.5 s<br/>activity events, rows mirrored"]:::cur
  K{"reply has lumina-step?"}:::cur
  L["ToolDecider: site, JEV or rules"]:::cfg
  M["P05 browser or P06 search"]:::cfg
  N["result message back to the assistant"]:::cur
  O["files captured, cards attached<br/>P16"]:::cur
  P["spend reconciled and settled<br/>P19"]:::cur
  Q["request completed, failed or cancelled<br/>slot freed"]:::cur
  R["customer polls: reply, cards, files<br/>P20"]:::cur
  X["abort and fail at 900 s, or cancel, or crash"]:::bad

  A --> B --> C --> D --> E --> F --> G
  G -- no --> H --> Q
  G -- yes --> I --> J --> K
  K -- yes --> L --> M --> N --> J
  K -- no --> O --> P --> Q --> R
  J -.-> X
  X -.-> P
```

| Step | Function | Evidence |
|---|---|---|
| send and reserve | `ChatService.send`, `BudgetLedger.admit` | `chat.py:224`, `budget.py:74-91` |
| claim | `RequestQueue.claim` | `request_queue.py:126` |
| funded check | `RequestWorker._tick` | `request_worker.py` (unfunded branch) |
| deliver | `ChatDriver.execute` | `chat.py:584` |
| poll | `ChatDriver._poll` | `chat.py:1300` |
| tool step | `_answer_step` | `chat.py:897` |
| finish | `_capture_files`, `attach_cards`, `_close` | `chat.py:1242,730,559` |
| settle | `_reconcile_usage`, `ledger.settle` | `chat.py:521`, `budget.py:116` |

## 3. Planning and decision flow

```mermaid
flowchart TD
  classDef cust fill:#1b1d27,stroke:#7455ff,color:#f2f2f5
  classDef code fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef model fill:#1f1a33,stroke:#a78bfa,color:#e0d6fa
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef dis fill:#1b1c22,stroke:#8a8d99,color:#c9cbd3,stroke-dasharray:5 4

  M0["Customer chooses Respond mode<br/>CUSTOMER decides"]:::cust
  M1{"mode"}:::code
  P1["plain chat, no tool protocol<br/>P02"]:::code
  P2["intent plan: assistant drafts a JSON plan<br/>3 to 10 phases<br/>MODEL proposes, code validates"]:::model
  P3["customer edits and approves<br/>CUSTOMER decides"]:::cust
  P4["PlanRunner runs enabled phases in order<br/>CODE decides order and gates"]:::code
  P5["intent browse: run the browser directly<br/>P04"]:::cfg
  P6["Auto: assistant reads message first<br/>MODEL decides: answer, ask, plan, tool"]:::model
  Q1{"asks for a step?"}:::model
  Q2["code validates step fields<br/>agent_protocol.clean"]:::code
  Q3{"site named?"}:::code
  Q4["browser, no model call"]:::code
  Q5{"jev_services on and JEV sure >= 0.6?"}:::cfg
  Q6["JEV chooses browser or search<br/>EXTERNAL MODEL decides"]:::cfg
  Q7["keyword rules choose<br/>CODE decides"]:::code
  Q8{"pursuit switch on?"}:::cfg
  Q9["stored plan with success criteria<br/>MODEL writes, code stores<br/>P07"]:::dis
  Q10["code decides continue, replan, ask user, stop, close<br/>pursuit.next_action"]:::dis
  Q11["single browser session per message"]:::code

  M0 --> M1
  M1 -- text --> P1
  M1 -- plan --> P2 --> P3 --> P4
  M1 -- browse --> P5
  M1 -- auto --> P6 --> Q1
  Q1 -- no --> END1["answer"]:::code
  Q1 -- yes --> Q2 --> Q3
  Q3 -- yes --> Q4
  Q3 -- no --> Q5
  Q5 -- yes --> Q6
  Q5 -- no --> Q7
  Q4 --> Q8
  Q6 --> Q8
  Q7 --> Q8
  Q8 -- yes --> Q9 --> Q10
  Q8 -- no --> Q11
```

**Decision ownership in one line each.** Mode: customer. Whether to plan, ask, answer or use a tool: the assistant model. Whether a step is well-formed and which tool runs: Lumina code, with an optional JEV answer. Whether to continue after a browser session: the assistant (one session) or code (`pursuit.next_action`) when `pursuit` is on. Whether a browser action is allowed: code rules, never a model. See [07-registries.md](07-registries.md#decision-ownership-matrix).

## 4. Model and tool-routing flow

```mermaid
flowchart LR
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef dis fill:#1b1c22,stroke:#8a8d99,color:#c9cbd3,stroke-dasharray:5 4
  classDef ext fill:#1f1a33,stroke:#a78bfa,color:#e0d6fa

  subgraph LUMINA["LUMINA CODE (P01, P05, P14, P15)"]
    DRV["ChatDriver"]:::cur
    TD["ToolDecider P05<br/>jev-1.13.0 config"]:::cfg
    SH["ShadowRouter P14<br/>jev-1.13.0"]:::cfg
    DSP["DisplayDecider P15"]:::dis
    LAD["Browse ladder"]:::cfg
    REV["Browse review P07"]:::dis
  end
  subgraph MODELS["MODELS"]
    SON["claude-sonnet-5-5<br/>assistant default, browser tier 3"]:::ext
    HAI["claude-haiku-4-5<br/>browser tier 2, utility"]:::ext
    S46["claude-sonnet-4-6<br/>allowed alias"]:::ext
    J13["jev-1.13.0<br/>routing, tool choice, display"]:::ext
    J14["jev-1.14.0<br/>browser steps"]:::ext
  end
  subgraph TOOLSNODE["TOOLS"]
    OWN["Assistant's own tools in the cell<br/>exec, read, write, web_search, web_fetch ..."]:::ext
    BRW["Lumina browser<br/>runner.mjs in Chromium"]:::cfg
    SEARCH["web_search via Brave plugin"]:::ext
  end

  DRV -->|"message + preamble"| SON
  SON --> OWN
  OWN --> SEARCH
  SON -->|"lumina-step"| DRV
  DRV --> TD
  TD -.->|"cfg jev_services"| J13
  TD -->|"browser"| BRW
  TD -->|"search nudge"| SON
  DRV -.->|"cfg jev_routing"| SH --> J13
  DRV -.->|"cfg jev_display"| DSP --> J13
  BRW --> LAD
  LAD -->|"tier 1"| J14
  LAD -->|"tier 2"| HAI
  LAD -->|"tier 3, max 2 per run"| SON
  LAD -.-> REV
  REV -.->|"one question"| J14
  S46 -.->|"allowed, not default"| SON
```

**Notes.** The assistant model is chosen by provisioning (`DEFAULT_MODEL`), never per request. JEV is called under two model ids: `jev-1.13.0` (routing config default, tool choice, display, optimization, research adapter) and `jev-1.14.0` (browser, pinned in `browse/service_main.py:20`). Model access for cells goes through the relay that allows only completions and model listing (`deploy/model-proxy/agentai_model_proxy.py:9`). Detailed registry: [07-registries.md](07-registries.md#tool-and-model-registry).

## 5. Execution loop and replanning

```mermaid
flowchart TD
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef dis fill:#1b1c22,stroke:#8a8d99,color:#c9cbd3,stroke-dasharray:5 4
  classDef bad fill:#2a1616,stroke:#ef6a6a,color:#f5d0d0

  subgraph OUTER["OUTER LOOP: ChatDriver (P01, P05, P06, P07)"]
    O1["send message to assistant"]:::cur
    O2["_poll until reply and idle x2<br/>cancel check, lease heartbeat, 900 s cap"]:::cur
    O3{"step block?"}:::cur
    O4["rounds < 6 (12 with pursuit)?"]:::cur
    O5["run tool, build result message"]:::cur
    O6["send follow-up in the same session"]:::cur
    O7["finish"]:::cur
    O1 --> O2 --> O3
    O3 -- no --> O7
    O3 -- yes --> O4
    O4 -- no --> O7
    O4 -- yes --> O5 --> O6 --> O2
  end

  subgraph INNER["INNER LOOP: browser job (P05)"]
    I1["observe: snapshot, candidates, screenshot"]:::cfg
    I2{"code rules:<br/>human check, payment,<br/>sign-in, sensitive, denied"}:::cfg
    I3["handoff to the customer"]:::bad
    I4["ladder: JEV, Haiku, Sonnet"]:::cfg
    I5["act on fresh target"]:::cfg
    I6{"done, stuck, 25 steps,<br/>600 s, budget?"}:::cfg
    I7["periodic progress review<br/>JEV one question or rules (P07)"]:::dis
    I1 --> I2
    I2 -- trip --> I3
    I2 -- clear --> I4 --> I5 --> I6
    I6 -- continue --> I7 --> I1
    I6 -- end --> I8["final state to the worker"]:::cfg
  end

  subgraph REPLAN["PURSUIT RE-PLANNING (P07, switch off)"]
    R1["verify result against success criteria"]:::dis
    R2{"next_action"}:::dis
    R3["continue: more plan steps"]:::dis
    R4["replan: assistant told why and asked for a revised step"]:::dis
    R5["ask_user"]:::dis
    R6["stop or close with a fixed ending"]:::dis
    R1 --> R2
    R2 --> R3
    R2 --> R4
    R2 --> R5
    R2 --> R6
  end

  O5 --> I1
  I8 --> R1
  R3 -.-> O6
  R4 -.-> O6
```

**Loop controls (from code).** Outer: `SETTLE_POLLS=2`, `MAX_STEP_ROUNDS=6`, `PURSUIT_MAX_ROUNDS=12`, `poll_interval=1.5`, `run_timeout=900`, `usage_wait=45` (`chat.py:41-44,431`). Inner: `max_steps=25`, `max_seconds=600` (service caps 40 and 900), ladder `max_sonnet=2`, one job at a time (`browse/loop.py:79`, `service.py:166,179`, `ladder.py:577`). Without pursuit, the assistant (not code) decides whether to continue after a result; there is no code-level evaluation of whether the final answer satisfies the request.

## 6. Queue, worker, cell and concurrency architecture

```mermaid
flowchart LR
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef ext fill:#1f1a33,stroke:#a78bfa,color:#e0d6fa
  classDef lock fill:#2a1a28,stroke:#d46aa0,color:#f5d6e8

  subgraph DB["APP DATABASE (SQLite, WAL)"]
    Q["customer_requests<br/>waiting, starting, running, uncertain, ..."]:::cur
    S1["request_slot (one row)<br/>GLOBAL SERIAL SLOT"]:::lock
    S2["lifecycle_slot (one row)<br/>ONE ACTIVE CELL"]:::lock
    R["task_reservations<br/>per task, per account, per service allowance"]:::cur
  end
  subgraph PROCS["PROCESSES"]
    APP["gunicorn app<br/>accounts.wsgi"]:::cur
    RW["request worker<br/>one tick = one request"]:::cfg
    LW["lifecycle worker"]:::cfg
    SUP["supervisor (root)<br/>serialized dispatch"]:::cfg
    BR["cell bridge (root)<br/>per-account lock"]:::cfg
    BS["browse service (root)<br/>Semaphore(1): one job"]:::cfg
  end
  subgraph CELLS["CELLS"]
    C1["cell of account A<br/>(OpenClaw, gVisor)"]:::ext
    C2["cell of account B<br/>(stopped)"]:::ext
  end

  APP -->|"submit, admit"| Q
  APP --> R
  RW -->|"claim"| S1
  RW -->|"requires active cell for same account"| S2
  RW --> BR --> C1
  RW --> BS
  LW -->|"wake, drain, stop"| SUP --> C1
  LW --> S2
  C2 -. "capacity: at most one running cell in the trial profile" .-> S2
```

**Concurrency scopes, as implemented.**
- **Requests:** one running request across **all** customers (`request_slot` row, `RequestQueue.claim` returns nothing while the slot is held; `request_queue.py:128-131`). Per account only 3 may be `waiting`.
- **Cells:** the trial capacity profile allows one running cell; `wake_plan` hands over only when the other cell is idle (900 s, or 60 s when another account waits) (`lifecycle/sleep.py`, `worker.py:152`). Host capacity is read at run time (`lifecycle/capacity.py`, default 2 per file note).
- **Browser:** one job at a time on the host (`Semaphore(1)`); job state is in service memory, so a restart loses running jobs.
- **Within a cell:** OpenClaw serialises runs per session lane (docs `agent-loop.md`).
- **Bridge:** one connection and lock per account (`cell_bridge.py:157-190`).

## 7. Approvals, interruption and cancellation

```mermaid
flowchart TD
  classDef cur fill:#10231c,stroke:#34d3a0,color:#d7f5ea
  classDef cfg fill:#2a2314,stroke:#f5b942,color:#f5e6c0
  classDef cust fill:#1b1d27,stroke:#7455ff,color:#f2f2f5
  classDef bad fill:#2a1616,stroke:#ef6a6a,color:#f5d0d0
  classDef dis fill:#1b1c22,stroke:#8a8d99,color:#c9cbd3,stroke-dasharray:5 4

  subgraph APPROVALS["WHERE A HUMAN DECIDES"]
    A1["Plan phase requiresApproval<br/>awaiting_approval until approved<br/>genui/runner.py:91"]:::cust
    A2["Browser asks a question or fields<br/>state asking, customer answers<br/>browse/loop.py:456, accounts/browse.py answer"]:::cust
    A3["Browser handoff: payment, sign-in, human check<br/>customer takes the wheel"]:::cust
    A4["Saved login or card used only with customer approval<br/>vault, loop _fill_login/_fill_card"]:::cust
    A5["Assistant tools: no Lumina approval flow<br/>approval_request event is never emitted"]:::dis
  end
  subgraph CANCEL["WHAT STOPS WORK"]
    C1["Stop on a waiting request<br/>state cancelled at once"]:::cur
    C2["Stop on a running request<br/>cancel_requested flag"]:::cur
    C3["driver poll sees the flag"]:::cur
    C4["assistant run: gateway.abort(session, run_id)"]:::cur
    C5["browser job: rpc cancel; service stops the loop"]:::cfg
    C6["owner turns browse_tasks off<br/>service kill-switch watcher cancels all jobs"]:::cfg
    C7["account revoked: next heartbeat sets cancel_requested"]:::cur
    C8["close as cancelled, settle spend"]:::cur
  end
  subgraph LIMITS["WHAT LUMINA DOES NOT CONTROL"]
    L1["the assistant's own tool calls inside the cell<br/>(only the whole run can be aborted)"]:::bad
    L2["external effects already performed by a tool"]:::bad
  end

  C1 --> C8
  C2 --> C3
  C3 --> C4 --> C8
  C3 --> C5 --> C8
  C6 --> C5
  C7 --> C3
  C4 -.-> L1
  C5 -.-> L2
```

**Interruption by a follow-up message.** A new message while a request runs is a new request (queued, max 3 waiting) and runs afterwards in the same cell session; it does not steer the running run. OpenClaw's own queue modes (steer, followup, collect, interrupt) are not used by Lumina's bridge, which only exposes `chat.send` / `chat.abort`.

**Resumption.** Approvals gate phases by state, not by pausing a process: a phase that awaits approval simply has no request yet (`runner.py:91-95`). The browser `asking` state is a live pause inside the job (deadline extended while waiting, `chat.py:_run_browse`). A crash during either loses only the in-memory browser job.

**Evidence:** `request_queue.py:86-109,162-170`; `chat.py:_poll`, `_run_browse`, `abort`; `browse/service.py:64 (watch_kill_switch)`; `events.py:37`; `genui/runner.py:91-95,159-188`.
