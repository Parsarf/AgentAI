-- Phase 13: hosted billing (Stripe test mode first). Provider secrets are never stored here.
-- Billing records are deliberately NOT tied to accounts(id) by a foreign key: required financial
-- records are retained separately from agent data and survive account content deletion.
CREATE TABLE billing_customers (
  account_id TEXT PRIMARY KEY,
  provider_customer_id TEXT NOT NULL UNIQUE CHECK(provider_customer_id LIKE 'cus_%'),
  created_epoch INTEGER NOT NULL
);
CREATE TABLE billing_checkout_sessions (
  provider_session_id TEXT PRIMARY KEY CHECK(provider_session_id LIKE 'cs_%'),
  account_id TEXT NOT NULL,
  plan_version TEXT NOT NULL,
  price_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('open','completed','expired')),
  created_epoch INTEGER NOT NULL,
  expires_epoch INTEGER NOT NULL
);
CREATE INDEX billing_checkout_account ON billing_checkout_sessions(account_id,state);
CREATE TABLE billing_subscriptions (
  provider_subscription_id TEXT PRIMARY KEY CHECK(provider_subscription_id LIKE 'sub_%'),
  account_id TEXT NOT NULL,
  provider_customer_id TEXT NOT NULL,
  plan_version TEXT,
  price_id TEXT,
  provider_status TEXT NOT NULL,
  current_period_start INTEGER,
  current_period_end INTEGER,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0 CHECK(cancel_at_period_end IN (0,1)),
  past_due_since INTEGER,
  fully_refunded INTEGER NOT NULL DEFAULT 0 CHECK(fully_refunded IN (0,1)),
  disputed INTEGER NOT NULL DEFAULT 0 CHECK(disputed IN (0,1)),
  access_state TEXT NOT NULL CHECK(access_state IN ('active','grace','expired','suspended')),
  access_reason TEXT NOT NULL,
  synced_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL
);
CREATE INDEX billing_subscriptions_account ON billing_subscriptions(account_id);
CREATE TABLE billing_invoices (
  provider_invoice_id TEXT PRIMARY KEY CHECK(provider_invoice_id LIKE 'in_%'),
  account_id TEXT NOT NULL,
  provider_subscription_id TEXT,
  status TEXT NOT NULL,
  amount_due INTEGER NOT NULL,
  amount_paid INTEGER NOT NULL,
  currency TEXT NOT NULL,
  hosted_invoice_url TEXT,
  period_start INTEGER,
  period_end INTEGER,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL
);
CREATE INDEX billing_invoices_account ON billing_invoices(account_id,created_epoch);
CREATE TABLE billing_flags (
  kind TEXT NOT NULL CHECK(kind IN ('refund','dispute')),
  object_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  provider_subscription_id TEXT NOT NULL,
  active INTEGER NOT NULL CHECK(active IN (0,1)),
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(kind,object_id)
);
CREATE TABLE billing_inbox (
  event_id TEXT PRIMARY KEY CHECK(event_id LIKE 'evt_%'),
  event_type TEXT NOT NULL,
  provider_created INTEGER NOT NULL,
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  payload TEXT,
  status TEXT NOT NULL CHECK(status IN ('received','processing','applied','ignored','dead')),
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_epoch INTEGER NOT NULL DEFAULT 0,
  lease_until INTEGER,
  error_code TEXT,
  received_epoch INTEGER NOT NULL,
  processed_epoch INTEGER
);
CREATE INDEX billing_inbox_status ON billing_inbox(status,next_attempt_epoch);
CREATE TABLE billing_operations (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('create_customer','create_checkout','create_portal')),
  idempotency_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK(state IN ('pending','applied','uncertain')),
  provider_ref TEXT,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL
);
