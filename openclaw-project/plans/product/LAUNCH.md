# Launch readiness (Lumina, getlumina.pro)

Status as of 2026-10-13. Production (179.236.71.203) runs this branch: app release `launch1`, supervisor `p16-n`, Lumina bundle current. Merge to `main` deploys the website through Vercel.

## Done and live
Sign-in and accounts, isolated per-customer assistants, chat with history, plans and forms, data cards, web search, files, Activity window, browser tasks (switch ON), JEV routing (switch ON, record-only), serial task queue, budget caps ($79/mo, $25 included, $5 task cap, 7-day $1 trial, no auto overage), nightly backups on the server, monitor every 5 minutes.

## Needs the owner before real customers (cannot be done from code)
1. **Merge to `main`** via the PR (publishes the website).
2. **Stripe**: create the account/product, give the keys, turn on `billing_checkout`; test one real payment and one refund.
3. **Legal pages**: terms, privacy, refund policy (the app links to them; text is not written).
4. **Off-server backup copy**: backups live only on the VPS today; a disk loss loses them.
5. **SSH**: key-only login (root password login is still allowed).
6. **Brave search key**: every assistant uses the owner's key; replace with a dedicated key and set a spend alert.
7. **Google / GitHub connectors**: register the OAuth apps if they should be offered at launch (otherwise leave off).
8. **Support**: a support email address and who answers it.

## Needs a "go" from the owner
- Phase 15 acceptance run, Phase 17 invite-only beta (2 trial accounts), then launch review.
- Browse benchmark with paid runs (tens of dollars) before JEV is allowed to choose actions.

## Not built yet (decide whether launch needs them)
Guarded ordering/payments by the browser agent (locked `credentialed_browsing`), browser hardening pass (injection tests, capacity test), live code/file preview workspace.

## Rollback
Switch the feature off in the owner switches (`browse_tasks`, `customer_execution`, `open_access`); app release rollback is `release.py` previous release (binary rollback compatible).
