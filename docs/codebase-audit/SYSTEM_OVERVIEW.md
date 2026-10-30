# Lumina: System Overview

> **UPDATE 2026-10-29:** production was verified over SSH after this document was written. Statements below that production is "unverified" are superseded for the items in [PRODUCTION_VERIFICATION_2026-10-29.md](PRODUCTION_VERIFICATION_2026-10-29.md) (live host is Hostinger `179.236.71.203`; IONOS is dead; IS-002 and the tool-origin v2 drift confirmed; IS-004 resolved; M-01 latent, not observed).

Audit date 2026-10-29. Branch `product-phases-6-11`, HEAD `03662de`, plus uncommitted tool_origin / tool_relay / cell_bridge / cell_config work (IN PROGRESS, not judged). **Production is UNVERIFIED throughout** (no SSH or network was used; see L-01 to L-03 in `_findings/00_RECONCILIATION.md`). Everything below describes the repo as intended.

## 1. What Lumina is

A hosted personal AI assistant ("Lumina", site getlumina.pro). Each customer gets an isolated OpenClaw 2026.9.6 "cell" (gVisor container) running a Sonnet 5.5 tool loop. The customer chats in a React web app; the assistant can search the web, write files, and drive a real browser on their behalf (with the customer able to watch live and take over). A prepaid plan limits spend per task, per day, and per period.

Internal naming: repo root is `AgentAI`, project dir is `openclaw-project/`, product brand is Lumina. "JEV" is an external hosted vision/choice model (TypeSafe, `jev-1.13.0` in code constant, `jev-1.14.0` in browse service); it is NOT the local `jev-browser/` prototype (OP-004).

## 2. Who it serves

| Audience | Surface |
|---|---|
| Customers (private beta, small number) | `lumina/` SPA at `/app/`, Django `/account/` pages, Telegram (not working, BE-007) |
| Owner / operator (one person) | `dashboard/` (SSH-tunnelled), `bin/` helpers on the owner Mac, `manage.py account_admin` and friends on the host |
| Customer-facing contract | `product/CONTRACT.md`, `product/plan.json` ($79/mo plan, $25 included, $15 per rolling 24 h, $5 per task, 3 queued tasks) |

Owner priority (memory): customer privacy over new task guardrails. Findings are ranked with that in mind.

## 3. Components

| Component | Where | Role |
|---|---|---|
| Web SPA | `openclaw-project/lumina/` (React 19, Vite, TS) | Chat, tasks, live view, files, safety console, generative UI |
| Customer app | `platform/accounts/` (Django 5.2, gunicorn, SQLite) | Auth, REST `/v1/*`, SPA bundle server, Stripe and Telegram webhooks |
| Platform library | `platform/agentai_platform/` | Queue, budget ledger, chat service, driver, gateway, billing, vault, genui, ops |
| Request worker | `manage.py request_worker` | Serial queue consumer; runs `ChatDriver` against the cell |
| Cell lifecycle | `agentai_platform/lifecycle/` (supervisor, bridge, fleet driver, netpolicy) | Starts/sleeps one customer cell, root-owned bridge to cell Gateway |
| Tool relay | `agentai_platform/tool_relay.py` (MCP over HTTP, 10.77.0.1:4100) | Lets a cell call `lumina_browser`, `lumina_task_update` |
| Browse service | `agentai_platform/browse/` + `browse/runner.mjs` | Observe-decide-act browser loop, safety floor, JEV ladder, live frames |
| Model relay | `platform/deploy/model-proxy/` (10.77.0.1:4000) | Cell to LiteLLM, completions/models only |
| Owner stack | `deploy/docker-compose.production.yml` | Postgres, LiteLLM, OpenClaw Gateway (owner), CLI |
| Owner dashboard | `dashboard/app.py` (stdlib, 1718 LOC) | Owner ops UI on 127.0.0.1:18795 |
| Ops | `agentai_platform/ops/` | Encrypted backup, scoped restore, monitor, alerts |
| Edge | Vercel rewrites to Caddy `backend.getlumina.pro` | TLS, routing, live-frame path |

## 4. Tech stack

- Python 3.12 (CI) to 3.14 (local); Django 5.2.17, django-otp, gunicorn 26.2, cryptography 50 (hash-pinned `platform/requirements.lock`, only 9 packages). Everything else is stdlib, including the control server, dashboard, and most clients (ST-007, ST-011).
- SQLite (WAL, `IMMEDIATE` transactions) for the customer app; 30 raw SQL migrations plus 15 Django migrations (two systems, BE-012). Postgres only for the owner LiteLLM budget DB.
- TypeScript: React 19.3, Vite 8.3, vitest 5, zod 4.6, mermaid, katex, three/R3F (`lumina/package.json`).
- Node: `playwright-core 1.49.1` in `browse/`; OpenClaw plugin `.mjs` for tool-origin proofs.
- Docker with gVisor (`runsc`) on a second engine for customer cells; nftables + ufw egress policy; systemd units (18 files).
- External: Anthropic (via LiteLLM), Brave search, TypeSafe/JEV, Stripe, Telegram, Gmail/Google connectors (inert), Vercel. Details in `DEPENDENCIES.md`.

## 5. Deployment shape (as intended by the repo; unverified)

```
Browser -> Vercel (static + rewrites) -> backend.getlumina.pro (Caddy, auto-TLS)
        -> gunicorn 127.0.0.1:18800 (1 worker) -> SQLite
        -> /v1/live/<id>/frame -> 127.0.0.1:18801 (live gateway thread in browse service)
Host (one VPS): request-worker, lifecycle-worker, supervisor-native, cell-bridge (root),
                browse (root), tool-relay, model-proxy, cells-docker + gVisor cells,
                owner compose stack, dashboard, ops backup/monitor timers
```

Deployment target drift (L-01): 17 tracked files name an IONOS VPS (69.48.206.62); the owner's SSH config names a different Hostinger host for "Lumina production". Treat the whole topology as a design description until re-verified. Also: a single global running slot, one active cell per host (AG-004, BE-013).

## 6. Current phase status (from OP-014; production side unverified)

| Phases | State |
|---|---|
| 1-2 contract, platform foundation | Implemented |
| 3 accounts, 5 usage/admission, 14 operations | Implemented; phase 14 off-server backup still a launch blocker |
| 4 tenant provisioning | Partial; later native driver work superseded acceptance |
| 6 chat, 7 Telegram, 8 files, 9 live work | Build ready; Telegram real linking deferred (BE-007); uploads off by default |
| 10 native capabilities, 11 integrations | Built offline; activation blocked, connectors disconnected |
| 12 optimization | Adapters disabled in code; live JEV behavior contradicts docs (OP-015, M-02) |
| 13 billing | Implementation ready, Stripe not configured; test mode behind owner switch |
| 15 system acceptance | Partial: 21 PASS, 2 BLOCKED, 7 NOT_RUN |
| 16-19 optimization eval, private beta, launch, purchases | Not started |

Deferred items F1-F13 are in `phase-prompts/final_phase.md`. Work since 12 Oct went well beyond the phase numbering: Lumina web app, browse ladder, generative UI, native cell execution, safety menu (GH timeline E5-E11). "Phase N" has four meanings in this repo (GH-008).

## 7. Size numbers

| Metric | Value |
|---|---|
| Git commits on branch | 132 (107 dated 12-27 Oct) |
| Tracked files in `openclaw-project/` | 10,224 (platform 405; lumina 4,701; lumina-character 4,697; evidence 183) |
| Python LOC (tracked, excl. lumina) | about 45,800 |
| Platform tests | 73 `platform/tests/test_*.py` + 14 `accounts/test_*.py`; 1,163 `def test_` across platform, accounts, dashboard |
| Frontend tests | 42 `*.test.*` in `lumina/`, 2 in `browse/test/` |
| SQL migrations | 30 (+ 15 Django) |
| HTTP routes | 111 documented in `openapi.json` |
| Env vars | about 42-45 `AGENTAI_*` read; 8 documented (M-09) |
| `.git` | 351 MB; untracked clutter at root about 800 MB incl. `.claude/worktrees` 573 MB (M-03) |
| Largest files | `dashboard/app.py` 1,718; `chat_driver.py` 907; `browse/ladder.py` 701; `billing.py` 683 |

## 8. Top risks (master IDs; approx. 10-12 distinct High)

| ID | Summary |
|---|---|
| M-01 | Cancelling a waiting request leaks its budget reservation and queued task (BE-001 = AG-001) |
| M-02 | Customer browser screenshots go to api.typesafe.ai each JEV step; consent switch not wired (AG-002/003, IS-014) |
| M-03 | Untracked private key `ssk-key` not gitignored; plus about 800 MB other un-ignored material |
| M-04 | Per-IP rate limits are global behind Vercel to Caddy (BE-003, IS-009) |
| BE-002 | Authenticated SSE route can block the single sync gunicorn worker |
| FE-002 | Browser "asking" and vault UI missing from shipping app (conditional) |
| IS-002 | Root SSH by password documented (prod unverified) |
| ST-001 | CI runs about 20 of 73 platform test modules and nothing of the frontend (M-10) |
| M-06 | `lumina-character` is a tracked full fork of `lumina` (4,697 files, 61 MB assets) |
| M-08 | Three browser designs coexist; prod engine unknown |

Coverage gap, not a clean bill: backend notes "no IDOR found in routes read" but `gateway.py`, `events.py`, `artifacts.py`, `storage.py`, `genui/*`, `routing/*`, `ops/*` were not deep-audited.

## 9. Reading order for the other audit docs

1. This file, then `ARCHITECTURE.md` (layers, trust boundaries, diagrams).
2. `EXECUTION_FLOWS.md` (end-to-end hops with file:line, flaws per flow).
3. `FILE_MAP.md` (where things live, source vs generated vs evidence).
4. `DEPENDENCIES.md` (module graph, external services, declared-vs-used).
5. `CLAUDE.proposed.md` (rules for future AI sessions; not installed).
6. Per-scope raw findings in `_findings/` (backend, orchestration, frontend, infra_security, structure, history, outside_project) and `_findings/00_RECONCILIATION.md` (authoritative dedupe map and rules).
7. Earlier audit: `openclaw-project/docs/orchestration-audit/` (historical, pre-26-Oct; bannered) and `docs/architecture/native-execution.md` (current).
