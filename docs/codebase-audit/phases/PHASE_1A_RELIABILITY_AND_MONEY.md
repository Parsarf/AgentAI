# Phase 1A: reliability and money-path fixes (implementation specs)

Purpose. Concrete, self-contained specs for the Phase 1 items that protect the customer allowance and the single web worker: the reservation/task leak (M-01 = BE-001 = AG-001, plus BE-006), the webhook body cap (BE-004 / ST-018), the missing billing reconcile timer (BE-005), the park limit and the fail-open spend guard (AG-005, AG-007), the SSE route that can starve the one gunicorn worker (BE-002), the duplicate upload-size setting and per-endpoint caps (BG-011 / BE-021), and six smaller correctness fixes (BE-017, BG-014, BG-013, BG-015, BG-006, BG-004). Everything below was re-read against the working tree at HEAD `03662de` on 2026-10-29; every `path:line` is current. Owner priorities that shape every choice: customer privacy first, no new per-task limits (memory: privacy over task guardrails), fail-closed bookkeeping repairs are allowed, preserve unfinished functionality.

All paths are relative to `/Users/parsa/AgentAI/openclaw-project/platform/` unless they start with `/`.

## Task order and dependency graph

Money path = touches `budget.py`, `request_queue.py` finish/claim/cancel, `chat_driver._close`/spend guard, or anything that decides what an allowance is charged. Do these with extra care and never in the same commit as a non-money task.

| Order | Task | Findings | Money path | Depends on | Risk |
|---|---|---|---|---|---|
| 1 | P1-7 webhook body cap | BE-004, ST-018 | no | none | low |
| 2 | P1-6 upload cap duplicate + per-endpoint caps | BG-011, BE-021 | no | P1-7 (same function) | low-medium |
| 3 | P1-12 isolate `/v1/tasks/<id>/stream` | BE-002 | no | none | low |
| 4 | P1-8 billing reconcile timer | BE-005 | no (reads Stripe, repairs access) | none; owner install step | low |
| 5 | P1-1 reservation/task leak, sweep, admission ordering | M-01 (BE-001, AG-001), BE-006 | **YES** | none (blocks P1-9 rebase and AG-004) | medium-high |
| 6 | P1-9 park limit and spend guard | AG-005, AG-007 | **YES** (settle path, spend stop) | P1-1 merged first (same files) | medium |
| 7 | P1-10a BG-015 `task_state` | BG-015 | no | none | none |
| 8 | P1-10b BG-006 newest-first listings | BG-006 | no | none | low-medium |
| 9 | P1-10c BG-004 inline asset cap | BG-004 | no | none | low |
| 10 | P1-10d BG-013 capture isolation | BG-013 | no | none | low |
| 11 | P1-10e BG-014 stuck plan phase | BG-014 | indirect (calls `chat._spawn`) | P1-1 (hold ordering in `_spawn`) | low-medium |
| 12 | P1-10f BE-017 `chat_send` task cap | BE-017 | no, but policy | GATE (conflicts with "no new limits") | n/a |

```
P1-7 -> P1-6                 (middleware.py)
P1-12, P1-8                  (independent)
P1-1 (1a ledger -> 1b queue -> 1c sweep+worker -> 1d hold/migration) -> P1-9 -> AG-004 stub test
P1-1 -> P1-10e
```

Commit one task (or one sub-step of P1-1) per commit. Do not deploy anything: production changes are owner-approved text in the "Owner steps" sections.

## Pre-flight checklist (do once, before the first task)

1. `cd /Users/parsa/AgentAI && git status --short` and `git branch --show-current`. Expected branch `product-phases-6-11`. The tree is NOT clean: the tool-origin work is modified/untracked (`agentai_platform/tool_relay.py`, `lifecycle/cell_bridge.py`, `lifecycle/cell_config.py`, `lifecycle/tool_origin.py`, `tool_origin_install.py`, `tool_origin_plugin/`, `tests/e2e/*`, `tests/test_browser_tool.py`, `tests/test_tool_origin.py`, `accounts/management/commands/tool_relay.py`). Those files are Phase 0 territory: do not edit, stage, revert or commit them. Stage only the files named in your task (`git add <path>`; never `git add -A`). If Phase 0 has not committed them yet, that is fine; your work is disjoint from them.
2. Create a working branch from the current branch: `git switch -c phase1a-reliability-and-money`.
3. Baseline test run (record the failures that already exist, so you can tell yours apart). From `/Users/parsa/AgentAI/openclaw-project/platform`:
   ```
   .venv/bin/python -m unittest tests.test_request_queue tests.test_budget tests.test_chat tests.test_native_run tests.test_request_worker tests.test_events tests.test_files tests.test_ops_restore
   .venv/bin/python manage.py test accounts --verbosity 1
   ```
   Suites that skip or need extra tools: `tests/e2e/*` skip unless the pinned OpenClaw package exists; `tests/test_native_browser.py` needs Chrome; neither is required here. `tests.test_native_run` and `tests.test_request_worker` are NOT in the CI list (`/Users/parsa/AgentAI/.github/workflows/*.yml`, line 27 of the unit step); run them by hand, and add them to CI as part of M-10, not here.
4. Confirm `rg -n "task_reservations|UPDATE tasks" agentai_platform accounts --glob '!tests'` still shows only the writers named in P1-1 (budget.py, request_queue.py, chat_driver.py:138/796, ops/restore.py:146/168). If a new writer appeared, stop and read it first.

---

# P1-1: Reservation and task leak (M-01) and admission ordering (BE-006)

- **Findings**: M-01 = BE-001 = AG-001 (High, money), BE-006 (race). **Finding check**: re-verified HIGH for the code defect. Corrections:
  - Line numbers have moved. Current: `RequestQueue.cancel` `request_queue.py:107-115` (waiting branch is line 112); revoked-author branch in `claim` `request_queue.py:162-165`; `worker._tick` unfunded branch `request_worker.py:56-63`; `ChatService.send` `chat.py:203-262` (admit at 253-259, cancel on failure at 259), `ChatService._admit` `chat.py:180-201`, `_spawn` `chat.py:337-351`, `cancel` `chat.py:465`; `ChatDriver._close` `chat_driver.py:785-799`; `ops/restore.py:166-169` (closes reservations with a raw `UPDATE ... SET state='settled'`, no `usage_entries` rows).
  - The "unfunded failure" path does not itself leak: it runs only when there is NO active reservation, so there is nothing to release, and a missing reservation normally means a missing `tasks` row (budget.admit inserts both atomically, `budget.py:85-88`). The real leak on that path is BE-006: a worker claims the just-submitted request before `ledger.admit` commits, fails it as unfunded, and then `admit` succeeds and creates an active reservation plus a `queued` task for an already-finished request. The fix for that is ordering plus an admit-side refusal, not a release.
  - Production is latent, not affected today (PRODUCTION_VERIFICATION_2026-10-29.md: 0 active reservations, 0 queued tasks, 0 waiting requests). So this is a correctness repair with no urgency to deploy mid-run.
- **Goal / user-visible effect**: Pressing Stop on a task that has not started (or an author revoked while waiting) gives the reserved allowance back at once and closes the task row, in the same transaction. Three cancels no longer lock the account into "queue full"; the plan limit and the service-wide allocation stop leaking; the cell can sleep again. A request can never be failed as "not funded" while its funding is being written.
- **Depends on / blocks**: none / blocks P1-9 (same files; rebase P1-9 on this) and P1-10e. **GATE**: one owner approval, because step 1d adds a migration (0031, additive `ALTER TABLE ... ADD COLUMN`) that runs on the production DB at the next deploy. Question: "Approve migration `0031_request_admission_hold.sql` (adds `customer_requests.admitting`, default 0) and the ledger refactor, to be released together at a quiet time? Alternative without a migration: skip step 1d and rely on step 1a (admit refuses a closed request) plus the sweep; the cost is that a request can still be failed with 'could not be funded, send again' if a worker happens to claim it in the few milliseconds before admission commits." Steps 1a-1c need no gate beyond normal deploy approval.
- **Files to read first**: `agentai_platform/budget.py` (whole), `request_queue.py` (whole), `chat.py:180-262,337-351,465-480`, `chat_driver.py:120-160,785-835`, `request_worker.py` (whole), `accounts/management/commands/request_worker.py`, `migrations/0003_budget_admission.sql`, `migrations/0022_task_control.sql`, `ops/restore.py:140-170`, `tests/test_budget.py`, `tests/test_request_queue.py`, `tests/test_chat.py:25-100,134-142`, `tests/test_native_run.py:1-60`.
- **Files to change**: `agentai_platform/budget.py` (settle ~117-133, admit ~61-91), `agentai_platform/request_queue.py` (`__init__` 57-60, `submit` 61-86, `_ahead` 94-97, `cancel` 107-115, `claim` 147-173, `finish` 195-212, new `release_hold`, new `sweep`), `agentai_platform/chat.py` (`send` 203-262, `_spawn` 337-351), `agentai_platform/request_worker.py` (`__init__`, `tick`), `accounts/management/commands/request_worker.py` (idle branch), new `migrations/0031_request_admission_hold.sql`. Tests listed below.

### Current behaviour (quotes)

- `request_queue.py:112`: `if row['state']=='waiting':c.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=? AND id=?",(principal.account_id,request))` — nothing touches `task_reservations` or `tasks`.
- `request_queue.py:164`: `c.execute("UPDATE customer_requests SET state='cancelled' WHERE account_id=? AND id=?",(row['account_id'],row['id']))` (revoked author) — same omission.
- `budget.py:79-80`: `queued=con.execute("SELECT count(*) FROM tasks WHERE account_id=? AND state='queued'",...)`; `if queued>=limits['max_queued_tasks'] ...: raise BudgetDenied('queue full')` — counts the leaked `queued` rows.
- `budget.py:55-57`: `_holds` sums `task_reservations` in `('active','uncertain')` — counts the leaked reservations toward period, daily and service allocation.
- `chat_driver.py:790-792` (`_close`): `self.ledger.settle(account=..., task=..., effects_quiesced=True, all_routes_reconciled=True)` is the ONLY settler besides restore.
- `chat.py:233-259` (`send`): `queue.submit(...)` commits a claimable `waiting` row, then the transcript row, then `self.ledger.admit(...)` in a separate transaction; on `admit` failure `self.queue.cancel(...)`.
- `request_worker.py:56-63`: `funded = ... state='active'`; `if not funded: ... self.queue.finish(claim, RequestReceipt(... 'failed', 'This request could not be funded or started...'))`.

### Ledger semantics to reuse (read before coding)

`BudgetLedger.settle` (`budget.py:117-133`) on the completed path does, in one transaction: `spent = sum(provider_receipts)`; `UPDATE task_reservations SET state='settled'`; append `usage_entries` kind `reconciled` (=spent) and kind `released` (= `max(0, amount-spent) - prior_released`), both with reference `'settle-'+uuid`. `usage_entries` is append-only (triggers in 0001). A second `settle` returns False because the state is already `settled`/`cancelled` (line 121): that is the idempotency guard and it must be preserved. `provider_receipts` for a request that never ran is empty, so a release books `reconciled 0`, `released <amount>`: exactly what the audit trail should show for a request that never spent. Do NOT write `state='cancelled'` on the reservation (that value exists in the CHECK but `budget.py` only reads it); use `settled`, as settle and restore do.

### Change

**Step 1a. Ledger: make the settle body callable inside an existing transaction, and refuse admission for a closed request** (`agentai_platform/budget.py`).

```diff
     def settle(self, *, account, task, effects_quiesced=False, all_routes_reconciled=False):
         with self.transactions.transaction() as con:
             row=con.execute('SELECT * FROM task_reservations WHERE account_id=? AND task_id=?',(account,task)).fetchone()
             if not row:raise NotFound()
             if row['state'] in {'settled','cancelled'}:return False
             if effects_quiesced is not True or all_routes_reconciled is not True:
                 con.execute("UPDATE task_reservations SET state='uncertain' WHERE account_id=? AND task_id=?",(account,task))
                 self.transactions._audit(con,account,'receipt-adapter',task,'budget_settle','uncertain')
                 return False
-            spent=con.execute('SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE account_id=? AND task_id=?',(account,task)).fetchone()[0]
-            con.execute("UPDATE task_reservations SET state='settled' WHERE account_id=? AND task_id=?",(account,task))
-            prior_released=...
-            reference='settle-'+uuid.uuid4().hex
-            self._entry(con,account,task,'reconciled',spent,reference)
-            self._entry(con,account,task,'released',max(0,row['amount_microusd']-spent)-prior_released,reference)
-            self.transactions._audit(con,account,'receipt-adapter',task,'budget_settle','completed')
-            return True
+            return self.settle_in(con,row)
+
+    def settle_in(self, con, row):
+        """The completed-settlement writes, inside the caller's write transaction (settle(), and the request queue's cancel/revoke/sweep paths)."""
+        account,task=row['account_id'],row['task_id']
+        (the five moved lines above, unchanged, ending in `return True`)
+
+    def release_in(self, con, account, task):
+        """Give back the reservation of a request that never ran or has fully drained. True when this call released one; False when there is none or it is already closed.
+        An 'uncertain' reservation is left for settle()/the operator: receipts may be unreconciled."""
+        row=con.execute('SELECT * FROM task_reservations WHERE account_id=? AND task_id=?',(account,task)).fetchone()
+        if not row or row['state']!='active':return False
+        return self.settle_in(con,row)
```

Refuse a late admit (closes the BE-006 leak even when step 1d is not shipped). In `admit`, directly after the idempotent-replay block (`budget.py:72-74`, so a genuine replay still returns the existing reservation) and before `_limits`:

```diff
             if existing:
                 if existing['request_hash']!=digest:raise Conflict('allocation payload changed')
                 return dict(existing)
+            if con.execute("SELECT 1 FROM customer_requests WHERE account_id=? AND id=? AND state IN ('completed','failed','cancelled')",(account,task)).fetchone():
+                raise Conflict('request already closed')      # a worker may have finished it while admission was pending: never fund a closed request
             entitlement,limits=self._limits(con,account)
```
(`tests/test_budget.py` admits task ids that have no `customer_requests` row; the `SELECT` simply finds nothing, so those tests are unaffected. `Conflict` is already imported in `budget.py`.) `ChatService.send` already turns an `admit` exception into `queue.cancel` + re-raise, so a refused late admit surfaces as a 409 `request_conflict` in `accounts/chat.py` (existing `except Conflict`).

**Step 1b. Queue: release and close in the same transaction** (`agentai_platform/request_queue.py`).

```diff
+from .budget import BudgetLedger
 ...
     def __init__(self,store,clock=time.time,*,require_cell=False):
         self.require_cell=require_cell
         self.store=store;self.clock=clock;self.coordinator=Coordinator(store,clock=clock)
+        self.ledger=BudgetLedger(store,clock=clock)        # only release_in/settle_in are used here: no service limit needed
+    def _close_unrun(self,c,account,request,task_state):
+        """A request that ends without ever running (cancelled while waiting, author revoked): give its allowance back and close the task row, inside the caller's transaction."""
+        released=self.ledger.release_in(c,account,request)
+        c.execute("UPDATE tasks SET state=? WHERE account_id=? AND id=? AND state IN ('queued','paused')",(task_state,account,request))
+        return released
```
(`budget.py` does not import `request_queue`, so there is no import cycle; it imports `agentai_platform.lifecycle.coordinator` as `request_queue.py` already does.)

```diff
     def cancel(self,principal,request):
         ...
-            if row['state']=='waiting':c.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=? AND id=?",(principal.account_id,request))
+            if row['state']=='waiting':
+                c.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1,admitting=0 WHERE account_id=? AND id=?",(principal.account_id,request))
+                self._close_unrun(c,principal.account_id,request,'cancelled')
             elif row['state'] in {'starting','running','uncertain'}:c.execute('UPDATE customer_requests SET cancel_requested=1 ...
```
(`admitting=0` only once step 1d exists; before that, omit it.) The `starting/running/uncertain` branch is deliberately unchanged: a claimed request is owned by the driver, which settles in `_close`; releasing here would race the live run. A request already `completed/failed/cancelled` falls through both branches (no-op), so a double Stop is idempotent.

```diff
                 if authorized:break
                 c.execute("UPDATE customer_requests SET state='cancelled' WHERE account_id=? AND id=?",(row['account_id'],row['id']))
+                self._close_unrun(c,row['account_id'],row['id'],'cancelled')
                 self.coordinator._audit(c,row['account_id'],'worker','request_revoked'...)
```
`release_in` does not call `store._authorize`, so it works for a revoked/suspended account (do not add an authorize call).

Safety net in `finish` (covers the unfunded failure, a deferred request that was never given a tasks update, and any future path): in `finish`, right after the `UPDATE customer_requests ... closing=1` at `request_queue.py:208-209`:

```diff
             c.execute('UPDATE customer_requests SET state=?,result=?,...closing=1 WHERE ...')
+            c.execute("UPDATE tasks SET state=? WHERE account_id=? AND id=? AND state IN ('queued','running','waiting_for_approval','paused')",
+                      ({'completed':'completed','failed':'failed','cancelled':'cancelled'}[receipt.state],claim.account_id,claim.request_id))
             c.execute('DELETE FROM request_slot WHERE ...')
```
On the normal path `ChatDriver._close` has already set the final task state (`chat_driver.py:796`, committed before `finish`), so this `WHERE` matches nothing and the driver's finer mapping (`blocked`, `completed` for `partial`) is untouched. It only acts when a task row was left non-terminal.

Unfunded branch in the worker (`request_worker.py:56-63`) needs no code change after the above, except to stop an `uncertain` reservation from wedging the slot: `finish` raises `Conflict('usage must reconcile before handoff')` when a reservation is `uncertain` (request_queue.py:207) and `_tick` has no handler, so the request stays `starting` and the exception repeats each tick until the lease lapses. Make the funded check include both states and let the driver deal with it:

```diff
-            funded = con.execute("SELECT 1 FROM task_reservations WHERE account_id=? AND task_id=? AND state='active'", ...
+            funded = con.execute("SELECT 1 FROM task_reservations WHERE account_id=? AND task_id=? AND state IN ('active','uncertain')", ...
```
Then an `uncertain` reservation goes to `driver.execute`, whose `_admit` (`chat_driver.py:120-131`) raises `Conflict('task not admitted')` for any non-`active` state, which is caught by `_run`'s `except Exception: self.queue.uncertain(claim); raise`, leaving the request recoverable by `_settle_uncertain` (and abandoned after 1800 s with `driver.abandon`, which settles). That is the existing, tested recovery path; it is strictly better than a tight Conflict loop. Add the one-line change and its test (below); if the reviewer prefers not to touch it, record it as a known edge in the commit and skip.

**Step 1c. Sweep (repair for anything that still leaks, including rows leaked before this fix and restore residue)** in `RequestQueue`:

```python
    def sweep(self,*,hold_grace=300,limit=50):
        """Idempotent repair, safe to run at any time and from any process: (1) an admission hold nobody released (a crash between submit and admit) is released so the worker
        fails the request as unfunded, (2) an active reservation whose request is already over is given back, (3) a task row still queued/paused for an over request is closed.
        Uncertain reservations are never touched here (they mean unreconciled spend)."""
        now=int(self.clock());report={'holds_released':0,'released':0,'tasks_closed':0}
        with self.coordinator.transaction() as c:
            report['holds_released']=c.execute("UPDATE customer_requests SET admitting=0 WHERE admitting=1 AND state='waiting' AND created_epoch<=?",(now-hold_grace,)).rowcount
            rows=c.execute("""SELECT r.account_id,r.id FROM customer_requests r JOIN task_reservations s ON s.account_id=r.account_id AND s.task_id=r.id
                WHERE r.state IN ('completed','failed','cancelled') AND s.state='active' ORDER BY r.sequence LIMIT ?""",(limit,)).fetchall()
            for r in rows:
                if self.ledger.release_in(c,r['account_id'],r['id']):
                    report['released']+=1
                    self.coordinator._audit(c,r['account_id'],'worker',r['id'],'reservation_sweep','completed')
            report['tasks_closed']=c.execute("""UPDATE tasks SET state=(SELECT CASE r.state WHEN 'completed' THEN 'completed' WHEN 'failed' THEN 'failed' ELSE 'cancelled' END
                    FROM customer_requests r WHERE r.account_id=tasks.account_id AND r.id=tasks.id)
                WHERE state IN ('queued','paused') AND EXISTS (SELECT 1 FROM customer_requests r WHERE r.account_id=tasks.account_id AND r.id=tasks.id AND r.state IN ('completed','failed','cancelled'))""").rowcount
        return report
```
Why it cannot double-settle or race a live run: it only looks at requests already in a terminal state (a live request is `waiting/starting/running/uncertain`), it runs inside `BEGIN IMMEDIATE`, and `release_in` skips anything not `active`. The driver settles BEFORE `finish` marks the request terminal (`_close` then `queue.finish`), and `finish` refuses to close while the reservation is `active/uncertain`, so a terminal request with an active reservation can only be a leak. Reservations with no `customer_requests` row at all (other producers such as optimization or tool relay) are not matched by the `JOIN` and are never touched.

Run it from the worker, throttled, and also while execution is off:

```diff
 class RequestWorker:
-    def __init__(self, queue, driver, capacity, *, owner='request-worker', lease_seconds=120, clock=time.time, abandon_after=1800, shadow=None, runner=None, goals=None):
+    def __init__(self, queue, driver, capacity, *, owner='request-worker', lease_seconds=120, clock=time.time, abandon_after=1800, shadow=None, runner=None, goals=None, sweep_every=60):
         ...
+        self.sweep_every, self._swept = sweep_every, None
+    def sweep_due(self):
+        """Startup and every `sweep_every` seconds: repair reservations/tasks left behind by a request that ended without running. Never breaks request handling."""
+        now = self.clock()
+        if self._swept is not None and now - self._swept < self.sweep_every:
+            return None
+        self._swept = now
+        try:
+            done = self.queue.sweep()
+        except Exception:
+            return None
+        return {'swept': done} if any(done.values()) else None
     def tick(self):
         report = self._tick()
+        swept = self.sweep_due()
+        if swept:
+            report = {**report, **swept}
```
`accounts/management/commands/request_worker.py` loop: in the `else` that reports `'customer_execution is off'`, call `worker.sweep_due()` so the repair also runs while the owner switch is off (a leak must not wait for execution to be turned on). Keep the existing print rule (counts only).

**Step 1d. BE-006 ordering: hold the request until admission commits** (migration + queue + chat).

`migrations/0031_request_admission_hold.sql`:
```sql
-- A request is held (never claimed) from submit until its budget admission has committed, so a worker cannot fail it as unfunded while its funding is being written (BE-006).
ALTER TABLE customer_requests ADD COLUMN admitting INTEGER NOT NULL DEFAULT 0 CHECK(admitting IN (0,1));
```
(Additive, defaulted; `ops/restore.py` copies only columns common to backup and live, so old backups restore fine. `tests/test_foundation.py:50` counts migration files against `schema_migrations`, so it stays consistent automatically.)

`request_queue.py`:
```diff
-    def submit(self,principal,*,message,key,conversation_id=None,intent='chat',context=None,goal_mode=False,continues=None):
+    def submit(self,principal,*,message,key,conversation_id=None,intent='chat',context=None,goal_mode=False,continues=None,hold=False):
     ...
-            c.execute('''INSERT INTO customer_requests(account_id,id,...,goal_mode,continues)
-                VALUES (?,?,?,?,?,?,?,?,'waiting',?,?,?,?,?)''',(...))
+            c.execute('''INSERT INTO customer_requests(account_id,id,...,goal_mode,continues,admitting)
+                VALUES (?,?,?,?,?,?,?,?,'waiting',?,?,?,?,?,?)''',(...,continues,1 if hold else 0))
```
```diff
     def _ahead(c,row):
-        if row['state']!='waiting' or row['paused']:return None
+        if row['state']!='waiting' or row['paused'] or row['admitting']:return None
         busy=...
-        return busy+c.execute("SELECT count(*) FROM customer_requests WHERE state='waiting' AND paused=0 AND sequence<?",(row['sequence'],)).fetchone()[0]
+        return busy+c.execute("SELECT count(*) FROM customer_requests WHERE state='waiting' AND paused=0 AND admitting=0 AND sequence<?",(row['sequence'],)).fetchone()[0]
```
```diff
                 row=c.execute("""SELECT * FROM customer_requests r WHERE state='waiting' AND paused=0 AND NOT EXISTS
-                    (SELECT 1 FROM customer_requests p ...) ORDER BY sequence LIMIT 1""").fetchone()
+                    (SELECT 1 FROM customer_requests p ...) ORDER BY sequence LIMIT 1""").fetchone()
```
Edit the first line of that SELECT to `WHERE state='waiting' AND paused=0 AND admitting=0 AND NOT EXISTS`. (Claim already ignores `paused`; `admitting` is a second, separate flag precisely so a customer Pause/Resume can never clear it: `_hold` only writes `paused`.)

```python
    def release_hold(self,principal,request):
        """Admission has committed (or the route is unpriced): the request may now be claimed. Idempotent; a customer's own Pause is untouched (separate flag)."""
        with self.coordinator.transaction() as c:
            self.store._authorize(c,principal)
            c.execute("UPDATE customer_requests SET admitting=0 WHERE account_id=? AND id=? AND admitting=1",(principal.account_id,request))
```
`chat.py`: in `send` pass `hold=True` to `queue.submit` (line 233) and release at every non-exception exit; in `_spawn` (line 339) the same.

```diff
-        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id,
-                                   intent=..., context=context, goal_mode=goal)
+        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id,
+                                   intent=..., context=context, goal_mode=goal, hold=True)
         ...
         try:
             amount, price_version = self.pricer.reservation(message)
         except CapabilityUnavailable:
+            self.queue.release_hold(principal, result['id'])        # unpriced route: unchanged behaviour (waits unfunded, the worker fails it clearly)
             return {**result, ... 'admission': 'route_unconfigured', ...}
         try:
             self.ledger.admit(...)
         except Exception:
             self.queue.cancel(principal, result['id'])
             raise
+        self.queue.release_hold(principal, result['id'])
         self._announce_queued(principal.account_id, result['id'])
```
`ChatService._admit` (used by `_spawn`, `chat.py:180-201`) returns early at the `budget_on` False and `CapabilityUnavailable` branches; release in `_spawn` after `_admit` returns (both branches reach the line `amount, price_version, _project = self._admit(...)` at 345), i.e. add `self.queue.release_hold(principal, result['id'])` immediately after that call. Replays are safe: a repeated `send` with the same key returns the existing request (submit's replay branch ignores `hold`), runs `admit` (idempotent by key) and `release_hold` (idempotent), which also repairs a request whose first attempt crashed before releasing. The sweep releases a hold older than 300 s as the last resort, after which the worker fails the request with the existing "send it again" message (nothing ran, nothing charged).

Visibility note: a held request counts toward the 3-waiting queue limit (`submit` counts `state='waiting'`) and shows as `waiting`, not paused, for the few milliseconds; `_ahead` hides its position while held.

### Tests to add or update

Test harnesses already exist; reuse them (`tests/test_chat.py` `ChatChecks` with `FixedRoute(500)` and `max_queued_tasks=3`; `tests/test_budget.py` `BudgetChecks`; `tests/test_request_queue.py` `SerialQueueChecks`; `tests/test_native_run.py` `Base` with a real worker).

`tests/test_chat.py` (class `ChatChecks`; uses `self.send`, `self.rows`, `self.queue`, `self.service`, `self.ledger`, `CAPACITY`):

1. `test_cancel_waiting_releases_reservation_and_closes_task` — `r=self.send(key='k1')`; before: `self.ledger.summary(self.a)['held_microusd']==500`; `self.service.cancel(self.a,r['id'])`; assert `held_microusd==0`; `task_reservations.state=='settled'`; `tasks.state=='cancelled'`; `usage_entries` kinds for the task in insertion order == `['reserved','reconciled','released']` with amounts `[500,0,500]` (query `ORDER BY rowid`). Fails today: held stays 500, task stays `queued`.
2. `test_three_cancelled_waiting_tasks_do_not_fill_the_queue` — `ids=[self.send(key=f'k{i}')['id'] for i in range(3)]`; cancel all three; `self.send(key='k4')` must NOT raise `BudgetDenied` and must return `execution_enabled True`. Fails today with `BudgetDenied('queue full')` because three `queued` tasks remain.
3. `test_double_cancel_and_cancel_after_close_are_noops` — cancel twice; `usage_entries` still has exactly one `released` row; reservation `settled`.
4. `test_cancel_then_claim_race` — (a) cancel first: `self.service.cancel(...)`; `self.queue.claim(owner='w',capacity=CAPACITY)` is None; reservation settled. (b) claim first: new request; `claim=self.queue.claim(...)`; then `self.service.cancel(...)` returns state `starting` with `cancel_requested=1`; assert the reservation is STILL `active` and the task still `queued` (the driver owns it), then settle via the driver path (`self.ledger.settle(account='a',task=id,effects_quiesced=True,all_routes_reconciled=True)` returns True, second call returns False) and assert exactly one `released` entry. This pins "never release a claimed request from cancel".
5. `test_revoked_author_waiting_request_is_closed_and_released` — `r=self.send()`; `UPDATE memberships SET status='revoked' WHERE account_id='a'`; `self.queue.claim(owner='w',capacity=CAPACITY)` is None; request `cancelled`, reservation `settled`, task `cancelled`, audit has `lifecycle.request_revoked`.
6. `test_a_worker_cannot_claim_a_request_while_its_admission_is_pending` (BE-006) — wrap `self.ledger.admit` with a function that records `self.queue.claim(owner='w',capacity=CAPACITY)` and then calls the real `admit`; `self.send()`; assert the recorded claim is `None`; afterwards `self.queue.claim(...)` returns the request. Fails today (the early claim succeeds and the request is then failed as unfunded).
7. `test_late_admission_for_a_closed_request_is_refused` (also in `tests/test_budget.py`) — insert a `customer_requests` row for task `t9` with `state='cancelled'`; `self.admit('t9')` raises `Conflict`; `SELECT count(*) FROM tasks WHERE id='t9'`==0 and no reservation.
8. `test_admit_failure_still_cancels_without_residue` — existing `test_budget_denial_cancels_request_without_residue` must still pass unchanged (the denied admit leaves no reservation, so `release_in` returns False).

`tests/test_budget.py` (class `BudgetChecks`):
9. `test_release_in_is_idempotent_and_leaves_uncertain_alone` — `self.admit()`; inside `with self.ledger.transactions.transaction() as con:` `self.assertTrue(self.ledger.release_in(con,'a','t1'))`, then a second call returns False; admit another task, call `receipt()` then `settle(effects_quiesced=True)` without `all_routes_reconciled` to make it `uncertain`, and assert `release_in` returns False and the state is still `uncertain`.
10. `test_settle_still_behaves_after_refactor` — the existing settle tests (`test_uncertain_effects_keep_allowance_reserved`, `test_duplicate_changed_foreign_and_late_receipts`) must pass untouched; they are the regression guard for the `settle_in` extraction.

`tests/test_request_queue.py` (class `SerialQueueChecks`; no entitlements, so queue-only behaviour):
11. `test_submit_hold_is_not_claimable_until_released` — `a=self.q.submit(self.a,message='m',key='h1',hold=True)`; `self.assertIsNone(self.claim())`; `self.assertIsNone(self.q.get(self.a,a['id'])['ahead'])`; `self.q.release_hold(self.a,a['id'])`; `self.assertEqual(self.claim().request_id,a['id'])`. Also: a customer `pause`/`resume` while held does not release it (`self.q.pause(...)`, `self.q.resume(...)`, still unclaimable).
12. `test_finish_closes_a_task_row_left_non_terminal` — insert a `tasks` row `queued` for the request (raw SQL, with the project/conversation FKs satisfied as `tests/test_budget.py` does), claim, `finish(...,state failed)`; assert `tasks.state=='failed'`. Guard: a task already `completed` by the driver is not overwritten.
13. `test_sweep_releases_orphans_and_ignores_live_and_uncertain` — build four requests with `tests/test_chat.py`'s fixture style in a new class `SweepChecks(ChatChecks)` inside `tests/test_chat.py` (it has the ledger): (i) a `cancelled` request with an `active` reservation and `queued` task made by raw `UPDATE customer_requests SET state='cancelled'` (simulating a pre-fix leak) -> released, task `cancelled`; (ii) a `waiting` request with active reservation -> untouched; (iii) a `running` request -> untouched; (iv) a terminal request with an `uncertain` reservation -> untouched. Assert the returned report `{'holds_released':0,'released':1,'tasks_closed':1}` and that a second `sweep()` returns all zeros (idempotent). Also a stale hold: submit with `hold=True`, advance `self.now` by 301, `sweep()` -> `holds_released==1`, then `claim` succeeds.

`tests/test_request_worker.py` (class `RequestWorkerChecks`, has a real worker and chat service):
14. `test_worker_restart_sweep_repairs_a_leak_on_the_first_tick` — send, then simulate the pre-fix leak by raw `UPDATE customer_requests SET state='cancelled'`; new `RequestWorker(...)` instance (fresh `_swept=None`), `tick()` -> report contains `'swept'` with `released==1`; reservation `settled`; a second `tick()` has no `'swept'` key (throttle: `self.now` unchanged). Then `self.now += 61`; leak again; tick sweeps again.
15. `test_unfunded_request_is_failed_with_task_closed_and_slot_free` — `UnmeasuredRoute` (see `tests/test_chat.py:73` for the pattern): the request waits unfunded; `tick()` -> `{'ran': 0, 'failed_unfunded': True}`; `request_slot` empty; request `failed`.
16. `test_uncertain_reservation_does_not_wedge_the_slot` (only if the `IN ('active','uncertain')` change is kept) — admitted request; set its reservation `uncertain` by raw SQL; `tick()` must not raise `Conflict`; the request ends `uncertain` (recoverable), not stuck `starting` with an exception.

`tests/test_native_run.py` (class `Base`, real `RequestWorker`):
17. `test_stop_while_waiting_behind_a_running_task_frees_the_allowance` — account `a` has a running request (claim it, leave it); a second `say(key='k2')` waits; `self.chat.cancel(self.a, second['id'])`; `self.ledger.summary(self.a)['held_microusd']` equals only the first request's 1000000; the second's task is `cancelled`; finish the first normally with `self.worker.tick()` and assert both reservations `settled` and no `active` rows remain (`SELECT count(*) FROM task_reservations WHERE state='active'`==0).
18. `test_ag004_two_accounts_stall_stub` (follow-up stub, `@unittest.skip('AG-004: needs the claim() decision from the owner')`). Setup: accounts `a` (cell holder, already in `Base.setUp`) and `b` (Base creates `b` too, no cell). Steps: `b` sends first (older, waiting; `claim` returns None because `lifecycle_slot` belongs to `a`), then `a` sends (newer). Assert the intended behaviour once decided: the cell holder `a` is not starved forever by `b`'s older request, i.e. either `claim` serves `a`'s request or the cell of `a` can sleep so `b` starts. Today (by reading) neither happens and `a`'s `tasks.state='queued'` blocks sleep. Write the test body to assert `self.queue.claim(owner='w', capacity=OK)` is not None for `a` and leave it skipped, with a comment pointing to AG-004 and Phase 2. This stub exists so the decision has an executable question; do not unskip it in this phase.

### Commands to run

From `/Users/parsa/AgentAI/openclaw-project/platform`:
```
.venv/bin/python -m unittest tests.test_budget tests.test_request_queue tests.test_chat tests.test_request_worker tests.test_native_run tests.test_worker tests.test_events tests.test_ops_restore tests.test_foundation tests.test_genui
.venv/bin/python manage.py test accounts.test_chat accounts.test_telegram accounts.test_billing
```
Run each step's tests as you go (1a: budget+chat; 1b: queue+chat+native_run; 1c: worker; 1d: foundation (migration count) + everything).

### Acceptance criteria

- Cancelling a waiting task: `held_microusd` drops by the reservation, `tasks.state='cancelled'`, reservation `settled`, `usage_entries` shows `reconciled 0` and `released <amount>` — all visible after ONE committed transaction (verify by killing nothing: the test reads after `cancel` returns).
- Three cancels then a fourth send succeeds.
- No code path settles twice (second `settle`/`release_in` returns False; one `released` entry).
- `sweep()` is a no-op on a healthy database (all zero) and repairs a seeded leak in one pass.
- A worker poll between submit and admit never obtains the request.
- All pre-existing tests in the listed suites still pass.

### Rollback

`git revert` the commits in reverse order. Steps 1a-1c are code-only. Step 1d leaves a harmless unused `admitting` column in production (SQLite `DROP COLUMN` is not needed; the column defaults to 0 and old code ignores it). Emergency switch without revert: stop calling `sweep` (set `sweep_every` huge) — the cancel/claim changes are inside existing transactions and have no switch; if a bad release is suspected, revert and deploy via `deploy/release.py` (canary + rollback).

### Risks and edge cases

- Deferred requests (`queue.defer`, `request_queue.py:240-247`) go back to `waiting` with a `queued` task and an `active` reservation and no receipts; cancelling one now releases correctly.
- A waiting request that already has receipts (cannot happen today because receipts are written only after a run) would still settle correctly, because `settle_in` books `reconciled=spent`, `released=amount-spent`.
- `restore.py` closes reservations with raw `state='settled'` and never writes `released` entries, so `_holds` is right but the audit differs; leave it, but note the sweep never touches a `settled` row.
- The sweep updates only `queued/paused` tasks of terminal requests; it must not run against a request whose driver is mid-`_close` (it cannot: the request is still `running` until `finish`).
- Goal chain (`chat.cancel` pauses the goal for a waiting goal task) is unchanged; run `tests/test_native_run.py` goal tests.
- Legacy `/v1/requests` POST (`accounts/requests.py:26`) never admits budget; it keeps `hold=False` and its old behaviour.

### Do not

- Do not call `ledger.settle` or `release_in` from `RequestQueue.cancel` for `starting/running/uncertain` requests.
- Do not open a second transaction (`ledger.settle(...)`) inside `queue.cancel`'s transaction: `Coordinator.transaction` uses `BEGIN IMMEDIATE` and would deadlock/raise. Use `release_in(c, ...)` with the caller's connection.
- Do not set reservation state to `cancelled`; do not delete or edit `usage_entries` (append-only triggers).
- Do not sweep `uncertain` reservations or reservations without a `customer_requests` row.
- Do not touch the tool-origin files in the dirty tree.

### Commit messages

- `Release the reservation and close the task when a waiting request is cancelled or revoked (M-01: BE-001, AG-001)` (steps 1a-1b)
- `Sweep reservations and tasks left behind by finished requests; run it from the request worker (M-01)` (1c)
- `Hold a request until its budget admission commits; refuse admission for a closed request (BE-006)` (1d)

---

# P1-7: Webhook body cap (BE-004, ST-018)

- **Findings**: BE-004, ST-018 (no test mentions `accounts/middleware.py`). **Finding check**: re-verified HIGH. `BoundaryMiddleware` (`accounts/middleware.py:22`) rejects any `CONTENT_LENGTH` above 8192 for every path except `/v1/requests`, paths ending `/send`, and paths ending `/files`. `/v1/billing/webhook` and `/v1/telegram/webhook` are in no exception, so a Stripe event larger than 8 KiB (invoices and subscriptions with expanded objects routinely are) is answered `413 request_too_large` before the view can verify its signature, and Stripe retries it for days. The billing view already has its own cap (`accounts/billing.py:150` against `MAX_BODY=262144`, and `agentai_platform/billing.py:380` again on the bytes). The Telegram view has no size check at all (`accounts/telegram.py:94-112`).
- **Goal**: provider webhooks of normal size are accepted and still authenticated by signature/secret; nothing else loses its 8 KiB cap.
- **Depends on / blocks**: none / P1-6 builds on this function. **GATE**: none.
- **Files to change**: `accounts/middleware.py:11-40` (and the `PUBLIC_UNMETERED` set at line 42), `accounts/telegram.py:94-112`. **Read first**: `accounts/billing.py:144-168`, `accounts/test_billing.py:111-128`, `accounts/test_telegram.py:20-47`.

### Change

1. In `middleware.py`, define the webhook set once above `BoundaryMiddleware`, reuse it for `PUBLIC_UNMETERED`, and exempt exactly those two paths from the default cap (their own views keep enforcing their own limits):

```diff
+WEBHOOKS={'/v1/telegram/webhook','/v1/billing/webhook'}     # provider ingress: authenticated by signature/secret and size-checked by their own views
+
 class BoundaryMiddleware:
@@
-            if len(request.get_full_path()) > 2048 or int(request.META.get('CONTENT_LENGTH') or 0) > (31457280 if request.path=='/v1/requests' or request.path.endswith('/send') or request.path.endswith('/files') else 8192):
+            if len(request.get_full_path()) > 2048 or int(request.META.get('CONTENT_LENGTH') or 0) > (31457280 if request.path=='/v1/requests' or request.path.endswith('/send') or request.path.endswith('/files') else 262144 if request.path in WEBHOOKS else 8192):
@@
-PUBLIC_UNMETERED={'/healthz','/readyz','/v1/telegram/webhook','/v1/billing/webhook'}
+PUBLIC_UNMETERED={'/healthz','/readyz'}|WEBHOOKS
```
The webhook ceiling in the middleware is 262144 (the same as `billing.MAX_BODY`), not "unlimited": the middleware stays a coarse outer bound and the views stay the precise ones. P1-6 replaces this expression with a tier table; if you implement P1-6 right after, fold this into it rather than keeping both.

2. Give Telegram the size check it lacks, after the secret check and before parsing (`accounts/telegram.py` after line 101):

```diff
     if not _secret_ok(request):
         ...
         return JsonResponse({'error': 'unavailable'}, status=403)
+    if int(request.META.get('CONTENT_LENGTH') or 0) > 65536:       # Telegram updates are a few KB; this bounds what an authenticated caller can make us parse
+        return JsonResponse({'ok': True})                          # 200 so Telegram does not retry an update we will never accept
     try:
         update = json.loads(request.body or b'{}')
```
Returning 200 (not 413) matches the view's existing "ignore, never make the provider retry" style for unparseable bodies (`telegram.py:104-105`). Billing keeps its 413 (Stripe should know).

### Tests (through the full middleware stack, Django test client with `secure=True`)

`accounts/test_billing.py` (next to `test_webhook_rejects_bad_signature_tampering_size_and_stale_timestamps`, line 111; reuse `self.events.make`, `self.events.body`, `signature_header`, `SECRET`, `self.configure(switch=False)`):
- `test_webhook_accepts_a_9kb_signed_event` — `event=self.events.make('customer.created', {'id':'cus_zzzzzz','metadata':{'pad':'x'*9000}})` (if `make` validates the object shape, pad any free-form field; confirm in `accounts/billing_fixture` / `tests/billing_fixture.py`), post the body with a valid `HTTP_STRIPE_SIGNATURE`; assert the body length is > 8192, status is 200 (or the same status the existing valid-signature test expects for that event type), and the JSON `error` is not `request_too_large`. Fails before the fix with 413 `request_too_large`.
- Keep the existing `b'x' * 300000 -> 413` assertion (now returned by the view as `too_large`, via `CONTENT_LENGTH > MAX_BODY`).
- `test_non_webhook_path_keeps_the_8kib_cap` — `self.new_client().post('/auth/login', b'x'*9000, content_type='application/json', secure=True)` -> 413 `request_too_large` (proves only the two paths were exempted).
`accounts/test_telegram.py` (class with `ENABLED`): 
- `test_webhook_accepts_a_9kb_update_and_drops_a_70kb_one` — `self.secret_post(self.new_client(), {'update_id':1,'junk':'x'*9000})` -> 200 and not 413; a 70000-byte body with the right secret -> 200 with `handle_update` not called (patch `TelegramService.handle_update`, assert not called).
- Wrong-secret requests above 8 KiB still return 403 (secret is checked before size), and unauthenticated requests above the cap never reach `request.body`.

### Commands
`cd /Users/parsa/AgentAI/openclaw-project/platform && .venv/bin/python manage.py test accounts.test_billing accounts.test_telegram accounts.tests` (Django suites; no external tools needed).

### Acceptance
A 9 KiB signed Stripe body is processed; a 9 KiB body to `/auth/login` is still 413; a 300 KB body to either webhook is refused; both views' own checks still run.

### Rollback
`git revert`. No data or config involved.

### Risks / Do not
- Do not exempt webhooks from `AccountMiddleware` metering semantics (`PUBLIC_UNMETERED` behaviour must stay identical; only the constant moved).
- Do not widen any other path. Do not remove the view-level checks.
- `request.body` of a webhook above `DATA_UPLOAD_MAX_MEMORY_SIZE` raises `RequestDataTooBig` (a `SuspiciousOperation`); see P1-6 so the Django ceiling stays at least 262144.

### Commit message
`Let provider webhooks past the 8 KiB boundary cap and size-check Telegram updates itself (BE-004, ST-018)`

---

# P1-6: Duplicate `DATA_UPLOAD_MAX_MEMORY_SIZE` and per-endpoint body caps (BG-011, BE-021)

- **Findings**: BG-011, BE-021 (also BE-004/P1-7). **Finding check**: re-verified HIGH, with two corrections to the finding text. (1) Current lines: `accounts/settings.py:58` (`= 200000`, dead) and `:100` (`= 31457280  # 25MiB batch cap plus multipart overhead`, the effective one). So today Django's own ceiling on any `request.body`/non-file form data is 30 MiB for every endpoint, including login. (2) The practical gate is `BoundaryMiddleware` (`middleware.py:22`), which only looks at `Content-Length`: it already caps most JSON at 8192 bytes, but that is lower than what some views intend. `accounts/views.py:62-63` says structured endpoints allow `len(request.body) > 131072` -> 400, and the generative-UI endpoints (`accounts/genui.py:53,62,70,78,122,131,140,149`, `browse.py:91,185`, `vault.py:34`, `safety.py:88`) are declared `structured=True`, yet the middleware stops any of them above 8192 first with 413. A plan or document block above 8 KiB therefore cannot be saved or launched. Also `/send` and `/v1/requests` carry a message of at most 16000 characters but are allowed 30 MiB. (A request without `Content-Length`, e.g. chunked, does not bypass this: Django/gunicorn then see a zero-length body.)
- **Goal**: one authoritative size policy per endpoint class; no endpoint accepts more than it can use; large structured blocks work.
- **Depends on / blocks**: P1-7 (same expression) / none. **GATE**: tightening `/send` and `/v1/requests` from 30 MiB to 256 KiB changes an accepted-input bound. It does not limit any task or customer allowance (messages are already capped at 16000 characters by the views), so it is consistent with the owner rule, but confirm: "Cap chat messages at 256 KiB of request body (they are 16000 characters max) instead of 30 MiB? Default: yes." Raising the structured cap from 8 KiB to 128 KiB is a bug fix with no gate.

### Intended caps (decision)

| Class | Paths | Cap (bytes of `Content-Length`) | Why |
|---|---|---|---|
| default | everything else (auth, signup, recovery, small JSON/forms) | 8192 | unchanged |
| message | `/v1/requests`, `/v1/conversations/<id>/send` | 262144 | 16000 chars x up to 3 UTF-8 bytes x percent-encoding in the form-post fallback is about 144 KB; JSON with `\u` escapes about 96 KB |
| structured | `/v1/blocks/<id>/(state|submit|launch|phase|stop|live)`, `/v1/genui/artifacts/<id>/(state|events|update|diagnostics)`, `/v1/browse/<id>/(control|answer|...)`, `/v1/vault`, `/v1/safety/change` | 131072 | equals the view's own `len(request.body) > 131072` check (`views.py:63`) |
| upload | `/v1/projects/<id>/files` | 31457280 | 25 MiB batch + multipart overhead (`MAX_BATCH_BYTES`, `agentai_platform/files.py:21`) |
| webhook | `/v1/billing/webhook`, `/v1/telegram/webhook` | 262144 | P1-7; views enforce 262144 / 65536 |

Django ceiling: after this task `DATA_UPLOAD_MAX_MEMORY_SIZE = 262144` (largest non-file body), `FILE_UPLOAD_MAX_MEMORY_SIZE = 0` stays, so uploaded file parts go to temporary files and are not counted against it. VERIFY this with the upload test below before relying on it; if the 5 MiB multipart upload fails, fall back to the safe option.

**Safe option (no behaviour change, do this first as its own commit)**: only delete the dead line 58 and make the line-100 comment true ("Django-level ceiling for any request body; the tiered caps in BoundaryMiddleware are the real gate"). Zero risk. The tiered middleware and the lowered Django ceiling are the second commit.

### Files to change
`accounts/settings.py:58,100`, `accounts/middleware.py:11-40`. **Read first**: `accounts/views.py:46-66`, `accounts/files.py:83-110`, `accounts/genui.py` decorators, `accounts/test_files.py`.

### Change

1. `settings.py`: delete line 58. Replace line 100 with `DATA_UPLOAD_MAX_MEMORY_SIZE = 262144  # largest non-file request body (chat message class and webhooks); uploaded file parts are not counted (FILE_UPLOAD_MAX_MEMORY_SIZE = 0 sends them to temp files)`. Keep `DATA_UPLOAD_MAX_NUMBER_FIELDS = 12`.
2. `middleware.py`: replace the inline conditional with a small table (match the file's dense style):

```diff
+import re
+BODY_CAPS=((re.compile(r'^/v1/projects/[^/]+/files$'),31457280),
+           (re.compile(r'^/v1/(requests|conversations/[^/]+/send)$'),262144),
+           (re.compile(r'^/v1/(blocks/[^/]+/[a-z]+|genui/artifacts/[^/]+/[a-z]+|browse/[^/]+/[a-z]+|vault|safety/change)$'),131072))
+def body_cap(path):
+    if path in WEBHOOKS:return 262144
+    return next((cap for pattern,cap in BODY_CAPS if pattern.match(path)),8192)
@@
-            if len(request.get_full_path()) > 2048 or int(request.META.get('CONTENT_LENGTH') or 0) > (31457280 if ... else 8192):
+            if len(request.get_full_path()) > 2048 or int(request.META.get('CONTENT_LENGTH') or 0) > body_cap(request.path):
```
Anchored regexes replace the old `endswith('/send')`/`endswith('/files')` matching, which also matched any future route that merely ends in those words. GET requests have no body, so the structured pattern matching GET paths such as `/v1/browse/<id>/shot` is harmless.
3. `views.py:57` (`json.loads(request.body or b'{}')`) needs no change: it parses after the middleware gate and Django's ceiling; the per-field limits at `views.py:65` (`512` default, `16000` for messages) and the 131072 structured check remain the semantic bounds. Add a one-line comment above line 57 that the size gate is `BoundaryMiddleware.body_cap`.

### Tests
- New `accounts/test_boundary.py` (Django `TestCase`, reuse `AccountBoundaryTests.new_client`/`signed` from `accounts/tests.py`): 
  - `test_default_cap_is_8kib` — 9000-byte JSON to `/auth/login` -> 413 `request_too_large`.
  - `test_structured_block_state_above_8kib_reaches_the_view` — signed customer posts a 20000-byte `{'version':1,'state':{...}}` to `/v1/blocks/nope/state`; expect NOT 413 (404 `unavailable` or 400 from the view). Pre-fix: 413.
  - `test_structured_cap_is_128kib` — 140000 bytes -> 413.
  - `test_message_cap` — 300000 bytes to `/v1/conversations/x/send` -> 413; 100000 bytes -> not 413 (view error is fine).
  - `test_upload_cap_and_5mib_multipart_upload_still_works` — in `accounts/test_files.py`, reuse its upload helper with a ~5 MiB valid file (UPLOADS_ENABLED is required there); must still return the same status as before. This is the guard for the lowered `DATA_UPLOAD_MAX_MEMORY_SIZE`.
  - `test_webhook_paths_follow_p1_7` — unchanged from P1-7.
  - `test_get_full_path_limit_unchanged` — 2100-char query -> 413.

### Commands
`cd /Users/parsa/AgentAI/openclaw-project/platform && .venv/bin/python manage.py test accounts.test_boundary accounts.test_files accounts.test_genui accounts.test_chat accounts.test_billing accounts.test_telegram`; plus `tests/test_foundation.py` line 101 (a raw HTTP check that 5000 bytes to `/v1/tasks` gives 413 on a stricter harness) must still pass: `.venv/bin/python -m unittest tests.test_foundation`.

### Acceptance
Plans/documents of 8-128 KiB save; 9 KiB login bodies 413; chat messages up to 256 KiB accepted; uploads up to 25 MiB still succeed; `rg -n "DATA_UPLOAD_MAX_MEMORY_SIZE" accounts/settings.py` shows one line.

### Rollback
`git revert` (two commits revert independently). If the Django ceiling breaks uploads in production, restore line 100 to `31457280` only.

### Risks / Do not
- Caddy/Vercel body limits are unverified (BG-011 note): raising the structured cap here does nothing if an edge proxy truncates first; ask the owner to check `platform/deploy/caddy/Caddyfile.getlumina` (`request_body max_size`) and `vercel.json` when deploying (text only, no SSH by you).
- Do not lower `/files` below 31457280 (batch of 10 x 10 MiB capped at 25 MiB).
- Do not rely on `Content-Length` for streaming uploads beyond this gate; the upload view validates per file.

### Commit messages
`Remove the dead DATA_UPLOAD_MAX_MEMORY_SIZE assignment (BE-021)` then `Tier the request body caps by endpoint class so structured blocks above 8 KiB work (BG-011)`

---

# P1-12: Remove or isolate `/v1/tasks/<id>/stream` (BE-002)

- **Findings**: BE-002 (High). **Finding check**: re-verified HIGH for the config part. `deploy/gunicorn.conf.py`: `workers=1, worker_class='sync', threads=1, timeout=15, backlog=16`. `accounts/streams.py:stream` (lines 62-121) is a sync generator that loops with `time.sleep(1.0)` for `STREAM_WINDOW_SECONDS = 45`. A sync worker serves one request at a time, so one open stream blocks the whole web app, and gunicorn kills the worker at 15 s, dropping any other in-flight request; the "3 streams per account" cap cannot be reached because streams are serialised. Confirmed no client uses it: `rg` over `lumina/src` finds no `EventSource` and no `/stream` call (`useActivity.ts` polls `/events`); only docs (`UI_CONTRACT.md:42`, `docs/architecture/*`), `openapi.json:2488`, `accounts/urls.py:49`, `accounts/test_streams.py:33-72` and `deploy/p15_acceptance.py:161` mention it. (Other routes with `streams` under `/v1/streams*` are separate disabled stubs and are not touched.)
- **Goal**: no authenticated customer can occupy or kill the single web worker; unfinished SSE code is preserved for a future async worker.
- **Depends on / blocks**: none. **GATE (choose one)**: Option A (recommended, preserves unfinished functionality): keep the code behind an off-by-default setting; the route answers 404 `unavailable`. Option B: delete the view, route, OpenAPI path and tests. Question: "Keep the SSE stream code but disabled (A), or delete it (B)?" Recommended A, per "preserve unfinished functionality". Option A is specified in full below; Option B is the delete list at the end.
- **Files to change (A)**: `accounts/streams.py:62-121`, `accounts/settings.py` (new flag near `UPLOADS_ENABLED`, line ~64), `openapi.json:2488-2520`, `UI_CONTRACT.md:42`, `accounts/test_streams.py:39-70`, `deploy/p15_acceptance.py:161` (expectation only if the acceptance run compares statuses; it already expects non-owner results, so check). **Read first**: `accounts/test_streams.py`, `accounts/test_chat.py:338-355` (OpenAPI drift test).

### Change (Option A)

```diff
 # settings.py, next to UPLOADS_ENABLED
+# Server-sent task streams need an async/threaded web worker; the single sync gunicorn worker must never run them (BE-002). The app polls /v1/tasks/<id>/events.
+SSE_ENABLED = os.environ.get('AGENTAI_SSE_ENABLED') == '1'
```
```diff
 @csrf_exempt
 def stream(request, request_id):
     denied = customer(request)
     if denied:
         return denied
     if request.method != 'GET':
         return JsonResponse({'error': 'method_not_allowed'}, status=405)
+    if not settings.SSE_ENABLED:
+        return JsonResponse({'error': 'unavailable'}, status=404)        # same public shape as every disabled capability; the client polls /events
     principal = _principal(request)
```
`settings` is already imported at the top of `streams.py` (line 13). The order keeps 401 for anonymous callers and 405 for POST (existing assertions), and still does not reveal whether a task exists.

OpenAPI: edit the `/v1/tasks/{id}/stream` summary to `"Disabled in this deployment (needs an async web worker); answers 404. Poll /v1/tasks/{id}/events instead"` and change its documented responses to 401/404/405; keep the path so `accounts/test_chat.py:OpenApiDriftChecks` (which requires every routed `/v1` path to be documented) stays green. `UI_CONTRACT.md:42`: replace "live `GET /v1/tasks/{id}/stream` (...)" with "live updates: poll the timeline endpoint (`/stream` is disabled)".

Gunicorn implications (write these into the commit body, do not change the config here): `workers=1`/`sync` plus SQLite means all customers' polling is serialised (BE-013 is a separate decision); `timeout=15` would kill any 45 s stream even if enabled, so enabling `AGENTAI_SSE_ENABLED=1` is only valid after moving to `gthread`/`gevent` workers with `timeout` above the 45 s window and re-checking SQLite write contention. The flag is therefore a deliberate tripwire, not a tuning knob. Caddy buffering: `X-Accel-Buffering: no` is already set by the view.

### Tests
`accounts/test_streams.py`:
- Existing `test_sse_stream_auth_cap_and_events` (line 39): decorate with `@override_settings(SSE_ENABLED=True)` so the preserved behaviour (cap of 3, 429, events, `open`/`task_event` chunks) stays covered.
- New `test_stream_is_disabled_by_default` — signed customer `GET /v1/tasks/task-a/stream` -> 404 `{'error':'unavailable'}`; anonymous -> 401; `POST` -> 405; no `event_streams` row is created (`SELECT count(*) FROM event_streams` unchanged) — this proves a disabled stream can no longer block anything or fill the table.
- `test_cross_account_stream_is_a_clean_404_not_a_server_error` (line 33) must pass unchanged.
- `accounts/test_chat.py::OpenApiDriftChecks.test_routes_and_spec_agree` must pass (route still present and documented).

### Commands
`cd /Users/parsa/AgentAI/openclaw-project/platform && .venv/bin/python manage.py test accounts.test_streams accounts.test_chat && .venv/bin/python -m unittest tests.test_events`

### Acceptance
Default deployment: `/stream` returns 404 immediately for an authenticated customer, takes no worker time, creates no stream row; `/events` polling unchanged; with the flag on in a test, the old behaviour is intact.

### Rollback
`git revert`; or set `AGENTAI_SSE_ENABLED=1` (not recommended on the sync worker).

### Option B (delete)
Remove `path('v1/tasks/<str:request_id>/stream',st.stream)` from `accounts/urls.py:49`; delete `stream`, `_sse` and the unused imports from `streams.py`; delete the `/v1/tasks/{id}/stream` entry from `openapi.json`; delete the stream cases from `accounts/test_streams.py:33-70` and the stream line from `deploy/p15_acceptance.py:161`; update `UI_CONTRACT.md:42`; leave `EventService.open_stream/heartbeat_stream/close_stream` and `event_streams` (tested in `tests/test_events.py`) in place. Then `rg -n "tasks/.*stream"` must show only docs history.

### Do not
Do not touch `/v1/streams*` stubs; do not change gunicorn settings; do not add a 503 (the repo's disabled convention is 404 `unavailable`, per `test_chat.py` DISABLED).

### Commit message
`Disable the SSE task stream by default so it cannot hold the single web worker (BE-002)`

---

# P1-8: Billing reconcile timer (BE-005)

- **Findings**: BE-005. **Finding check**: re-verified HIGH. `deploy/agentai-billing-worker.service:11` runs `manage.py billing_worker` without `--reconcile`; `deploy/agentai-billing-worker.timer` (`OnBootSec=3min`, `OnUnitInactiveSec=30s`, `RandomizedDelaySec=5s`) is the only billing timer; the VPS listing shows it enabled (`vps_readonly_2026-10-29.txt:30,59`). Semantics (`accounts/management/commands/billing_worker.py:28-45`, `agentai_platform/billing.py:627-657`): every run does `sync_open_access`, and only when a Stripe client is configured (`svc.api is not None`) also `process(50)` (apply stored webhook events), `sweep()` (clock-driven access changes from stored facts) and, with `--reconcile`, `reconcile()` which calls `retrieve_subscription` once per row of `billing_subscriptions` (sequential, no pacing), re-derives access with `apply_snapshot`, and reports `{checked, drift, provider_errors, inbox, dead_letters}`. Output is counts only. Note for the owner: production is in free-access mode (RUNBOOK:848); with no Stripe key configured the command prints `provider: not configured` and `--reconcile` does nothing, so the new timer is harmless until payments are switched on, and is exactly what catches a lost webhook after that. Also the service's `TimeoutStartSec=120`, `MemoryMax=96M`, `CPUQuota=25%` are fine for tens of subscriptions; each Stripe call is about 0.2-0.5 s, so above roughly 200 subscriptions raise `TimeoutStartSec`.
- **Goal**: webhook drift against Stripe is detected and repaired on a schedule, separately from the 30 s inbox worker.
- **Depends on / blocks**: none. **GATE**: owner installs units on the VPS (text below; you do not run anything). Question: "Run the reconcile every 6 hours (recommended) or daily?"
- **Files to add**: `platform/deploy/agentai-billing-reconcile.service`, `platform/deploy/agentai-billing-reconcile.timer`. **Files to change**: `agentai_platform/ops/monitor.py:23` (add the timer so a dead reconcile is noticed), `tests/test_ops_monitor.py:103-104` (cover it), `RUNBOOK.md:843-846` (one sentence). `deploy/release.py:84,86` needs no change (the reconcile unit only reads Stripe and writes via the same SQLite transactions; a release that stops the app does not require stopping it; if the owner wants it paused during releases, add a second `systemctl stop/start` line to `SystemdControl.stop/timers_start`).

### Unit text (draft; same hardening as the existing service)

`agentai-billing-reconcile.service`:
```
[Unit]
Description=AgentAI billing reconcile (compare every subscription with Stripe and repair drift)
After=network-online.target agentai-platform-app.service

[Service]
Type=oneshot
User=agentai-platform
Group=agentai-platform
WorkingDirectory=/opt/agentai-platform/current
EnvironmentFile=/etc/agentai-platform/accounts.env
ExecStart=/opt/agentai-platform/current/.venv/bin/python manage.py billing_worker --reconcile
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
ReadWritePaths=/var/lib/agentai-platform
ReadOnlyPaths=/etc/agentai-platform
MemoryMax=96M
MemorySwapMax=0
CPUQuota=25%
TasksMax=16
TimeoutStartSec=300
```
`agentai-billing-reconcile.timer`:
```
[Unit]
Description=Run the AgentAI billing reconcile every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:25:00 UTC
RandomizedDelaySec=300
Persistent=true
Unit=agentai-billing-reconcile.service

[Install]
WantedBy=timers.target
```
Rate: one Stripe retrieve per subscription every 6 h (about 4 x N calls/day); Stripe's live limit is 100 requests/s, so there is no pacing concern at current scale. `billing_worker --reconcile` also runs `process(50)` and `sweep()`; both are idempotent and lease-based (`billing_inbox` leases), so overlapping with the 30 s worker is safe.

### Monitor change (code)
```diff
-TIMERS = {'agentai-billing-worker.timer': 300, 'agentai-platform-mail.timer': 600, ...
+TIMERS = {'agentai-billing-worker.timer': 300, 'agentai-billing-reconcile.timer': 8 * 3600, 'agentai-platform-mail.timer': 600, ...
```
(value = seconds of staleness tolerated, 6 h period plus slack.) Caution: `ops/monitor.py` will WARN until the owner installs the timer, so merge this line only together with the owner's install, or accept one WARN. `tests/test_ops_monitor.py:103-104`: add `self.probe.timers['agentai-billing-reconcile.timer'] = NOW - 3000` and assert OK/WARN in the same style; confirm how `probe.timers` defaults for unlisted timers first.

### Owner steps (text for approval; not to be run by the implementer)
1. Copy the two files to `/etc/systemd/system/` (owner root), `systemctl daemon-reload`.
2. Dry check: `sudo -u agentai-platform /opt/agentai-platform/current/.venv/bin/python manage.py billing_worker --check` (inbox counts only; shows `provider_configured`).
3. `systemctl enable --now agentai-billing-reconcile.timer`.
4. Verify: `systemctl list-timers agentai-billing-reconcile.timer`; trigger once `systemctl start agentai-billing-reconcile.service`; `journalctl -u agentai-billing-reconcile.service -n 20 --no-pager` must show one JSON line containing `"reconcile": {"checked": N, "drift": [], "provider_errors": 0, ...}` (or `"provider": "not configured"` in free-access mode). `dead_letters` above 0 needs a person (RUNBOOK:844).
5. Rollback: `systemctl disable --now agentai-billing-reconcile.timer`; remove the two files.

### Tests
- `tests/test_billing_install.py` (existing install checks): add `test_reconcile_units_exist_and_match_the_worker_hardening` — read both files from `platform/deploy/`, assert `ExecStart` ends with `billing_worker --reconcile`, `Type=oneshot`, `User=agentai-platform`, and that every hardening directive present in `agentai-billing-worker.service` (`NoNewPrivileges`, `ProtectSystem`, `ReadWritePaths`, `MemoryMax`, `CPUQuota`, `TasksMax`, `RestrictAddressFamilies`) also appears in the reconcile unit (so the two cannot drift apart). Timer file has `OnCalendar=` and `Persistent=true`.
- `accounts/test_billing.py`: add `test_reconcile_reports_drift_and_counts_only` if no existing test calls `billing_worker --reconcile` (grep first); use the existing fake API fixture to return a different status for one subscription, run `call_command('billing_worker', '--reconcile', stdout=out)`, assert `reconcile.drift` has one entry and the output contains no email, customer id or key (counts-only rule).
Commands: `cd /Users/parsa/AgentAI/openclaw-project/platform && .venv/bin/python -m unittest tests.test_billing_install tests.test_ops_monitor && .venv/bin/python manage.py test accounts.test_billing`.

### Acceptance
Unit files parse (`systemd-analyze verify` is for the owner on the VPS), tests pass, monitor lists the new timer, first manual run prints a reconcile summary, no secrets in the journal.

### Risks / Do not
- Do not add `--reconcile` to the 30 s unit (it would call Stripe 2880 times/day per subscription).
- Do not enable the timer in repo scripts; install is owner-only. Do not log subscription ids or emails.
- If Stripe is unreachable, `provider_errors` rises and nothing is changed (errors are swallowed per subscription by design).

### Commit message
`Add a scheduled billing reconcile timer and watch it in the ops monitor (BE-005)`

---

# P1-9: Park limit that actually stops the run (AG-005) and a spend guard that does not fail open (AG-007)

Money path (both): coordinate with P1-1, rebase after it. These touch `chat_driver.py` only in the functions named; do not reformat the file.

## AG-005: `PARK_LIMIT` does not stop a run

- **Findings**: AG-005. **Finding check**: re-verified MEDIUM-HIGH by reading. Current: `check_parked` `chat_driver.py:802-824`: at line 817-819 `if self._human_wait(claim): if self.clock() - since >= self.park_limit: return 'ended'`. `RequestWorker._parked_tick` (`request_worker.py:103-112`) treats `'ended'` as "only closing is left": `unpark(need_slot=False)` then `_run(claim)` -> `driver.execute` -> `_reassert` + `_supervise`. The run is still live and the browse job is still `asking/paused`, so `_supervise` hits `reason = self._human_wait(claim)` (`chat_driver.py:364-366`) and returns `Parked(reason)` again; `queue.park` (`request_queue.py:230-239`) rewrites `parked_epoch`, restarting the 1800 s clock. The browse service bounds a question to `ASK_SECONDS` 300 and a takeover pause to 600 s, so in practice the hold ends after minutes, but the limit itself is dead, and the test at `tests/test_native_run.py:198-201` only asserts the string `'ended'`.
- **Goal**: a person who never answers cannot hold the cell, the reservation and the browser forever; the task ends with a clear message and the allowance is settled. This enforces the EXISTING 1800 s limit (no new limit).
- **GATE**: none.

### Change
`agentai_platform/chat_driver.py`:
1. `check_parked` returns `'expired'` instead of `'ended'` for the timeout case only (keep `'ended'` for "the run finished on its own" and "Stop pressed"):
```diff
         if self._human_wait(claim):
-            if self.clock() - since >= self.park_limit:
-                return 'ended'
-            return 'waiting'
+            return 'expired' if self.clock() - since >= self.park_limit else 'waiting'
```
and update the docstring: `'expired'` = the person never came back: stop the run and close the request.
2. New driver method (next to `_timed_out`, `chat_driver.py:569`), reusing the existing stop helpers:
```python
    def expire_parked(self, claim):
        """The person never came back within the park limit: stop the run and the browser job and close the request as failed. A real stop, not another park."""
        gateway = self.gateway_factory(claim)
        session = self._session(claim)
        self._stop_browser_jobs(claim)
        if self._cell_gone(gateway):
            return self._interrupted(claim, gateway)          # already stopped: closes failed (not cancelled), settles
        self._abort_all(claim, gateway, session)               # raises when the runtime cannot confirm: the request stays recoverable
        self._pause_goal(claim, gateway, session, 'Waiting for you took too long, so the task was stopped.')
        self._mirror(claim, gateway, session, set())
        note = 'You did not answer in time, so the task was stopped. Send it again whenever you are ready.'
        self._emit(claim, 'progress', {'summary': note}, 'gateway')
        return self._close(claim, 'failed', note, gateway, self._before(claim), verdict=outcome_mod.Verdict('failed', 'unverified', note, ''))
```
(`_close` reconciles usage and settles through the ledger exactly as for `_timed_out`; after P1-1 `finish` also normalises the task row.)
3. `request_worker.py` `_parked_tick`:
```diff
             state = self.driver.check_parked(parked)
             if state == 'waiting':
                 continue
+            if state == 'expired':
+                claim = self.queue.unpark(parked, owner=self.owner, lease_seconds=self.lease_seconds, need_slot=False)
+                if claim is None:
+                    continue
+                return self._expire(claim)
             claim = self.queue.unpark(...)
```
```python
    def _expire(self, claim):
        try:
            receipt = self.driver.expire_parked(claim)
        except Exception:
            self.queue.uncertain(claim)       # same recovery as any failed run: reconciled on a later tick
            raise
        return {'ran': 1, 'expired': True, 'finished': bool(self.queue.finish(claim, receipt))}
```

### Tests
Replace `tests/test_native_run.py:198-201` (`test_a_person_who_never_answers_does_not_hold_the_cell_forever`) with an outcome test:
```python
    def test_a_person_who_never_answers_does_not_hold_the_cell_forever(self):
        sent = self.start_and_park()
        self.now += self.driver.park_limit + 1
        self.assertEqual(self.driver.check_parked(self.queue.parked()[0]), 'expired')
        self.assertEqual(self.worker.tick(), {'ran': 1, 'expired': True, 'finished': True})
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['outcome'], row['parked_reason']), ('failed', 'failed', None))
        self.assertFalse(self.rows('SELECT 1 FROM request_slot'))
        self.assertTrue([c for c in self.gateway.calls if c[0] == 'abort'])                 # the run was really stopped
        self.assertEqual(self.rows('SELECT state FROM task_reservations')[0][0], 'settled')  # allowance given back
        self.assertEqual(self.rows('SELECT state FROM tasks')[0][0], 'failed')
        self.assertEqual(self.worker.tick(), {'ran': 0})                                     # not parked again
```
Before the fix the last two lines fail (the request is re-parked: `state` stays `running`, reservation `active`). Add `test_expiry_with_an_unreachable_cell_leaves_the_request_recoverable`: make the gateway raise `CapabilityUnavailable` on `abort`; the tick raises, the request is `uncertain`, and a later tick with the gateway restored finishes it. Add a negative test that a parked request below the limit is still `'waiting'`.
Commands: `cd /Users/parsa/AgentAI/openclaw-project/platform && .venv/bin/python -m unittest tests.test_native_run tests.test_request_worker tests.test_chat`.

### Acceptance / rollback / do not
Acceptance: after `park_limit + 1` the request is `failed` with the user-facing note and the reservation `settled`; no re-park. Rollback: `git revert`. Do not shorten `PARK_LIMIT` or the browse service bounds; do not call `_stop` (it would label the task cancelled by the customer).
Commit: `Stop a run whose person never answered instead of re-parking it forever (AG-005)`.

## AG-007: spend guard fails open

- **Findings**: AG-007. **Finding check**: re-verified HIGH. `_usage_before` (`chat_driver.py:464-471`) returns `None` on any exception; `_over_budget` (`chat_driver.py:478-490`) returns `False` when there is no reservation, no first delivery, `usage_before_microusd is None`, or no `usage_snapshot` attribute, and `False` again on any snapshot exception (lines 489-490). It is called once every `spend_check_seconds=20` from `_supervise` (`:372-375`). So a flaky LiteLLM snapshot silently disables the per-task spend stop for the rest of the run; the remaining backstops are the 900 s run timeout and provider-side caps. A missing reservation or snapshot capability is by design (budget caps off, unpriced route) and must stay unmetered.
- **Goal**: an unreadable spend meter is visible and, if the owner agrees, ends a run only after it has been unreadable for a sustained period. It never stops a run whose meter works, and it never adds a customer-facing limit.
- **GATE (owner decision, both options specified)**. Question: "When the spend meter cannot be read for 5 minutes in a row during a run, should Lumina stop the run (Option B, recommended) or only log it (Option A)?" Recommendation: B with a high threshold, because it is a correctness repair of bookkeeping (fail-closed), not a new task limit: the run is bounded to a few minutes of blindness, healthy runs are never touched, and a transient error (a handful of failed 20 s checks) does not stop anything. Option A keeps today's blindness and only adds a counts-only journal line. The code below implements both through one constructor setting: `blind_limit` consecutive unreadable checks (default 15, about 5 minutes); `blind_limit=0` means alert-only (Option A). If the owner picks A, set the default to 0.

### Change (`agentai_platform/chat_driver.py`)
1. Constructor: add `blind_limit=SPEND_BLIND_LIMIT` (module constant `SPEND_BLIND_LIMIT = 15  # consecutive unreadable spend checks (20 s apart) before a run is stopped; 0 = only log`), store `self.blind_limit`.
2. `_over_budget` rewrite keeping its contract (`True` = stop):
```diff
-        if not reserved or not first or first['usage_before_microusd'] is None or getattr(gateway, 'usage_snapshot', None) is None:
-            return False
-        try:
-            return gateway.usage_snapshot() - first['usage_before_microusd'] >= reserved
-        except Exception:
-            return False
+        if not reserved or not first or getattr(gateway, 'usage_snapshot', None) is None:
+            return False                                   # nothing to measure against (no reservation / no meter): unmetered by design
+        try:
+            now_spend = gateway.usage_snapshot()
+        except Exception:
+            return self._blind(spend, 'snapshot failed')
+        baseline = first['usage_before_microusd']
+        if baseline is None:
+            baseline = spend.setdefault('baseline', now_spend)   # the start-of-run read failed: guard from the first good reading (local only; settlement still uses the conservative reserved amount)
+            if now_spend == baseline and 'baseline_logged' not in spend:
+                spend['baseline_logged'] = True
+                self._log_blind('no start baseline')
+        spend['blind'] = 0
+        return now_spend - baseline >= reserved
+
+    def _blind(self, spend, why):
+        spend['blind'] = spend.get('blind', 0) + 1
+        if spend['blind'] == 1:
+            self._log_blind(why)
+        spend['stopped_blind'] = bool(self.blind_limit) and spend['blind'] >= self.blind_limit
+        return spend['stopped_blind']
+
+    @staticmethod
+    def _log_blind(why):
+        print(json.dumps({'event': 'spend_guard_blind', 'reason': why}), flush=True)   # counts only: no account, task or amount
```
Do NOT write the late baseline into `chat_deliveries.usage_before_microusd`: `_reconcile_usage` charges the full reserved amount when `before` is `None`, which is the conservative behaviour, and a late baseline would under-charge.
3. In `_supervise` (`:372-375`) choose the stop message by cause:
```diff
                 over = self._over_budget(claim, gateway, spend)
                 if over:
-                    return self._budget_stop(claim, gateway, session)
+                    return self._budget_stop(claim, gateway, session, blind=spend.get('stopped_blind', False))
```
`_budget_stop(self, claim, gateway, session, blind=False)`: when `blind`, the pause note and the event use "We could not check this task's spending, so it was stopped to protect your allowance." instead of "The spending limit for this task was reached." (both the `_pause_goal` text and `self._emit(... 'budget' ...)` and `note`); the verdict stays `partial`, state `completed`, so the customer keeps whatever was produced and the closing path (`_close` -> reconcile -> settle) is identical.
4. Optional (separate small commit): log once when `_usage_before` fails (`print(json.dumps({'event':'spend_guard_blind','reason':'no start baseline'}))`).

### Tests (`tests/test_native_run.py`, class `Base`; find the existing `_over_budget` / budget-stop tests with `rg -n "usage_snapshot|budget" tests/test_native_run.py tests/test_chat.py` and extend their gateway stub)
- `test_a_run_with_a_failing_meter_is_stopped_after_the_blind_limit` — gateway whose `usage_snapshot` raises; `ChatDriver(..., blind_limit=3, spend_check_seconds=0)`; run a long script (`gateway.polls=50`); `worker.tick()`; assert the run was aborted, request `completed` with outcome `partial`, note mentions "could not check", reservation settled at the reserved amount. Before the fix: the run continues until the 900 s timeout.
- `test_one_failed_check_among_good_ones_never_stops_a_run` — snapshot fails once then recovers; run finishes normally; `spend['blind']` reset (assert via the final outcome `completed`, no abort call).
- `test_blind_limit_zero_is_alert_only` — `blind_limit=0`, snapshot always fails; run completes; the captured stdout contains exactly one `spend_guard_blind` line (use `contextlib.redirect_stdout`).
- `test_missing_start_baseline_uses_the_first_good_reading` — `usage_before_microusd` NULL; snapshot returns 0 then reserved+1 later; run is stopped for spend (normal budget message).
- `test_no_reservation_or_no_meter_is_unmetered` — budget caps off (no reservation) -> never stops, no log line.
Commands: `cd /Users/parsa/AgentAI/openclaw-project/platform && .venv/bin/python -m unittest tests.test_native_run tests.test_chat tests.test_request_worker`.

### Acceptance / rollback / do not
Acceptance: a meter that fails for 5 minutes ends the run with a clear message and a settled reservation; a meter that fails a few times does not; a journal line appears once per run on first failure and never contains ids or amounts. Rollback: `git revert` or set `blind_limit=0` (alert only). Do not add a max-turns or tool-round cap here (AG-007's optional second half is a new task limit; owner has said no new task limits, and it needs a decision, not this phase). Do not change `spend_check_seconds`.
Commit: `Make the per-run spend guard visible and stop a run whose meter has been unreadable for five minutes (AG-007)`.

---

# P1-10: Compact specs for six smaller fixes

Same template, shorter. Each is independently committable.

## P1-10a: BG-015 `task_state` returns the last event's sequence
- **Findings**: BG-015. **Finding check**: re-verified HIGH. `agentai_platform/events.py:127-141`: `row = con.execute('SELECT state FROM tasks ...')` then `for row in rows:` rebinds `row`, and `'task_state': row[0]` after the loop is the last event's `sequence` (an int) whenever the page has events; correct only on an empty page. Not money path. No gate.
- **Change**:
```diff
             if not row:
                 raise NotFound('unavailable')
+            task_state = row[0]
             rows = con.execute(...)
             events = []
-            for row in rows:
-                payload = json.loads(row['public_payload'])
-                events.append({'sequence': row['sequence'], 'kind': row['kind'], 'source': payload.pop('source', 'system'),
-                               'payload': payload, 'created_at': row['created_at']})
-            return {'task_id': task_id, 'task_state': row[0], 'events': events, ...
+            for item in rows:
+                payload = json.loads(item['public_payload'])
+                events.append({'sequence': item['sequence'], 'kind': item['kind'], 'source': payload.pop('source', 'system'),
+                               'payload': payload, 'created_at': item['created_at']})
+            return {'task_id': task_id, 'task_state': task_state, 'events': events, ...
```
- **Tests**: `tests/test_events.py` near line 100-106 (pagination test): after appending events, `page = self.events.events(self.a, self.task_id, after=0)`; assert `page['task_state'] == 'queued'` (the fixture task state; read it from the `tasks` row) and is a `str`; a second assertion for an empty page. Fails today (returns an int such as 5). `accounts/test_streams.py::test_events_endpoint_scoped_and_validated` add the same field check over HTTP. Commands: `.venv/bin/python -m unittest tests.test_events && .venv/bin/python manage.py test accounts.test_streams`.
- **Acceptance**: `GET /v1/tasks/<id>/events` always returns the task's state string. **Rollback**: revert. **Do not**: rename the response key. **Commit**: `Return the task state, not the last sequence, from the events page (BG-015)`.

## P1-10b: BG-006 ascending `LIMIT` drops the newest rows
- **Findings**: BG-006. **Finding check**: re-verified HIGH. Current sites: `agentai_platform/artifacts.py:119-121` (`ORDER BY a.created_at,a.id,a.version LIMIT 200`), `agentai_platform/files.py:168-170` (`ORDER BY created_at,id LIMIT 200`), `agentai_platform/genui/store.py:98-99` (`ui_blocks ... ORDER BY created_epoch,rowid LIMIT 100`) and `:101-102` (`data_blocks ... ORDER BY created_epoch,position LIMIT 100`). `accounts/files.py:259` resolves "latest version of a file" from the truncated `list_artifacts`, so after 200 rows it serves a stale version or 404. Not money path. No gate (this keeps the same page size and contract: the UI gets the same-shaped list, now the newest N in the same ascending order).
- **Change**: take the newest N, return them oldest-first, so existing consumers see the same order:
```diff
-            rows = con.execute('''SELECT a.id,... FROM artifacts a LEFT JOIN tasks t ON ...
-                WHERE a.account_id=? AND a.project_id=? ORDER BY a.created_at,a.id,a.version LIMIT 200''', (...))
+            rows = con.execute('''SELECT * FROM (SELECT a.id,... FROM artifacts a LEFT JOIN tasks t ON ...
+                WHERE a.account_id=? AND a.project_id=? ORDER BY a.created_at DESC,a.id DESC,a.version DESC LIMIT 200)
+                ORDER BY created_at,id,version''', (...))
```
Same pattern for `list_files` (`ORDER BY created_at DESC,id DESC LIMIT 200` inside, `ORDER BY created_at,id` outside), `ui_blocks` (`created_epoch DESC,rowid DESC LIMIT 100` inside; outer `ORDER BY created_epoch,rowid`), `data_blocks` (inner DESC on `created_epoch,position`; outer ascending). Also add a direct lookup so `gen_asset` does not depend on the cap: `ArtifactService.latest_by_name(principal, project_id, name)` (`SELECT ... WHERE account_id=? AND project_id=? AND display_name=? ORDER BY version DESC, created_at DESC LIMIT 1`, after `_authorize`) and use it at `accounts/files.py:259-261` in place of the list comprehension (keep the files fallback). The `/blocks` and Files responses stay unpaged and capped, as `UI_CONTRACT.md` documents; add one sentence there: "the newest 100/200 items are returned".
- **Tests**: `tests/test_files.py` / `tests/test_gen_artifacts.py` (find the artifact fixtures with `rg -n "capture_or_version|capture(" tests`): `test_listing_keeps_the_newest_items_beyond_the_cap` — create 205 artifacts via `capture` (small payloads; quota is far away), assert `len==200`, the newest name is present, the oldest 5 are absent, and order is ascending. Same for 105 `data_blocks` (use `BlockStore.add_display`, `tests/test_genui.py` has the fixtures) and 205 project files. `accounts/test_genui.py` (line ~72 asset test): after 205 unrelated artifacts, the asset for a freshly versioned `sample.png` is the latest version (check the `sha256`/bytes). Fails today: the new item is missing.
- **Commands**: `.venv/bin/python -m unittest tests.test_files tests.test_gen_artifacts tests.test_genui && .venv/bin/python manage.py test accounts.test_files accounts.test_genui`.
- **Acceptance**: with more rows than the cap, the newest appear. **Rollback**: revert. **Risks**: ordering contract (ascending) must be preserved for the frontend; SQLite requires the outer `ORDER BY` since a subquery order is not guaranteed. **Do not**: paginate or change response shapes here. **Commit**: `List the newest artifacts, files and blocks when a bucket exceeds its cap (BG-006)`.

## P1-10c: BG-004 inline asset capped at 200 KiB
- **Findings**: BG-004. **Finding check**: re-verified HIGH. `accounts/files.py:266` and `:272` call `read_private(..., max_bytes=MAX_PREVIEW_BYTES)` with `MAX_PREVIEW_BYTES = 200 * 1024` (`agentai_platform/files.py:24`); `storage.py:75-77` raises `ValueError('content exceeds bound')`, which `_mapped` (`accounts/files.py:70-80`) turns into a generic 400, including for `download=1`. Typical screenshots, charts and PDFs exceed 200 KiB, so they cannot be shown or downloaded from a document block. Not money path.
- **GATE (small)**: the new bound. Recommend 10 MiB, which equals `MAX_FILE_BYTES` (`agentai_platform/files.py:20`) and the upload limit, so any file a customer could upload can also be shown; the artifact-side cap is `MAX_ARTIFACT_BYTES` in `artifacts.py`. Not a task limit.
- **Change**: add `MAX_ASSET_BYTES = 10 * 1024 * 1024` in `agentai_platform/files.py` (keep `MAX_PREVIEW_BYTES` for the text previews), and use it at `accounts/files.py:266` and `:272`:
```diff
-            data = artifacts.storage.read_private(parts, max_bytes=MAX_PREVIEW_BYTES)
+            data = artifacts.storage.read_private(parts, max_bytes=MAX_ASSET_BYTES)
```
(both call sites; update the import). Keep the sandbox headers (`CSP: default-src 'none'; sandbox`, `nosniff`, `Cache-Control: no-store`). `read_private` reads whole files into memory for `max_bytes` above one chunk (chunked loop at `storage.py:~70`), so 10 MiB per request on the single worker is acceptable; do not raise further without moving to `FileResponse(open(...))` streaming (note for later). Also make an over-bound file a clear 413 instead of the generic 400: catch the specific `ValueError('content exceeds bound')` in `gen_asset` and return `{'error': 'file_too_large'}` 413.
- **Tests**: `accounts/test_genui.py` (asset test at line ~72): add a 400 KiB valid PNG (pad with a valid `IDAT`/or reuse the fixture's PNG with a trailing `tEXt` chunk if `sniff` accepts it; otherwise a 400 KiB `text/plain` file referenced by `assetRef`) -> 200 with the full body length (before: 400); a file just above 10 MiB (create via the artifact store directly, bypassing the upload cap if needed) -> 413 `file_too_large`; `download=1` for the 400 KiB file -> 200 with `Content-Disposition`. Cross-account (`b.get(...)` -> 404) and unreferenced path (404) assertions stay.
- **Commands**: `.venv/bin/python manage.py test accounts.test_genui accounts.test_files`.
- **Acceptance**: a 1 MiB image in a document renders. **Rollback**: revert. **Do not**: loosen the `references()` check, the allowed media list or the CSP. **Commit**: `Allow generated media up to 10 MiB in document blocks and say so when a file is too large (BG-004)`.

## P1-10d: BG-013 asset capture aborts at the first failing file
- **Findings**: BG-013. **Finding check**: re-verified HIGH. `ChatDriver._capture_files` (`chat_driver.py:718-749`): one `try: ... except Exception: pass` wraps the whole `for path, data in collect(since)` loop, so the first file that raises (`Conflict` quota/version cap from `capture_or_version`, an `IntegrityError` from two captures of one name, a disk error) silently drops all remaining files of the task, with no event. `capture_or_version` (`artifacts.py:~65-84`) reads the current version in one transaction and inserts in another. The name mapping `path.replace('/', '_')` makes `a/b.txt` and `a_b.txt` one artifact name: leave it (changing it would break version chains of existing nested files); document it as a known limitation in the commit body. Money path: no. No gate.
- **Change**: isolate each file and tell the customer when one cannot be saved (the task still never fails because of it):
```diff
-            for path, data in collect(since):
-                ...
-                saved = self.artifacts.capture_or_version(...)
-                if saved:
-                    self._emit(claim, 'artifact', {...}, 'gateway')
-        except Exception:
-            pass
+            for path, data in collect(since):
+                name = path.replace('/', '_')[:128]
+                try:
+                    ...(existing extension/sniff/json checks, `continue` as today)...
+                    saved = self._save_capture(claim, row['project_id'], name, MEDIA.get(ext, 'application/octet-stream'), data)
+                    if saved:
+                        self._emit(claim, 'artifact', {...}, 'gateway')
+                except Exception as exc:
+                    why = 'storage limit reached' if isinstance(exc, Conflict) else 'could not be saved'
+                    self._emit(claim, 'progress', {'summary': f'A file the assistant made ({name}) {why}.'}, 'gateway')
+        except Exception:
+            pass      # listing the workspace itself failed: best effort, as before
+
+    def _save_capture(self, claim, project_id, name, media, data):
+        try:
+            return self.artifacts.capture_or_version(account_id=claim.account_id, project_id=project_id, task_id=claim.request_id, name=name, media_type=media, data=data)
+        except sqlite3.IntegrityError:           # a concurrent capture of the same name won the race: now it is a new version
+            return self.artifacts.capture_or_version(account_id=claim.account_id, project_id=project_id, task_id=claim.request_id, name=name, media_type=media, data=data)
```
(`sqlite3` import at the top if absent; the event contains the customer's own file name and a fixed phrase, never exception text. Confirm `progress` is an allowed event kind in `events.py` allowlist, as used at `chat_driver.py:195` and `chat.py:297`.)
- **Tests**: `tests/test_chat.py` (existing capture test around line 233 defines a `workspace_files` stub): `test_one_failing_file_does_not_drop_the_rest` — stub returns three small allowed files; patch `artifacts.capture_or_version` to raise `Conflict('x')` for the second; assert files 1 and 3 became artifacts, the task completed, and a `progress` event mentions the second name and "storage limit"; `test_integrity_race_retries_once` — raise `sqlite3.IntegrityError` once for a name then succeed; the artifact exists. Fails today: only file 1 saved, no event.
- **Commands**: `.venv/bin/python -m unittest tests.test_chat tests.test_gen_artifacts tests.test_files`.
- **Acceptance**: a quota failure on one file saves the others and tells the customer. **Rollback**: revert. **Do not**: let a capture failure fail or delay the task; do not put paths or exception strings in events. **Commit**: `Save each deliverable independently and say when one cannot be saved (BG-013)`.

## P1-10e: BG-014 plan phase stuck `running` with no request
- **Findings**: BG-014. **Finding check**: re-verified MEDIUM-HIGH. `PlanRunner._spawn` (`genui/runner.py:106-126`): transaction 1 sets the phase `running` (`attempts+1`, `started_epoch`), then `self.chat._spawn(...)` creates the request with the deterministic key `phase-{block}-{phase}-{attempts}` (`:116`), then transaction 2 stores `request_id` (`:123-125`). A process death between them leaves `state='running', request_id IS NULL`: `sync()` joins on `request_id` (`:53-55`) so it never advances; `advance()` returns early while any phase is `running` (`:80`); skip needs pending/awaiting/failed (`:191`) and retry needs failed (`:187`). Only Stop works. After P1-1, `chat._spawn` is also the place where the admission hold is released, so this fix assumes P1-1 is merged. Indirectly money path (it re-drives `chat._spawn`, which funds the request); the key is deterministic, so a re-drive is idempotent end to end (`submit` replay returns the same request; `admit` replay returns the same reservation).
- **Change**: in `sync()` (called at the top of every `tick`, `:62-64`), first adopt or release orphaned phases:
```python
    def _recover_orphans(self):
        """A phase marked running whose request id was never stored (the process died between the two writes): adopt the request if it exists, else send the phase back to pending so the normal advance re-spawns it with the same key."""
        cutoff = int(self.clock()) - 120
        with self.store.connect() as con:
            orphans = con.execute("SELECT account_id,block_id,phase_id,attempts FROM plan_phase_runs WHERE state='running' AND request_id IS NULL AND started_epoch<=? LIMIT 20", (cutoff,)).fetchall()
        for o in orphans:
            key = f'phase-{o["block_id"]}-{o["phase_id"]}-{o["attempts"]}'
            with self.blocks.coordinator.transaction() as con:
                req = con.execute('SELECT id FROM customer_requests WHERE account_id=? AND idempotency_key=?', (o['account_id'], key)).fetchone()
                if req:
                    con.execute("UPDATE plan_phase_runs SET request_id=? WHERE account_id=? AND block_id=? AND phase_id=? AND state='running' AND request_id IS NULL", (req['id'], o['account_id'], o['block_id'], o['phase_id']))
                else:   # nothing was created: re-spawn from pending with the same attempt number so the key repeats
                    con.execute("UPDATE plan_phase_runs SET state='pending',attempts=attempts-1,started_epoch=NULL WHERE account_id=? AND block_id=? AND phase_id=? AND state='running' AND request_id IS NULL AND attempts>0", (o['account_id'], o['block_id'], o['phase_id']))
```
Call `self._recover_orphans()` at the start of `sync()`. Request adoption also covers `ui_blocks.launched_request_id` (set it with the same `coalesce` UPDATE as `_spawn:125` if missing). The 120 s grace avoids racing a live `_spawn` between its two transactions. No new customer-visible limit.
- **Tests**: `tests/test_genui.py` (plan runner tests; find with `rg -n "PlanRunner|runner" tests/test_genui.py`): `test_phase_left_running_without_a_request_is_adopted` — launch a plan, advance (`runner.advance`), then simulate the crash by `UPDATE plan_phase_runs SET request_id=NULL` for that phase while the request exists; move `self.now` +121; `runner.tick()`; assert `request_id` restored and the phase later reaches `completed` through `sync`. `test_phase_left_running_with_no_request_is_respawned_once` — delete the request row (or simulate by never creating: set state running/request NULL with a fresh phase), advance time, `tick()`; assert state is `running` again with a request whose `idempotency_key` equals the original and `attempts` unchanged, and `SELECT count(*) FROM customer_requests` == 1. `test_a_fresh_running_phase_is_left_alone` (age < 120 s). Fails today: stays running forever.
- **Commands**: `.venv/bin/python -m unittest tests.test_genui tests.test_chat tests.test_native_run`.
- **Acceptance**: after a simulated crash the plan continues within one worker tick after 2 minutes; nothing duplicated. **Rollback**: revert. **Do not**: re-spawn without reusing the key; do not touch phases with a `request_id`. **Commit**: `Recover plan phases left running without a request after a crash (BG-014)`.

## P1-10f: BE-017 `task.create` cap missing on `chat_send`
- **Findings**: BE-017. **Finding check**: re-verified HIGH that the cap is absent: `rate('task.create', request.account_id, 30, 3600)` is applied in `accounts/requests.py:25`, `accounts/chat.py:198` (`chat_goal`) and `:266` (`chat_retry`), but not in `chat_send` (`accounts/chat.py:165-190`). Surrounding guards on the main path: `api.mutate` 30/min per user+IP (`middleware.py:60-66`), the 3-waiting queue limit (`request_queue.py:74`), the plan budget and the per-task cap.
- **Conflict with the owner's rule**: adding a 30-per-hour cap to the main send path is a new per-task limit. Also a trap: `send` also carries STEERED messages that join a running task and create no task (`chat.py:215-222`), so a naive `rate(...)` at the top of the view would cap ordinary back-and-forth chat at 30 messages/hour.
- **GATE (both options)**. Question: "Should the main send path get the same hourly task-creation cap as retry/goal/legacy requests (30 new tasks per hour per account)?" 
  - **Option A (recommended): do nothing; record the omission as intentional.** Add a comment above `chat_send` (`# no task.create cap by design: the queue limit, plan budget and api.mutate bound it; steered messages create no task`) and a one-line note in `CLAUDE.proposed.md`/`TECHNICAL_DEBT.md` if the owner keeps those. This respects "no new task limits" and "privacy over task guardrails".
  - **Option B: add the cap, counting only new tasks.** After a successful `service().send(...)`, charge once if the result is a new task, not a steer and not a replay: 
    ```diff
    +        if not result.get('steered') and result.get('created_new', True):
    +            rate('task.create', request.account_id, 30, 3600)
    ```
    where `ChatService.send` must expose whether the request was new (replay branch of `queue.submit` returns an existing request; add a `'replayed': True` key in `submit`'s `old` branch, or compare `created_epoch` to `now`). The limit would then apply after the task is created (it throttles the next one), which is acceptable but weaker than a pre-check; a pre-check needs the same new-vs-steer determination before submitting, which needs a service method change. Use a generous number (for example 120/hour) if the owner wants a guard against runaway scripts rather than a task limit.
- **Tests (B only)**: `accounts/test_chat.py`: `test_steered_messages_do_not_count_toward_task_create` (send 40 steer messages to one running task -> never 429); `test_task_create_cap_applies_to_new_tasks` (patch `accounts.chat.rate` as `accounts/test_billing.py:196` does and assert `assert_any_call('task.create', account, N, 3600)` exactly once per new task, not on replay). Commands: `.venv/bin/python manage.py test accounts.test_chat accounts.test_safety` (note `accounts/test_safety.py:253` already toggles the `task.create` scope per account).
- **Acceptance (A)**: comment only, no behaviour change. **Rollback**: revert. **Do not**: put `rate('task.create')` at the top of the view. **Commit (A)**: `Document that the main send path has no task.create cap by design (BE-017)`; (B) `Apply the task.create limit to new tasks on the main send path, not to steered messages (BE-017)`.

---

# Final verification pass (after all selected tasks)

From `/Users/parsa/AgentAI/openclaw-project/platform`:
```
.venv/bin/python -m unittest tests.test_request_queue tests.test_budget tests.test_chat tests.test_native_run tests.test_request_worker tests.test_worker tests.test_events tests.test_files tests.test_genui tests.test_gen_artifacts tests.test_ops_restore tests.test_ops_monitor tests.test_billing_install tests.test_foundation
.venv/bin/python manage.py test accounts --verbosity 1
```
Then `git diff --stat` must list only the files named in the tasks you did; the tool-origin files from the dirty tree must be unchanged. Production effects are limited to: (1) the additive migration `0031` (P1-1 step 1d) at the next deploy, (2) the billing reconcile timer installed by the owner (P1-8), (3) no gunicorn or Caddy changes. Add the new/untested suites to CI under M-10 (`tests.test_native_run`, `tests.test_request_worker`, `tests.test_ops_monitor`, `tests.test_billing_install`, the new `accounts.test_boundary`); not part of this phase.
