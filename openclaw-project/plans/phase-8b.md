# Phase 8B — complete owner dashboard with live work viewer

Status log (keep at top; newest last). Interrupted sessions resume from here.

- [x] 2026-09-28 late: §1–§3 implemented locally and committed
      (`dashboard/app.py` v2, `static/`, `workread.mjs`,
      `test_dashboard.py` — 17 regression tests green, incl. two real bugs
      the tests caught: v1 dot-check in `validate()` would have rejected
      every v2 token (owner lockout), and the root-listing empty-rel
      rejection). §2 rules applied (CSP self-only, central redaction,
      fail-open unknowns, no unverified controls).
- [ ] §0 + §4 live portions + §5 deploy: **BLOCKED — VPS down**
      (SSH now TCP-timeout, not banner: host rebooted or offline; IONOS
      console restart may be needed). Resume exactly per §5 list; the
      one-item-at-a-time lesson from 2026-09-28 applies: never leave a
      `doctor --json` orphaned on this box.

## §0 Starting point (verify at deploy — BLOCKED on VPS recovery)

- Deployed `dashboard/app.py` must hash-match the repo (sha256 recorded in
  evidence at deploy).
- To verify with harmless reads before enabling the live viewer (never
  invent endpoints/fields):
  1. Gateway HTTP auth: resolve the Gateway credential server-side into
     `dashboard/gateway-token` (0600, never printed). Candidate paths:
     `secrets` CLI resolution of the `gateway.auth.token` SecretRef.
  2. `GET /sessions/{key}/history?includeTools=1&follow=1` (SSE) on
     127.0.0.1:18789 — probe with `curl --max-time 3`; record status, auth
     scope, and real response shape in `plans/phase-8b.md` §0 results.
  3. Browser-worker per-step recording: inspect a `p11-browser-check*`
     session transcript via the same endpoint.
  4. Jev decision log: `/home/node/.openclaw/jev-research/decisions.jsonl`
     (verified to exist once the middleware fires; empty today).
  5. LiteLLM spend: `LiteLLM_SpendLogs` (verified: `startTime`, `spend`,
     `key_alias` columns; per-session attribution NOT available → per-run
     cost shows where the runtime exposes it, else "unknown").
- The app implements **both** live transports with a config-selected
  backend, so deploy-time verification picks without code changes:
  `state/live-backend.json` `{"backend": "gateway-http"|"cli-audit"}`.
  `gateway-http` = SSE/poll of the documented history endpoint (needs the
  token file). `cli-audit` = polling `audit --json` + `sessions list --json`
  (both verified working on the pinned build during Phases 3/10). Anything
  the chosen backend does not expose renders as "unknown", never invented.
- Headroom at last read: ~1.7 GB mem available, 84 GB disk. Unit keeps
  MemoryMax=200M; SSE streams capped at 5 concurrent; per-stream buffer cap
  500 events.

## §1 Defect fixes (implemented in `dashboard/app.py` v2 + `test_dashboard.py`)

1. Dotted file names allowed (`index.html` browses); still reject `..`,
   hidden files, absolute paths, control/encoded traversal.
2. Containment via container-side fixed helper `workread.mjs`: opens the
   final path with `O_NOFOLLOW`, `fstat` size/type check on the descriptor,
   hard byte cap on read; every path component lstat-walked for symlinks.
   Fixed argv only — no client code reaches a shell. (Residual race on
   intermediate components documented; Phase 10 case retests.)
3. Sessions: random `token_urlsafe(32)` IDs, stored SHA-256-hashed server
   side; per-session logout (server-side revocation), rotation on login,
   idle expiry 2 h, absolute expiry 24 h, revoke-all wipes the store; audit
   written before a state change is reported.
4. Downloads: signature bound to session-hash + path + version
   (size:mtime) + expiry; **single-use** (used signatures stored and
   rejected on replay); wrong session rejected.
5. Truthful status: every observation keeps its capture timestamp; sandbox
   `unhealthy` containers mark the card `warn` (not "ok"); blank session
   update times render "unknown".

Regression tests: `dashboard/test_dashboard.py` (offline, temp STATE).

## §2 Architecture (implemented)

Browser ⇄ dashboard (stdlib HTTP + SSE) ⇄ fixed native operations
(`docker exec` argv / gateway HTTP with the token file / read-only sqlite
never exposed). No credential reaches the browser: the only browser-visible
secret is its own session cookie. Cancel: the pinned build exposes no
verified owner-scoped abort API to the dashboard, so no cancel route exists
(native approvals stay read-only in the dashboard with the Telegram/Control
UI path shown). Jev toggles flip the documented plugin config file with
value readback, audited. All rendered content is escaped text; strict CSP
(unchanged); central `redact()` (bearer tokens, api keys, cookies, typed
secrets) applied before render/log/audit.

## §3 Features (implemented)

Overview (+unhealthy sandbox marking, pending approvals count, Jev/Codex
spend lines with unknown-when-unknown, now-running strip), Live viewer
(session tree, SSE timeline with pause/cursor-resume/agent+tool filters, web
activity rendering incl. Brave queries, fetch results, Jev decisions,
INJECTION_ATTEMPT highlighting, critic verdicts, final answer + citations;
browser/codex views from the same transcript data), Files (fixed read-only),
Approvals (read-only), Schedules, Memory (read), Integrations, Costs, Audit.
Light/dark mode, responsive, keyboard-visible focus states. Loading/empty/
disconnected/stale/denied states on every data region.

## §4 Checks

`test_dashboard.py` covers §1 regressions + redaction + signature
replay/expiry + session lifecycle. Deploy-time live checks (origin checks,
SSE resume, the one ≤$0.25 paid researcher run, memory-under-limit) are
listed in §5 resume list.

## §5 Resume list (needs VPS)

1. Deploy: rsync `dashboard/` → server, write `workread.mjs` into the
   container work dir, restart unit, hash-match record.
2. §0 probes → set `state/live-backend.json`.
3. Run `test_dashboard.py` on the host; auth/live/browser-matrix checks.
4. One paid researcher run ≤ $0.25 to exercise the live viewer.
5. Evidence pack + evals case IDs (T10-DASH2-*) + phase-index status lines.
