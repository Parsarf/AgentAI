# Three-step durable objective fixture (synthetic)

Objective: write three small files, one per step, each recorded with a receipt.
1. Step 1 completes with receipt r1.
2. Kill the runtime during step 2 after the write is issued but before its
   receipt returns: record checkpoint r2 as `uncertain`.
3. Restart. Expected: objective is `paused`/`needs_reconciliation`; no work
   resumes by itself; resume is refused.
4. Reconcile r2 by reading the workspace (file exists or not) — never by
   resending. Then explicit resume continues with step 3 only.
5. Separate run: cancel mid-task with a child job registered; restart. Expected:
   children cancelled, objective stays cancelled, resume refused.
