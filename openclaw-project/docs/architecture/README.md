# Lumina architecture and agent execution map

Evidence-based map of what the code in this repository does, from a customer submitting a prompt to the final delivery.
Written 25 Oct 2026 from a read-only inspection of branch `product-phases-6-11` (working tree, including uncommitted changes). Nothing in the application, configuration or infrastructure was changed.

All paths are relative to `openclaw-project/` (the directory that holds this `docs/` folder). Line numbers are from that working tree and will drift; the symbol name is the durable reference.

## Start here
[native-execution.md](native-execution.md) is the current description: who owns what, the path of a request, tools, people, Stop, steering, goals, outcomes, recovery, and how it was validated. The pages below were written before that change; each carries a note saying where it is out of date (agent-execution, tool-routing, task-lifecycle, findings). system-overview is still the right map of components, minus the removed loop.

## Reading order
| File | What it answers |
|---|---|
| [system-overview.md](system-overview.md) | **Diagram A.** Which components exist, where the trust boundaries are, what is external. |
| [agent-execution.md](agent-execution.md) | **Diagrams B and C.** The request journey, step by step, and the call sequence. The 15 requested stages, who controls each, and the loop limits. |
| [tool-routing.md](tool-routing.md) | **Diagram D and F.** How tools are chosen, what the Search Web / Build & Code / Analyze Data / Automate buttons really do, the capability matrix, and capability-specific flows (browser, plan and approvals, automations, coding, integrations). |
| [task-lifecycle.md](task-lifecycle.md) | **Diagram E.** Every state name found, what changes it, what is persisted, cancellation and crash recovery. |
| [findings.md](findings.md) | Gaps, inconsistencies, unreachable code, stale documentation, unknowns, and (separately) recommendations. |

An older, shorter diagram is in [`../../platform/WORKFLOW.md`](../../platform/WORKFLOW.md). This folder supersedes it where they differ.

## Legend (used in every diagram)
| Style | Meaning |
|---|---|
| Solid box, green outline | Implemented and connected on the request path. |
| Solid box, amber outline | Implemented and connected, but only runs while an owner switch is on (see `agentai_platform/switches.py`). |
| Dashed box, grey outline | Implemented in code but not reachable from any route or caller found (dead or unrouted). |
| Dashed box, red outline | UI-only, placeholder, or disabled endpoint. |
| Violet box | External service. Its internals are not visible in this repository. |
| Dotted arrow | Polled, background or best-effort relationship (not a direct call). |
| Subgraph titled `TRUST ...` | A trust boundary. |

Exact identifiers (function names, routes, table names) are in the explanation under each diagram, not in the node labels.

## How to verify a claim
Each section ends with an **Evidence** list of `path:line  symbol`. Open the file at that symbol. When a statement says "no caller found", it comes from a search for importers and callers (`grep` over `platform/agentai_platform`, `platform/accounts`, `lumina/src`, excluding tests) and is not proof that nothing outside this repository calls it.

## Scope and method
- Read first: `../CLAUDE.local.md` (index notes), `lumina/AGENTS.md`, `platform/UI_CONTRACT.md`, `platform/README.md`, `ARCHITECTURE.md`.
- Traced by reading the code along one ordinary chat request, one Browse request, one Plan request, and a worker crash, plus every UI button listed in the brief.
- Not done: running any request, deploying, sending messages, purchases or scheduled jobs. No external service was contacted. The existing test suite was not run for this report.

## Snapshot facts
- Frontend: React 19 single-page app in `lumina/`, served by Django at `/app/`.
- Backend: Django app `platform/accounts/` over a SQLite store managed by `platform/agentai_platform/`, with 27 SQL migrations in `platform/migrations/`.
- The assistant itself is the OpenClaw runtime inside a per-customer container ("cell"). Lumina's code does not contain the assistant's agent loop; it sends messages to it and reads its transcript back.
- Lumina's own loop code is the **ChatDriver** (`agentai_platform/chat.py`) around the assistant, plus a separate **browser agent** (`agentai_platform/browse/`).

## Rendered diagrams
Every Mermaid block is also rendered to SVG in [`svg/`](svg/), named `<file>-<block number>.svg` (for example `system-overview-1.svg`, `agent-execution-1.svg` to `-4.svg`, `tool-routing-1.svg` to `-5.svg`, `task-lifecycle-1.svg` to `-4.svg`). They were produced by rendering the Mermaid source in Chrome (mermaid 11.4.1, default theme), so they use HTML text labels: open them in a browser. If a diagram and its SVG ever differ, the Mermaid source in the Markdown is the one to trust and re-render.

## Validation performed
- All 14 diagrams parse with `mermaid.parse` and render in Chrome.
- 376 source references (`path`, optional `:line`) were checked: every cited file exists (apart from the deleted `routing/services.py` and its tests, and `CLAUDE.local.md` and the root `README.md`, which live outside this directory), and no line number is past the end of its file. About 60 symbol-to-line pairs were spot-checked against the code.
- Not done: running the application or tests; any call to an external service; checking the deployed server.
