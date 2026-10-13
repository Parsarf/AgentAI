# Product Phase 15 — system acceptance (existing-VPS serialized trial profile)

**Status (2026-10-13): PARTIAL.** Implementation ready; 21 live cases PASS on the final revision, 2 BLOCKED, 7 NOT_RUN. NOT_RUN and BLOCKED are not PASS. Evidence: [`evidence/product/phase-15/20261013T1954Z/`](../../evidence/product/phase-15/20261013T1954Z/manifest.json). Harness: `platform/deploy/p15_acceptance.py` (frozen suite; run on the server with `--runtime`).

## What passed (live, real Django stack, real assistant)
- **Isolation (API):** a second disposable account B could not read or change any of A's objects across 19 routes (conversations, messages, blocks, tasks, events, stream, requests, browse runs and screenshots, projects, files, bundle, artifact tickets and downloads); denials changed nothing in A; list endpoints showed only B's data; positive controls prove both accounts were genuinely signed in.
- **Boundary:** signed-out refusal on all customer routes, CSRF missing and foreign-origin refusal, bad Host refusal, customer refused on operator lifecycle routes, traversal/injection shapes refused, download tickets single-use and account-bound.
- **Budget:** 12 concurrent sends against a $0.06 cap never held more than the cap; no native/provider delivery for denied or waiting requests; cancelling released the reservation.
- **Runtime:** real send/history/completion through the isolated cell; a file written by the assistant became a versioned download; two quick requests ran one after the other; cancelling a running 90-second command stopped it within seconds and settled the reservation; hostile instructions inside a file were not followed (reply-level); ledger never under-charges (reported receipts ≤ provider spend ≤ all receipts).
- **Operations:** a manual backup run produced a complete verified set including customer files; monitor 20 ok / 1 warn (off-server backup) / 0 crit.
- **Cleanup:** account B removed (tombstone row only; audit rows are append-only).

## Defects found by this run and fixed
1. SSE stream / file views returned HTTP 500 instead of 404 on a cross-account denial → middleware now maps it to 404 and audits it (regression test added).
2. File preview with a malformed id returned HTTP 500 → 400 (regression test added).

## Not passed (kept with their IDs)
- **BLOCKED P15-TENANT-TWO-CELLS:** a second live cell needs operator enrollment in a private terminal. Blocks raising concurrency; the serialized trial profile is one account at a time. Phase 4 holds the earlier two-cell evidence; it is not re-proven on this revision.
- **BLOCKED P15-RESTORE-A:** restore drill needs the owner's off-server age key (RTO unmeasured). Off-server copy is final-phase item F1.
- **NOT_RUN:** live Stripe payment/cancel/refund (checkout is OFF by owner decision), Telegram (F5), integrations (F6), Claude Code board (F2), schedules (F9), real-browser a11y/mobile on the signed-in site, independent security review.

## Cost, unknowns, rollback
About $0.20 provider spend. Unknowns: outbound traffic during hostile-content cases; behaviour with two live cells. Rollback: previous app release via `release.py`; nothing in this phase changed data except the disposable account.
