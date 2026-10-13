--
-- PostgreSQL database dump
--

\restrict daT2wdeTsPaMllNaosRpSZGYaHg1e3Vpyb2ZI5TWok8jnXp4bW4GTeTibYaV0I7

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

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
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    display_name text NOT NULL,
    email public.citext,
    participation_type text NOT NULL,
    status text DEFAULT 'ACTIVE'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT account_participation_type_check CHECK ((participation_type = ANY (ARRAY['OPERATOR'::text, 'SWL'::text])))
);


--
-- Name: account_credential; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_credential (
    account_id uuid NOT NULL,
    password_hash text NOT NULL,
    password_changed_at timestamp with time zone DEFAULT now() NOT NULL,
    failed_attempts integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone
);


--
-- Name: account_primary_callsign; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_primary_callsign (
    account_id uuid NOT NULL,
    callsign_id uuid NOT NULL
);


--
-- Name: account_recovery_token; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_recovery_token (
    token_hash text NOT NULL,
    account_id uuid NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone
);


--
-- Name: account_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_role (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid NOT NULL,
    programme_id uuid,
    role_code text NOT NULL,
    jurisdiction_id uuid,
    entity_type_code text,
    scopes jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    valid_to timestamp with time zone
);


--
-- Name: activation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    programme_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    operator_id uuid NOT NULL,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone,
    status text DEFAULT 'OPEN'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: approver_scope; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approver_scope (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid NOT NULL,
    programme_id uuid NOT NULL,
    jurisdiction_id uuid,
    entity_type_code text,
    scope jsonb DEFAULT '{}'::jsonb NOT NULL,
    valid_from timestamp with time zone DEFAULT now() NOT NULL,
    valid_to timestamp with time zone
);


--
-- Name: audit_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone
);


--
-- Name: auth_revocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_revocation (
    jti uuid NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: auth_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_session (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid NOT NULL,
    refresh_token_hash text NOT NULL,
    access_jti uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    user_agent text,
    remote_addr inet
);


--
-- Name: award; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.award (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    programme_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'ACTIVE'::text NOT NULL
);


--
-- Name: award_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.award_rule (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    award_id uuid NOT NULL,
    version integer NOT NULL,
    configuration jsonb NOT NULL,
    effective_from timestamp with time zone DEFAULT now() NOT NULL,
    retired_at timestamp with time zone
);


--
-- Name: callsign; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.callsign (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid NOT NULL,
    value text NOT NULL,
    lifecycle_status text DEFAULT 'UNVERIFIED'::text NOT NULL,
    verification_source text,
    verified_at timestamp with time zone,
    valid_from timestamp with time zone,
    valid_to timestamp with time zone,
    CONSTRAINT callsign_lifecycle_status_check CHECK ((lifecycle_status = ANY (ARRAY['UNVERIFIED'::text, 'VERIFIED'::text, 'RETIRED'::text])))
);


--
-- Name: callsign_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.callsign_evidence (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    callsign_id uuid NOT NULL,
    submitted_by uuid,
    evidence_type text NOT NULL,
    source text NOT NULL,
    checksum text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'PENDING'::text NOT NULL,
    submitted_at timestamp with time zone DEFAULT now() NOT NULL,
    reviewed_at timestamp with time zone
);


--
-- Name: consumer_checkpoint; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumer_checkpoint (
    consumer text NOT NULL,
    last_event_id uuid,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: consumer_processed_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumer_processed_event (
    consumer text NOT NULL,
    event_id uuid NOT NULL,
    processed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dead_letter_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dead_letter_event (
    event_id uuid NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    attempts integer NOT NULL,
    error text,
    dead_lettered_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: idempotency_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.idempotency_record (
    service text NOT NULL,
    key text NOT NULL,
    response jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: jurisdiction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jurisdiction (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    programme_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    parent_id uuid,
    external_reference jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: oidc_provider_mapping; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oidc_provider_mapping (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    programme_id uuid NOT NULL,
    issuer text NOT NULL,
    client_id text NOT NULL,
    configuration jsonb DEFAULT '{}'::jsonb NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: outbox_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox_event (
    event_id uuid NOT NULL,
    event_type text NOT NULL,
    producer text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    payload jsonb NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    available_at timestamp with time zone DEFAULT now() NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    published_at timestamp with time zone,
    last_error text,
    correlation_id text,
    CONSTRAINT outbox_event_correlation_id_length_check CHECK (((correlation_id IS NULL) OR (((length(correlation_id) >= 1) AND (length(correlation_id) <= 128)) AND (correlation_id !~ '[^!-~]'::text))))
);


--
-- Name: outbox_redrive_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox_redrive_audit (
    id bigint NOT NULL,
    event_id uuid NOT NULL,
    actor text NOT NULL,
    reason text NOT NULL,
    previous_attempts integer NOT NULL,
    previous_error text,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT outbox_redrive_audit_actor_check CHECK (((length(actor) >= 1) AND (length(actor) <= 120))),
    CONSTRAINT outbox_redrive_audit_reason_check CHECK (((length(reason) >= 1) AND (length(reason) <= 500)))
);


--
-- Name: outbox_redrive_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.outbox_redrive_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: outbox_redrive_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.outbox_redrive_audit_id_seq OWNED BY public.outbox_redrive_audit.id;


--
-- Name: programme; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.programme (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    theme jsonb DEFAULT '{}'::jsonb NOT NULL,
    oidc_config jsonb,
    status text DEFAULT 'ACTIVE'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: programme_policy_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.programme_policy_version (
    programme_id uuid NOT NULL,
    version integer NOT NULL,
    policy jsonb NOT NULL,
    effective_from timestamp with time zone DEFAULT now() NOT NULL,
    retired_at timestamp with time zone
);


--
-- Name: programme_rule; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.programme_rule (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    programme_id uuid NOT NULL,
    version integer NOT NULL,
    rule_code text NOT NULL,
    configuration jsonb NOT NULL,
    effective_from timestamp with time zone DEFAULT now() NOT NULL,
    retired_at timestamp with time zone
);


--
-- Name: qso; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qso (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    activation_id uuid NOT NULL,
    worked_callsign text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    band text,
    mode text,
    rst text,
    source text DEFAULT 'manual'::text NOT NULL
);


--
-- Name: security_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.security_event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    account_id uuid,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: service_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.service_state (
    service text NOT NULL,
    state jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: outbox_redrive_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_redrive_audit ALTER COLUMN id SET DEFAULT nextval('public.outbox_redrive_audit_id_seq'::regclass);


--
-- Name: account_credential account_credential_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_credential
    ADD CONSTRAINT account_credential_pkey PRIMARY KEY (account_id);


--
-- Name: account account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT account_pkey PRIMARY KEY (id);


--
-- Name: account_primary_callsign account_primary_callsign_callsign_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_primary_callsign
    ADD CONSTRAINT account_primary_callsign_callsign_id_key UNIQUE (callsign_id);


--
-- Name: account_primary_callsign account_primary_callsign_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_primary_callsign
    ADD CONSTRAINT account_primary_callsign_pkey PRIMARY KEY (account_id);


--
-- Name: account_recovery_token account_recovery_token_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_recovery_token
    ADD CONSTRAINT account_recovery_token_pkey PRIMARY KEY (token_hash);


--
-- Name: account_role account_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_role
    ADD CONSTRAINT account_role_pkey PRIMARY KEY (id);


--
-- Name: activation activation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activation
    ADD CONSTRAINT activation_pkey PRIMARY KEY (id);


--
-- Name: approver_scope approver_scope_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approver_scope
    ADD CONSTRAINT approver_scope_pkey PRIMARY KEY (id);


--
-- Name: audit_event audit_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_event
    ADD CONSTRAINT audit_event_pkey PRIMARY KEY (id);


--
-- Name: auth_revocation auth_revocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_revocation
    ADD CONSTRAINT auth_revocation_pkey PRIMARY KEY (jti);


--
-- Name: auth_session auth_session_access_jti_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_access_jti_key UNIQUE (access_jti);


--
-- Name: auth_session auth_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_pkey PRIMARY KEY (id);


--
-- Name: auth_session auth_session_refresh_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_refresh_token_hash_key UNIQUE (refresh_token_hash);


--
-- Name: award award_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.award
    ADD CONSTRAINT award_pkey PRIMARY KEY (id);


--
-- Name: award award_programme_id_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.award
    ADD CONSTRAINT award_programme_id_code_key UNIQUE (programme_id, code);


--
-- Name: award_rule award_rule_award_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.award_rule
    ADD CONSTRAINT award_rule_award_id_version_key UNIQUE (award_id, version);


--
-- Name: award_rule award_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.award_rule
    ADD CONSTRAINT award_rule_pkey PRIMARY KEY (id);


--
-- Name: callsign callsign_account_id_value_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callsign
    ADD CONSTRAINT callsign_account_id_value_key UNIQUE (account_id, value);


--
-- Name: callsign_evidence callsign_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callsign_evidence
    ADD CONSTRAINT callsign_evidence_pkey PRIMARY KEY (id);


--
-- Name: callsign callsign_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callsign
    ADD CONSTRAINT callsign_pkey PRIMARY KEY (id);


--
-- Name: consumer_checkpoint consumer_checkpoint_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_checkpoint
    ADD CONSTRAINT consumer_checkpoint_pkey PRIMARY KEY (consumer);


--
-- Name: consumer_processed_event consumer_processed_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_processed_event
    ADD CONSTRAINT consumer_processed_event_pkey PRIMARY KEY (consumer, event_id);


--
-- Name: dead_letter_event dead_letter_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dead_letter_event
    ADD CONSTRAINT dead_letter_event_pkey PRIMARY KEY (event_id);


--
-- Name: idempotency_record idempotency_record_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_record
    ADD CONSTRAINT idempotency_record_pkey PRIMARY KEY (service, key);


--
-- Name: jurisdiction jurisdiction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jurisdiction
    ADD CONSTRAINT jurisdiction_pkey PRIMARY KEY (id);


--
-- Name: jurisdiction jurisdiction_programme_id_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jurisdiction
    ADD CONSTRAINT jurisdiction_programme_id_code_key UNIQUE (programme_id, code);


--
-- Name: oidc_provider_mapping oidc_provider_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_provider_mapping
    ADD CONSTRAINT oidc_provider_mapping_pkey PRIMARY KEY (id);


--
-- Name: oidc_provider_mapping oidc_provider_mapping_programme_id_issuer_client_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_provider_mapping
    ADD CONSTRAINT oidc_provider_mapping_programme_id_issuer_client_id_key UNIQUE (programme_id, issuer, client_id);


--
-- Name: outbox_event outbox_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_event
    ADD CONSTRAINT outbox_event_pkey PRIMARY KEY (event_id);


--
-- Name: outbox_redrive_audit outbox_redrive_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_redrive_audit
    ADD CONSTRAINT outbox_redrive_audit_pkey PRIMARY KEY (id);


--
-- Name: programme programme_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme
    ADD CONSTRAINT programme_pkey PRIMARY KEY (id);


--
-- Name: programme_policy_version programme_policy_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_policy_version
    ADD CONSTRAINT programme_policy_version_pkey PRIMARY KEY (programme_id, version);


--
-- Name: programme_rule programme_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_rule
    ADD CONSTRAINT programme_rule_pkey PRIMARY KEY (id);


--
-- Name: programme_rule programme_rule_programme_id_rule_code_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_rule
    ADD CONSTRAINT programme_rule_programme_id_rule_code_version_key UNIQUE (programme_id, rule_code, version);


--
-- Name: programme programme_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme
    ADD CONSTRAINT programme_slug_key UNIQUE (slug);


--
-- Name: qso qso_activation_id_worked_callsign_occurred_at_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qso
    ADD CONSTRAINT qso_activation_id_worked_callsign_occurred_at_key UNIQUE (activation_id, worked_callsign, occurred_at);


--
-- Name: qso qso_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qso
    ADD CONSTRAINT qso_pkey PRIMARY KEY (id);


--
-- Name: security_event security_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.security_event
    ADD CONSTRAINT security_event_pkey PRIMARY KEY (id);


--
-- Name: service_state service_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_state
    ADD CONSTRAINT service_state_pkey PRIMARY KEY (service);


--
-- Name: account_role_scope_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX account_role_scope_idx ON public.account_role USING btree (account_id, programme_id, valid_to);


--
-- Name: audit_event_unpublished_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_event_unpublished_idx ON public.audit_event USING btree (published_at) WHERE (published_at IS NULL);


--
-- Name: auth_session_account_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_session_account_idx ON public.auth_session USING btree (account_id, revoked_at);


--
-- Name: outbox_dead_letter_unresolved_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX outbox_dead_letter_unresolved_idx ON public.dead_letter_event USING btree (dead_lettered_at) WHERE (resolved_at IS NULL);


--
-- Name: outbox_pending_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX outbox_pending_idx ON public.outbox_event USING btree (available_at, occurred_at) WHERE (published_at IS NULL);


--
-- Name: outbox_redrive_audit_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX outbox_redrive_audit_event_idx ON public.outbox_redrive_audit USING btree (event_id, requested_at DESC);


--
-- Name: account_credential account_credential_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_credential
    ADD CONSTRAINT account_credential_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: account_primary_callsign account_primary_callsign_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_primary_callsign
    ADD CONSTRAINT account_primary_callsign_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: account_primary_callsign account_primary_callsign_callsign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_primary_callsign
    ADD CONSTRAINT account_primary_callsign_callsign_id_fkey FOREIGN KEY (callsign_id) REFERENCES public.callsign(id);


--
-- Name: account_recovery_token account_recovery_token_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_recovery_token
    ADD CONSTRAINT account_recovery_token_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: account_role account_role_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_role
    ADD CONSTRAINT account_role_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: account_role account_role_jurisdiction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_role
    ADD CONSTRAINT account_role_jurisdiction_id_fkey FOREIGN KEY (jurisdiction_id) REFERENCES public.jurisdiction(id);


--
-- Name: account_role account_role_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account_role
    ADD CONSTRAINT account_role_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: activation activation_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activation
    ADD CONSTRAINT activation_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.account(id);


--
-- Name: activation activation_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activation
    ADD CONSTRAINT activation_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: approver_scope approver_scope_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approver_scope
    ADD CONSTRAINT approver_scope_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: approver_scope approver_scope_jurisdiction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approver_scope
    ADD CONSTRAINT approver_scope_jurisdiction_id_fkey FOREIGN KEY (jurisdiction_id) REFERENCES public.jurisdiction(id);


--
-- Name: approver_scope approver_scope_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approver_scope
    ADD CONSTRAINT approver_scope_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: auth_session auth_session_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: award award_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.award
    ADD CONSTRAINT award_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: award_rule award_rule_award_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.award_rule
    ADD CONSTRAINT award_rule_award_id_fkey FOREIGN KEY (award_id) REFERENCES public.award(id);


--
-- Name: callsign callsign_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callsign
    ADD CONSTRAINT callsign_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- Name: callsign_evidence callsign_evidence_callsign_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callsign_evidence
    ADD CONSTRAINT callsign_evidence_callsign_id_fkey FOREIGN KEY (callsign_id) REFERENCES public.callsign(id);


--
-- Name: callsign_evidence callsign_evidence_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.callsign_evidence
    ADD CONSTRAINT callsign_evidence_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.account(id);


--
-- Name: jurisdiction jurisdiction_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jurisdiction
    ADD CONSTRAINT jurisdiction_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.jurisdiction(id);


--
-- Name: jurisdiction jurisdiction_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jurisdiction
    ADD CONSTRAINT jurisdiction_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: oidc_provider_mapping oidc_provider_mapping_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_provider_mapping
    ADD CONSTRAINT oidc_provider_mapping_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: programme_policy_version programme_policy_version_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_policy_version
    ADD CONSTRAINT programme_policy_version_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: programme_rule programme_rule_programme_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.programme_rule
    ADD CONSTRAINT programme_rule_programme_id_fkey FOREIGN KEY (programme_id) REFERENCES public.programme(id);


--
-- Name: qso qso_activation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qso
    ADD CONSTRAINT qso_activation_id_fkey FOREIGN KEY (activation_id) REFERENCES public.activation(id);


--
-- Name: security_event security_event_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.security_event
    ADD CONSTRAINT security_event_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.account(id);


--
-- PostgreSQL database dump complete
--

\unrestrict daT2wdeTsPaMllNaosRpSZGYaHg1e3Vpyb2ZI5TWok8jnXp4bW4GTeTibYaV0I7


-- Record that this immutable schema baseline has been installed or adopted.
CREATE TABLE public.myota_schema_migration (
  migration_id text PRIMARY KEY,
  checksum text,
  application_mode text NOT NULL CHECK (application_mode IN ('applied', 'adopted')),
  applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.myota_schema_migration (migration_id, application_mode)
VALUES ('baseline-v1', 'applied');
