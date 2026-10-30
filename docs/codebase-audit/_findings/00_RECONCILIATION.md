# Lead reconciliation notes (authoritative over the per-scope files)

Audit date 2026-10-29. Branch product-phases-6-11, HEAD 03662de + uncommitted tool_origin/tool_relay/cell_bridge/cell_config work (in progress, not judged). Scan root is /Users/parsa/AgentAI (git root); project is openclaw-project/. Deliverables live in /Users/parsa/AgentAI/docs/codebase-audit/.

## Per-scope files (source of every finding; keep their IDs)
backend.md (BE-001..024), orchestration.md (AG-001..022), frontend.md (FE-001..020), infra_security.md (IS-001..025), structure.md (ST-001..021), history.md (GH-001..018), outside_project.md (OP-001..018).

## Duplicate findings: one MASTER entry, cite all IDs
- M-01 Reservation/task leak when a WAITING request is cancelled (also revoked-author, unfunded paths): BE-001 = AG-001. Lead verified request_queue.py:107-115 `cancel` updates only customer_requests. HIGH.
- M-02 Customer browser screenshots (base64 JPEG) sent to api.typesafe.ai every JEV step; scrub is text-only; consent switch `browser_optimization` + OptimizationGate not wired to the live path: AG-002 = IS-014, plus AG-003. Lead verified ladder.py:333,397 and loop.py:208-216. HIGH. Owner priority = customer privacy.
- M-03 Private key `ssk-key` untracked and NOT gitignored at repo root, mode 0600, ed25519, never in history (history.md/outside agent verified); also ~800 MB other untracked, un-ignored material (.claude/worktrees 573M, zips, tarballs, jev-*, lumina-cost-audit with owner browsing request logs): IS-001 = OP-001 = ST-003 = GH-009; OP-002/003/013, ST-004. Lead verified `git check-ignore -v ssk-key` returns nothing. HIGH. NOTE: the infra investigator printed only the 40-byte PEM header of ssk-key (no key material); no one read the key body.
- M-04 Shared client IP behind Vercel -> Caddy overwrites header, so per-IP limits are global: BE-003 = IS-009. MEDIUM-HIGH, prod unverified.
- M-05 Orphaned product modules (durable, memory, schedules, watchers, skills, optimization, policy_check, genui/intent, ops/rotation, lifecycle/broker): BE-014 = AG-009 (= AG-003 for optimization). Class C/G, NOT deletion.
- M-06 lumina-character is a tracked full fork of lumina (4,697 tracked files, 61 MB assets, unref'd by deploy/CI, untracked node_modules symlink): FE-001 = ST-002 = GH-012 (= GH-002 for the symlink). Product decision (C), preserve (G).
- M-07 Three generative-UI generations: FE-004 = GH-007 (+ FE-005 registry duplicated front/back).
- M-08 Browser stack: runner.mjs (host Docker, default) vs native_runner.py (rollout-gated) vs uncommitted tool_origin: AG-006/AG-010/AG-013-ish + GH-004 + IS-012(native browser). Which engine runs in prod UNVERIFIED.
- M-09 Env var sprawl: BE-015 = IS-007 (8 documented / ~42-45 read; 23 undocumented; 2 documented-but-unread).
- M-10 CI covers only part of the tests and nothing of the frontend: ST-001 = OP-009. Lead could not exactly reconcile the count (ST says 20 of 73 test_*.py modules, OP says 21); say "about 20 of 73" and cite both.
- M-11 Doc drift on ServiceRouter: AG-016 = GH-003 (ServiceRouter + routing/services.py + 2 tests deleted in 5db9636, a commit titled for a UI change; CLAUDE.local.md and several docs still describe it as live). Lead verified no ServiceRouter in code and routing/services.py absent.
- M-12 Logging/observability: BE-010 = IS-008 (django logger -> NullHandler; privacy-motivated) + ST-011 (7 modules use logging, 126 `except Exception`).

## NEW lead findings (not in any scope file)
- L-01 DEPLOYMENT TARGET DRIFT (High, doc/ops): 17 tracked files name the IONOS VPS 69.48.206.62 (README/RUNBOOK/SERVER_DEPLOYMENT/OPERATIONS/bin/ssh-server). The owner's ~/.ssh/config has `Host lumina` -> Hostinger VPS 179.236.71.203 (user root, key ~/.ssh/id_ed25519) commented "Lumina production server". No repo doc mentions this host. 69.48.206.62:22 timed out from the audit machine (2026-10-29); `ssk-key` is REJECTED by 179.236.71.203 (publickey,password offered). getlumina.pro resolves to 216.198.79.1 (Vercel front; the API origin backend.getlumina.pro was not resolved). Conclusion: either production moved, or the repo's ops runbook targets a dead/old server. All VPS-dependent findings stay UNVERIFIED. Also means IS-002 (password SSH to root, documented from .env) and the whole "Hostinger vs IONOS" topology must be re-verified.
- L-02 `ssk-key.pub` fingerprint SHA256:NItwjEf8... differs from ~/.ssh/id_ed25519.pub (SHA256:Rnb3Iaou...). ssk-key authorizes nothing on the current server as far as tested. Purpose unknown (open question).
- L-03 Production SSH access was attempted read-only (hostname/date/uptime only), twice, both failed; no command ran on any server.

## Conflicts resolved
- ST says SonarQube/other tooling absent; OP says Sonar report exists (2026-10-13: 28 vuln, 52 bugs, 709 smells; 14 spot-checks all still present). Both true: no linters installed locally; report is an external export.
- infra said repo has no `docs/release/RELEASE_NOTES.md`/`docs/SERVER_DEPLOYMENT.md`; real paths are openclaw-project/RELEASE_NOTES.md, SERVER_DEPLOYMENT.md. CLAUDE.local.md says evidence/ is "not indexed" but 183 files are tracked (IS-018).
- Backend says "no IDOR found in routes read", with gaps: gateway.py, events.py, artifacts.py, storage.py, genui/*, routing/*, ops/* not deep-audited. Report that as a coverage gap, not as a clean bill.
- Frontend FE-002 (question/vault UI missing) depends on whether the backend can still emit an `asking` state; backend/orchestration confirm the routes + `ASK_SECONDS` exist -> treat as HIGH-impact but conditional (MEDIUM confidence) until the VPS or a test confirms the state is reachable.

## Severity roll-up (as written by investigators; do not recount precisely, say "approx.")
High: BE-001/002/003, AG-001/002/003, FE-002, IS-001/002/014, ST-001/002/003 (+GH-003/004/009, OP-001). After dedupe ~10-12 distinct High.

## Rules for the writers
- Production is UNVERIFIED. Never state a production fact as true.
- No secret values. Key names only. Do not read ssk-key.
- Write ONLY the files assigned to you under /Users/parsa/AgentAI/docs/codebase-audit/. Do not touch any other file in the repo.
- Cite master IDs and source IDs, and keep file:line citations from the findings (do not invent new line numbers; if you need one, check the source read-only).
- Be concise but complete; tables over prose. Include the class A–G recommendation labels where relevant.
- Mark the uncommitted tool_origin/tool_relay work as IN-PROGRESS.
