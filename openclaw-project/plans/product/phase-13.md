# Product Phase 13 — hosted billing, invoices and access reconciliation

**Status (2026-10-12):** implementation **READY** (built and tested offline); acceptance **NOT_RUN** (Phase 15);
nothing deployed to the server, no Stripe account or key used, no payment of any kind.
Technical reference: [`platform/BILLING.md`](../../platform/BILLING.md). Evidence:
[`evidence/product/phase-13/20261012T012505Z/manifest.json`](../../evidence/product/phase-13/20261012T012505Z/manifest.json).

## What was built

Stripe **test-mode** hosted checkout and customer portal; a webhook ingress that verifies the raw body and stores the
event before acknowledging; an inbox worker with leases, backoff and dead-lettering; a state machine that turns verified
provider state into the same `entitlements` the Phase 5 ledger enforces; a billing page (plan, status, grace/cancel dates,
confirmed-by-provider vs held-estimate usage, invoice links, portal for payment recovery and cancellation); reconciliation
and a clock sweep; an owner switch `billing_checkout` (off); worker units (prepared, not installed); and an installer that
validates a Stripe **test** configuration and records only the facts it verified.

## Provider documentation verified (2026-10-12, docs.stripe.com)

| Topic | Fact relied on | Where used |
|---|---|---|
| Webhook signing ([webhooks](https://docs.stripe.com/webhooks)) | Header `t=<ts>,v1=<hmac>[,v0=…]`; signed string `<ts>.<raw body>`; HMAC-SHA256 with the `whsec_` secret; ignore non-`v1`; constant-time compare; default 5 min tolerance, `0` disables the check; raw body required; secrets can overlap up to 24 h while rolling | `verify_signature`, tests incl. rotation and downgrade |
| Delivery behavior (same page) | Return 2xx quickly then process; retries up to 3 days live, 3 over hours in sandbox; order **not** guaranteed; do not rely on `created` for order; dedupe by event id; fetch current objects; exempt route from CSRF | inbox-first design, canonical fetch, `csrf_exempt` route |
| Idempotency ([idempotent requests](https://docs.stripe.com/api/idempotent_requests)) | `Idempotency-Key` header, ≤255 chars, saved result replayed, keys pruned after ≥24 h, different parameters under one key error, POST only | `billing_operations`, stable keys, `StripeHttp` |
| Subscription object ([subscriptions](https://docs.stripe.com/api/subscriptions/object)) | Statuses `incomplete, incomplete_expired, trialing, active, past_due, canceled, unpaid, paused`; `cancel_at_period_end`; **period start/end are on subscription items** | `normalize_subscription`, `derive_access` |
| Subscription webhooks ([guide](https://docs.stripe.com/billing/subscriptions/webhooks)) | On `invoice.paid` retrieve the subscription and require `active` before extending access; revoke on `canceled`/`unpaid`; handle `charge.refunded` and `charge.dispute.created`; charge → subscription via PaymentIntent → invoice payment → invoice `parent.subscription_details` (API ≥ 2025-03-31.basil) | `_sync`, `_refund`, `_dispute`, `subscription_for_charge` |
| Checkout ([create session](https://docs.stripe.com/api/checkout/sessions/create)) | `mode=subscription`, `line_items[n][price|quantity]`, `customer`, `client_reference_id`, `metadata`, `subscription_data`, `success_url`/`cancel_url`; response `id`, `url`, `status`, `payment_status`; sessions expire (30 min–24 h) | `start_checkout` |
| Portal ([create portal session](https://docs.stripe.com/api/customer_portal/sessions/create)) | `customer`, `return_url` → `url` | `portal_url` |

Not verified here: tax settings, regional fees, Smart Retries dashboard defaults, the exact API version string for this account (the owner pins it).
No SDK is used: a small stdlib client with a pinned `Stripe-Version` replaces it; the official SDK remains an option.

## Scenario coverage (each is an automated test)

| Required scenario | Test (platform `tests/test_billing.py` unless noted) |
|---|---|
| Successful checkout | `LifecycleChecks.test_checkout_to_active_closes_the_trial_and_admits_tasks`, Django `test_full_flow_checkout_webhook_worker_and_access` |
| Redirect never grants access | `CheckoutChecks.test_redirect_alone_never_grants_access`; Django flow asserts status `none` after checkout and after *stored but unprocessed* webhook |
| Renewal | `LifecycleChecks.test_renewal_extends_and_resets_the_period_allowance`, `test_missed_renewal_webhook_still_ends_access_at_the_period_end` |
| Duplicate events / lost acknowledgment | `WebhookChecks.test_acknowledged_only_after_persistence_and_duplicates_collapse`, `LifecycleChecks.test_replaying_every_event_changes_nothing_a_second_time`, `InboxAndReconcileChecks.test_concurrent_processors_apply_each_event_once` |
| Reordered events | `LifecycleChecks.test_out_of_order_delivery_converges_on_the_canonical_state`, `RefundDisputeChecks.test_dispute_events_in_reverse_order_end_in_the_final_state` |
| Invalid / tampered / stale / oversize / live webhook | `SignatureChecks.*`, `WebhookChecks.test_invalid_oversize_and_live_events_are_refused_and_not_stored`, Django `test_webhook_rejects_bad_signature_tampering_size_and_stale_timestamps` |
| Payment failure, grace, recovery | `FailureAndRecoveryChecks.test_payment_failure_grace_then_block_then_recovery`, `PolicyChecks.test_past_due_gets_exactly_the_grace_window`, `GraceFromPlanChecks` |
| Running work after access ends | `FailureAndRecoveryChecks.test_running_work_drains_after_access_ends_but_nothing_new_starts` |
| Upgrade / downgrade, proration effect | `PlanChangeChecks.test_upgrade_and_downgrade_change_limits_without_a_new_period`, `test_downgrade_below_current_spend_denies_new_tasks_only` |
| Cancellation (period end and immediate) | `FailureAndRecoveryChecks.test_cancel_at_period_end_keeps_access_then_deleted_event_ends_it`, `test_immediate_cancellation_ends_access_now` |
| Refund (full / partial) | `RefundDisputeChecks.test_full_refund_stops_new_tasks_partial_does_not_and_renewal_restores` |
| Dispute (open / won / lost) | `RefundDisputeChecks.test_dispute_suspends_then_won_restores_and_lost_ends` |
| Task admission race | `AdmissionRaceChecks.test_a_task_cannot_start_without_an_eligible_entitlement_and_reservation` |
| Provider outage | `CheckoutChecks.test_outage_then_retry_reuses_the_same_idempotency_key`, `InboxAndReconcileChecks.test_provider_outage_retries_with_backoff_then_succeeds`, `test_endless_outage_dead_letters_after_the_attempt_limit` |
| Duplicate checkout | `CheckoutChecks.test_duplicate_click_reuses_the_hosted_session`, `test_already_subscribed_cannot_check_out_again_and_accounts_do_not_mix` |
| Client cannot choose account/price/quantity | `CheckoutChecks.test_everything_sensitive_is_derived_server_side`; Django default test posts `price`/`account_id` and gets `400` |
| Observable dead letters and reconciliation | `InboxAndReconcileChecks.test_permanent_failures_are_dead_lettered_and_visible`, `test_reconcile_repairs_drift_when_a_webhook_was_never_delivered` |
| Billing records outlive agent data | Django `test_retention_and_account_deletion_leave_billing_records_alone` |
| Live key / unpinned version refused | `HttpClientChecks.test_live_keys_missing_keys_and_unpinned_versions_are_refused`, installer tests |

## Decisions recorded

- Stripe-side free trials are **not** access (the 7-day $1 trial is the app's invitation trial; no card, no auto-conversion).
- One eligible entitlement per account: starting paid access expires the trial row in the same transaction.
- Customer ↔ account mapping exists only for customers and checkout sessions this platform created; nothing in a payload (metadata, `client_reference_id`) can assign an account.
- Refund of the paid invoice stops *new* tasks; usage receipts are never rewritten; a later paid period restores access.
- Grace is read from `plan.json` (`billing_grace_hours`, 72) and starts when the platform first observes `past_due`.
- Billing and agent purchasing stay separate: no cell, worker or tool receives Stripe configuration.

## Owner setup, step by step (when you are ready to try test mode)

1. Create a Stripe account and stay in **test mode** (sandbox). Nothing here uses real cards.
2. Create a product named *Builder* with a **recurring monthly price of $79.00 USD**; copy the `price_…` ID.
3. Copy the **test secret key** (`sk_test_…`) and note the account's **API version** (shown in Workbench).
4. Add a webhook endpoint `https://backend.getlumina.pro/v1/billing/webhook` with the events listed in `platform/BILLING.md`; copy its `whsec_…` secret.
5. In the customer portal settings allow: update payment method, cancel at period end, invoice history. In subscription settings leave payment retries on.
6. Put `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `STRIPE_API_VERSION` into `openclaw-project/.env` and tell me. I will deploy the code, run `deploy/billing_install.py` (dry run first), and you flip **Let customers subscribe and pay (Stripe test mode)** on the dashboard's Feature switches page.

## Checks actually run

45 billing scenarios and 6 installer checks (platform), 8 Django route checks, full suites: **350 platform (2 skipped), 75 Django, 35 dashboard** pass.
A first run of the downgrade scenario failed because the test crossed the daily-allowance boundary and the queue limit; both were test-design errors and are fixed, not product defects.
No network call, key or Stripe account was used.

## Cost, unknowns, blockers, rollback

- **Cost:** nothing spent. Stripe's published rates (2.9% + $0.30 per card, 0.7% of billing volume) apply to real payments only; account/country/tax fees unverified.
- **Unknowns:** the account's API version string; real event payload shapes beyond documentation; portal configuration defaults; Smart Retries timing vs the 72 h grace; tax and refund terms (open legal items).
- **Blockers for live proof:** Stripe test account, price, webhook; migration 0013 and the billing worker timer not yet deployed; Phase 15 runs the live test-mode scenarios.
- **Rollback:** nothing deployed. To remove after deployment: turn the switch off, disable `agentai-billing-worker.timer`, revert settings; billing tables are append-only records and are kept.

## Addendum 2026-10-12 — free access until payments are switched on (requested by the owner)

The owner asked to keep Stripe disabled for now and let any account use the service until payments are turned on. Built and deployed:

- New owner switch **Free access for every account (no payment needed) until payments are turned on** (`open_access`); the Stripe switch is now
  **Require payment**, needs two confirmations (test mode; accounts without a paid plan are paused) and takes precedence. One toggle flips the service between free and paid.
- `BillingService.sync_open_access` (runs in `billing_worker` every ~30 s, no Stripe needed). 7 platform and 1 end-to-end Django scenario cover grant, idempotence, refresh, switch-off, TTL lapse,
  paid-wins, fall-back after expiry, dispute-hold, and the full free → paid-required → free cycle. A real defect was found and fixed on the way: superseded entitlement rows kept a later `valid_until`
  and made the usage summary show the wrong (expired) row; expired rows now have `valid_until` pulled back to the moment they expired.
- **Deployed to the server (2026-10-12 ~01:38 UTC):** database backed up, migrations 0009–0013 applied, release `20261012T0230Z-billing` live (automatic rollback was armed; not needed), billing worker timer
  enabled, owner dashboard updated, `open_access` turned ON with the cost confirmation recorded as the owner's request. The one existing account now has an active `open` entitlement; its 7-day invitation-trial row was superseded.
- Findings: `/etc/agentai-platform` is root-only, so billing secrets and the plan file live in `/var/lib/agentai-platform/billing` (app-private, 0600) and `/opt/agentai-platform/billing-plan.json` (not secret); the installer was corrected.
- Cost: each active account may consume up to $25 of provider cost per month (invitation-only, so bounded by how many accounts you invite); you pay it. This only passes the payment gate: tasks still queue until customer cells and the per-account model route are switched on (Phase 4 follow-ups).
- Rollback: turn **Free access** off (access ends within ~30 s), or `ln -sfn` the previous release (recorded in `/root/p13-previous-release`) and restart `agentai-platform-app`; the pre-migration database backup is `backup-20261012T013633Z-premigrate-billing.sqlite3`.
