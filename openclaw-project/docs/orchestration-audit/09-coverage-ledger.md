# Coverage ledger

What was inspected, how, what was excluded or unavailable, and what remains unresolved. "Inspected" means read, not run. Nothing was executed, deployed, installed, switched or modified apart from creating files under `docs/orchestration-audit/` (and a temporary Mermaid checker in the session scratch folder, outside the repository).

## 1. Repository boundaries
| Area | Coverage |
|---|---|
| Git root `/Users/parsa/AgentAI` (122 commits, 15 local branches, 9 remote-tracking branches, 10+ tags, 15 worktrees) | Branch graph, tags, worktree list and status counts inspected; all commit subjects read; selected commits and paths read with `git show`/`git log`; no checkout, reset or branch switch |
| `openclaw-project/platform/` (Django `accounts/`, `agentai_platform/`, `migrations/`, `deploy/`, `tests/`) | **Inspected in depth** (next sections) |
| `openclaw-project/lumina/` (frontend) | Composer, Home, Chat, AgentThinking, Shell, Info, orbs, api client read; rest of `lumina/src` not read for orchestration (no server-side decisions live there) |
| `openclaw-project/browse/` (`runner.mjs`) | Header and role read; command set not traced line by line |
| `openclaw-project/dashboard/` | Routes, switch and routing controls, gateway reader inspected |
| `openclaw-project/bin/`, `deploy/`, `config/`, `plans/`, `evals/`, `browser-opt/`, `research-opt/` | Headers, configuration structure and key files read; not every file |
| `openclaw-project/evidence/` (149 files) | **Not read** (phase proof logs); named only |
| `openclaw-project/backups/` | Archive listing only (54 entries; an owner-runtime backup from 24 Sep) |
| `openclaw-project/tmp/`, `reviews/`, `research/` | Listed; empty or not orchestration code |
| `phase-prompts/`, `product/` | Existence and role noted; contents sampled in earlier work, not re-read |
| `jev-browser/`, `jev-window-core/` (untracked) | READMEs and file lists; code not traced |
| `jev-browser-*.tar.gz` (4) | Listings and READMEs via `tar -tzf` and `tar -xOzf` to the terminal only (nothing extracted) |
| `lumina-cost-audit/` | Executive section and era definitions read |
| `sonarqube-export/`, `*.PNG`, screenshots, zips | Excluded (not orchestration) |
| `ssk-key`, `ssk-key.pub` | **Excluded on purpose** (credentials) |
| `jev-browser/.env`, other `.env` files | **Not opened** |
| `~/.openclaw` | Directory name only (`migration`); contents not read |
| OpenClaw 2026.9.6 at `~/.npm-global/lib/node_modules/openclaw` | `docs/` read for agent loop, tools index, sub-agents, built-in tool config, timeouts; `dist/` (7 297 files, bundled) **not** traced |
| `.claude/worktrees/*` | `git status` counts and tip commits; not diffed except `worktree-product-images` |

## 2. Searches performed
- Behaviour terms across tracked files outside `lumina/` and `evidence/` (counts of files): planner (12), orchestrat (34), dispatch (40), router/route_decision/ServiceRouter (5), `lumina-step` (2), pursuit (12), claim/lease (115), reconcil (110), native_session/open_session (12), tool_call/tool_use (6), approval (103), scheduler/schedule (77), fallback (53), replan (6).
- Module docstring or header-comment survey of all 198 tracked `.py`, `.mjs`, `.js`, `.sh` files outside `lumina/`, tests, `node_modules`, `evidence/` and migrations.
- Importer and caller searches for 30 modules (reachability), including registration through `urls.py`, systemd `ExecStart`, and `manage.py` commands.
- Owner switch consumers (all 15 keys) across `platform`, `dashboard`, `bin`, `browser-opt`, `research-opt` including untracked files.
- Model identifiers across code and configuration (`claude-*`, `jev-*`, `gpt-*`, `litellm/*`).
- Event emitters versus declared kinds; state writers versus schema `CHECK` sets.
- Environment variable names in `accounts/settings.py` and `agentai_platform/**`.
- Tests: counted by pattern (95 test files, 1,191 test functions; tests were **not run**); searched for references to deleted modules (`ServiceRouter`, `intent.detect`: none remain).

## 3. History inspected
- Full commit list (122) with dates; 13 path histories (`--follow`, `--diff-filter=A|D`) for the orchestration modules.
- Legacy tree at `8298602^` (listing, `orchestrator.py` head and symbols, `limits.yaml`).
- `routing/services.py` at `5db9636^` (head and symbols); `HEAD` versions of `chat.py` and `genui/intent.py` (call sites).
- Branch ahead/behind and merge-base diffs for all 17 local and remote branches; `worktree-product-images` diff stat.
- Release and deployment record in `RELEASE_NOTES.md` (live1 to live24).
- **Not inspected:** diffs of every commit; blame; reflog; deleted files outside the orchestration set; commits' non-orchestration content.

## 4. Per-subsystem coverage
| Subsystem | Depth | Notes |
|---|---|---|
| Chat service, driver, queue, worker, ledger | Read most of `chat.py` (all of `send`, `execute`, `_poll`, `_run_browse`, `_close`, `reconcile`, pursuit helpers), `request_queue.py`, `request_worker.py`, `budget.py` (admit, receipt, settle) | `_baseline`, `_mirror_browse`, `_absorb` skimmed |
| Agent protocol, tool decider, routing, shadow, display | Read | `routing/classifier.py` and `decision.py` skimmed |
| Browse loop, ladder, service, review, modes | Read headers, constants, control flow around gates and limits; ladder prompts and parsing **not** traced line by line | |
| Pursuit | Module structure and `next_action`, `verify`, `closing` signatures read; internals of `check`/`validate` skimmed | |
| Generative UI | `runtime`, `runner`, `store` entry points, `prompts.plan_prompt`, routes read; schema and `data.py` skimmed | |
| Lifecycle | `worker`, `sleep`, `coordinator` header, `cell_config`, `cell_bridge` allowed methods and locking, `supervisor_main`, `native_wiring` header; Fleet driver and volumes not traced | |
| Gateway | `NativeGateway` methods and protocol pin read | |
| Events, activity | Read `events.py` header and kinds, `activity.py` categories | |
| Telegram, connectors, billing, signup | Entry points and importers only | Not orchestration-central |
| Ops (backup, monitor, restore) | Module docstrings only | |
| Dashboard | Routes and switch handling | |
| Frontend | As listed above | |

## 5. Unavailable or inaccessible
- The production server (switch file, facts file, systemd drop-ins, release folders, journals, database).
- TypeSafe/JEV, LiteLLM, the model provider, Stripe, Telegram (external services).
- OpenClaw source behind `dist/` (bundled; not traced).
- Any process or script outside the repository that might import a module this audit marks unreachable.

## 6. Unresolved at the end
See [08-inconsistencies.md](08-inconsistencies.md) sections C and D (hypotheses H-01 to H-06, unknowns U-01 to U-07).

## 7. Reconciliation of diagrams and registry
| Check | Method | Result |
|---|---|---|
| Every registry path (P01 to P45) appears in diagram 1 | script matching `P\d\d` in the landscape block | see README "Validation" |
| Every diagram parses | `mermaid.parse` (mermaid 11.4.1 under jsdom) | see README "Validation" |
| Every diagram renders | rendered in Chrome, saved to `svg/` | see README "Validation" |
| Every source reference resolves | script over `` `path[:line]` `` tokens | see README "Validation" |
| Diagram edges without direct evidence | labelled `?`, `cfg`, `hist` or drawn dashed | all such edges are listed in the legend; none is drawn solid without a code reference |
