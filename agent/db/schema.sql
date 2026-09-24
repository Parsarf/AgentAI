--
-- PostgreSQL database dump
--

\restrict ON8zhvX6RidD2JEcjHZEOrL4Gr4Pvjhcn0YSKNxbepv08f8HgVRZan3Q1mWifkM

-- Dumped from database version 16.15 (Homebrew)
-- Dumped by pg_dump version 16.15 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;


--
-- Name: EXTENSION citext; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION citext IS 'data type for case-insensitive character strings';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: api_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_costs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    task_id uuid,
    model text NOT NULL,
    input_tokens integer DEFAULT 0 NOT NULL,
    output_tokens integer DEFAULT 0 NOT NULL,
    cost_usd numeric(12,6) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    operation_key text
);


--
-- Name: approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approvals (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    task_id uuid,
    action_summary text NOT NULL,
    details_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_at timestamp with time zone,
    CONSTRAINT approvals_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'denied'::text, 'expired'::text])))
);


--
-- Name: auth_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    kind text NOT NULL,
    jti text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT auth_tokens_kind_check CHECK ((kind = ANY (ARRAY['verify_email'::text, 'password_reset'::text])))
);


--
-- Name: billing_operations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_operations (
    user_id uuid NOT NULL,
    kind text NOT NULL,
    operation_key text NOT NULL,
    provider_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: billing_warnings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_warnings (
    user_id uuid NOT NULL,
    period_start date NOT NULL,
    threshold integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: budget_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.budget_reservations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    task_id uuid,
    operation_key text NOT NULL,
    period_start date NOT NULL,
    amount_usd numeric(12,6) NOT NULL,
    state text DEFAULT 'reserved'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT budget_reservations_amount_usd_check CHECK ((amount_usd > (0)::numeric)),
    CONSTRAINT budget_reservations_state_check CHECK ((state = ANY (ARRAY['reserved'::text, 'settled'::text, 'unknown'::text])))
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    kind text NOT NULL,
    schedule text NOT NULL,
    check_mode text DEFAULT 'always'::text NOT NULL,
    check_script_path text,
    instruction text NOT NULL,
    state_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    active boolean DEFAULT true NOT NULL,
    created_by_task uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT jobs_check_mode_check CHECK ((check_mode = ANY (ARRAY['always'::text, 'on_change'::text]))),
    CONSTRAINT jobs_kind_check CHECK ((kind = ANY (ARRAY['recurring'::text, 'watcher'::text])))
);


--
-- Name: link_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.link_codes (
    code_hash text NOT NULL,
    user_id uuid NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    content text NOT NULL,
    category text DEFAULT 'general'::text NOT NULL,
    embedding public.vector(384),
    importance real DEFAULT 0.5 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);


--
-- Name: processed_stripe_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.processed_stripe_events (
    event_id text NOT NULL,
    event_type text NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: purchase_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    task_id text NOT NULL,
    task_source text NOT NULL,
    merchant text,
    amount_usd numeric(12,2),
    description text,
    outcome text NOT NULL,
    reason text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT purchase_attempts_outcome_check CHECK ((outcome = ANY (ARRAY['denied'::text, 'invalid'::text])))
);


--
-- Name: purchase_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.purchase_policies (
    user_id uuid NOT NULL,
    opted_in boolean DEFAULT false NOT NULL,
    per_transaction_cap_usd numeric(12,2) DEFAULT 0 NOT NULL,
    monthly_cap_usd numeric(12,2) DEFAULT 0 NOT NULL,
    merchant_allowlist text[] DEFAULT '{}'::text[] NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT purchase_policies_monthly_cap_usd_check CHECK ((monthly_cap_usd >= (0)::numeric)),
    CONSTRAINT purchase_policies_per_transaction_cap_usd_check CHECK ((per_transaction_cap_usd >= (0)::numeric))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version integer NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: skills_meta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills_meta (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    uses integer DEFAULT 0 NOT NULL,
    successes integer DEFAULT 0 NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    reviewed boolean DEFAULT true NOT NULL,
    last_used_at timestamp with time zone
);


--
-- Name: spend_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.spend_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    merchant text NOT NULL,
    amount numeric(12,2) NOT NULL,
    currency text DEFAULT 'usd'::text NOT NULL,
    approved_by text NOT NULL,
    status text NOT NULL,
    task_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    request text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    source text NOT NULL,
    parent_job_id uuid,
    steps_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    result text,
    cost_usd numeric(12,6) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    CONSTRAINT tasks_source_check CHECK ((source = ANY (ARRAY['user'::text, 'job'::text]))),
    CONSTRAINT tasks_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'awaiting_approval'::text, 'done'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: telegram_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.telegram_links (
    telegram_chat_id text NOT NULL,
    user_id uuid NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: usage_periods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_periods (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    total_cost numeric(12,6) DEFAULT 0 NOT NULL,
    included_allowance numeric(12,6) DEFAULT 0 NOT NULL,
    overage numeric(12,6) DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email public.citext NOT NULL,
    password_hash text,
    oauth_subject text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    plan_tier text DEFAULT 'free'::text NOT NULL,
    stripe_customer_id text,
    status text DEFAULT 'email_unverified'::text NOT NULL,
    user_limits_json jsonb,
    settings_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    timezone text DEFAULT 'UTC'::text NOT NULL,
    vault_mode text DEFAULT 'builtin'::text NOT NULL,
    billing_state text DEFAULT 'none'::text NOT NULL,
    stripe_subscription_id text,
    billing_grace_until timestamp with time zone,
    CONSTRAINT users_auth_present CHECK (((password_hash IS NOT NULL) OR (oauth_subject IS NOT NULL))),
    CONSTRAINT users_billing_state_check CHECK ((billing_state = ANY (ARRAY['none'::text, 'active'::text, 'trialing'::text, 'past_due'::text, 'unpaid'::text, 'canceled'::text]))),
    CONSTRAINT users_status_check CHECK ((status = ANY (ARRAY['email_unverified'::text, 'active'::text, 'suspended'::text, 'deleted'::text])))
);


--
-- Name: vault_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_entries (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    site text NOT NULL,
    encrypted_blob bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vault_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vault_keys (
    user_id uuid NOT NULL,
    wrapped_key bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: api_costs api_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_costs
    ADD CONSTRAINT api_costs_pkey PRIMARY KEY (id);


--
-- Name: approvals approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_pkey PRIMARY KEY (id);


--
-- Name: auth_tokens auth_tokens_jti_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_jti_key UNIQUE (jti);


--
-- Name: auth_tokens auth_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (id);


--
-- Name: billing_operations billing_operations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_operations
    ADD CONSTRAINT billing_operations_pkey PRIMARY KEY (user_id, kind, operation_key);


--
-- Name: billing_warnings billing_warnings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_warnings
    ADD CONSTRAINT billing_warnings_pkey PRIMARY KEY (user_id, period_start, threshold);


--
-- Name: budget_reservations budget_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_reservations
    ADD CONSTRAINT budget_reservations_pkey PRIMARY KEY (id);


--
-- Name: budget_reservations budget_reservations_user_id_operation_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_reservations
    ADD CONSTRAINT budget_reservations_user_id_operation_key_key UNIQUE (user_id, operation_key);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: link_codes link_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.link_codes
    ADD CONSTRAINT link_codes_pkey PRIMARY KEY (code_hash);


--
-- Name: memories memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_pkey PRIMARY KEY (id);


--
-- Name: processed_stripe_events processed_stripe_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.processed_stripe_events
    ADD CONSTRAINT processed_stripe_events_pkey PRIMARY KEY (event_id);


--
-- Name: purchase_attempts purchase_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_attempts
    ADD CONSTRAINT purchase_attempts_pkey PRIMARY KEY (id);


--
-- Name: purchase_policies purchase_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_policies
    ADD CONSTRAINT purchase_policies_pkey PRIMARY KEY (user_id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_token_hash_key UNIQUE (token_hash);


--
-- Name: skills_meta skills_meta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_meta
    ADD CONSTRAINT skills_meta_pkey PRIMARY KEY (id);


--
-- Name: skills_meta skills_meta_user_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_meta
    ADD CONSTRAINT skills_meta_user_id_name_key UNIQUE (user_id, name);


--
-- Name: spend_log spend_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spend_log
    ADD CONSTRAINT spend_log_pkey PRIMARY KEY (id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: telegram_links telegram_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_links
    ADD CONSTRAINT telegram_links_pkey PRIMARY KEY (telegram_chat_id);


--
-- Name: usage_periods usage_periods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_periods
    ADD CONSTRAINT usage_periods_pkey PRIMARY KEY (id);


--
-- Name: usage_periods usage_periods_user_id_period_start_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_periods
    ADD CONSTRAINT usage_periods_user_id_period_start_key UNIQUE (user_id, period_start);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_oauth_subject_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_oauth_subject_key UNIQUE (oauth_subject);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: vault_entries vault_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_entries
    ADD CONSTRAINT vault_entries_pkey PRIMARY KEY (id);


--
-- Name: vault_entries vault_entries_user_id_site_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_entries
    ADD CONSTRAINT vault_entries_user_id_site_key UNIQUE (user_id, site);


--
-- Name: vault_keys vault_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_keys
    ADD CONSTRAINT vault_keys_pkey PRIMARY KEY (user_id);


--
-- Name: idx_api_costs_time_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_costs_time_user ON public.api_costs USING btree (created_at, user_id);


--
-- Name: idx_api_costs_user_operation; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_api_costs_user_operation ON public.api_costs USING btree (user_id, operation_key) WHERE (operation_key IS NOT NULL);


--
-- Name: idx_api_costs_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_costs_user_time ON public.api_costs USING btree (user_id, created_at);


--
-- Name: idx_approvals_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_user_status ON public.approvals USING btree (user_id, status);


--
-- Name: idx_auth_tokens_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auth_tokens_user ON public.auth_tokens USING btree (user_id);


--
-- Name: idx_budget_reservations_user_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_budget_reservations_user_period ON public.budget_reservations USING btree (user_id, period_start, state);


--
-- Name: idx_jobs_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_due ON public.jobs USING btree (active, next_run_at);


--
-- Name: idx_jobs_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_user ON public.jobs USING btree (user_id);


--
-- Name: idx_link_codes_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_link_codes_user ON public.link_codes USING btree (user_id);


--
-- Name: idx_memories_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_embedding ON public.memories USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_memories_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_user ON public.memories USING btree (user_id);


--
-- Name: idx_purchase_attempts_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_purchase_attempts_user_created ON public.purchase_attempts USING btree (user_id, created_at DESC);


--
-- Name: idx_sessions_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_expires ON public.sessions USING btree (expires_at);


--
-- Name: idx_sessions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_user ON public.sessions USING btree (user_id);


--
-- Name: idx_spend_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_spend_user_time ON public.spend_log USING btree (user_id, created_at);


--
-- Name: idx_tasks_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_user_status ON public.tasks USING btree (user_id, status);


--
-- Name: idx_telegram_links_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telegram_links_user ON public.telegram_links USING btree (user_id);


--
-- Name: idx_users_stripe_customer; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_users_stripe_customer ON public.users USING btree (stripe_customer_id) WHERE (stripe_customer_id IS NOT NULL);


--
-- Name: idx_users_stripe_subscription; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_users_stripe_subscription ON public.users USING btree (stripe_subscription_id) WHERE (stripe_subscription_id IS NOT NULL);


--
-- Name: api_costs api_costs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_costs
    ADD CONSTRAINT api_costs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: approvals approvals_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: auth_tokens auth_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: billing_operations billing_operations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_operations
    ADD CONSTRAINT billing_operations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: billing_warnings billing_warnings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_warnings
    ADD CONSTRAINT billing_warnings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: budget_reservations budget_reservations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_reservations
    ADD CONSTRAINT budget_reservations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: jobs jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: link_codes link_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.link_codes
    ADD CONSTRAINT link_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: memories memories_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: purchase_attempts purchase_attempts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_attempts
    ADD CONSTRAINT purchase_attempts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: purchase_policies purchase_policies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.purchase_policies
    ADD CONSTRAINT purchase_policies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: skills_meta skills_meta_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_meta
    ADD CONSTRAINT skills_meta_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: spend_log spend_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spend_log
    ADD CONSTRAINT spend_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: tasks tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: telegram_links telegram_links_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_links
    ADD CONSTRAINT telegram_links_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: usage_periods usage_periods_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_periods
    ADD CONSTRAINT usage_periods_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: vault_entries vault_entries_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_entries
    ADD CONSTRAINT vault_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: vault_keys vault_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vault_keys
    ADD CONSTRAINT vault_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict ON8zhvX6RidD2JEcjHZEOrL4Gr4Pvjhcn0YSKNxbepv08f8HgVRZan3Q1mWifkM

