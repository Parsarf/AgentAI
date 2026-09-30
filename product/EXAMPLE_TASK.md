# One complete customer task — reading-list app

This is an acceptance specification, not a task already executed. Task budget:
$5 provider-cost ceiling, 60min, up to 30 metered model calls/20 searches;
admission includes coding/reviewer costs. If these routes lack an enforceable
quote/accounting, the request is blocked before execution rather than using
the owner's subscription. Estimated component allocation: research $0.40,
build $2.40, tests/browser $0.60, independent review $0.60, fixes/retries $0.50,
uncertainty reserve $0.50; sum $5.00. These are allocations, not measured prices.

Customer request: “Research two relevant reading-list apps using primary sources.
Build a private reading-list manager with title/URL validation, tags/search,
read status and notes. Persist my list after reload and export JSON. Test it,
verify in a browser, get an independent review, fix valid issues and give me a
ZIP with start/test instructions. Stay within $5 and one hour.”

| Step | Screen/event/state | Native/product mechanism | Observable assertion |
|---|---|---|---|
| 1 Sign in, choose Reading List project | Account/project; deployment ready | Server verified identity→account→private deployment | Other account cannot access project/session |
| 2 Submit dashboard or linked Telegram DM | Chat; queued with reservation | Atomic task creation + stable message/operation ID | Refresh/duplicate delivery starts one admitted task |
| 3 Research two primary sources | Timeline plan/search/source; running | Restricted researcher + critic | Links fetched; material claims supported, uncertainty stated |
| 4 Scope design | Chat plan + task checklist | Native orchestrator uses attributed data | No outside instruction changes tools/authority |
| 5 Build private app | File-change/command events | Native Codex in account/project boundary | Builder writes only scoped workspace, has no provider credential access |
| 6 Test and inspect | Test/browser results | Real tests + isolated browser worker | Assertions below pass on final revision |
| 7 Review/fix | Public findings/dispositions | Fresh independent ACP session/read-only source snapshot | Valid defects fixed, affected tests rerun; self-review not counted |
| 8 Capture/handoff | Completed/result/files/usage | Immutable version+hash/ZIP; reconcile usage | Download works; exact tested/reviewed source and instructions included |
| 9 Leave/reconnect/continue | Same history + cursor | Scoped replay/native history | No lost durable events, no rerun, correct active project |

App assertions (case `P15-EXAMPLE-APP`): reject blank title/invalid URL; add two
entries; tag/search/filter; edit notes; toggle read status; delete chosen entry;
reload retains remaining state; export JSON matches visible entries; empty/error
states work; keyboard focus/labels and 375px layout usable. No app public hosting,
real account integrations or purchases are needed. Include source/lockfile,
README with exact install/start/test commands, tests/results/source refs/review
summary and artifact manifest; exclude secrets/dependency caches/unrelated data.

Service assertions: customer B direct API/URL/cursor cannot fetch A's work;
usage UI matches enforcement ledger; budget exhaustion yields partial output and
no new paid call; cancellation reconciles receipts; unavailable reviewer prevents
verified completed status. `P15-CUSTOMER-BOUNDARY`, `P15-CHAT-RECONNECT`,
`P15-BUDGET`, `P15-ARTIFACT`, `P17-COMPLETE-WORKFLOW` cover those behaviors.
Final acceptance uses an actual authorized customer Telegram start and dashboard
continuation; fixture-only proof is recorded separately from that real workflow.
