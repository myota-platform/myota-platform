CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS account (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL,
  email citext,
  participation_type text NOT NULL CHECK (participation_type IN ('OPERATOR','SWL')),
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS callsign (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  value text NOT NULL,
  lifecycle_status text NOT NULL DEFAULT 'UNVERIFIED' CHECK (lifecycle_status IN ('UNVERIFIED','VERIFIED','RETIRED')),
  verification_source text,
  verified_at timestamptz,
  valid_from timestamptz,
  valid_to timestamptz,
  UNIQUE (account_id, value)
);

CREATE TABLE IF NOT EXISTS account_primary_callsign (
  account_id uuid PRIMARY KEY REFERENCES account(id),
  callsign_id uuid NOT NULL UNIQUE REFERENCES callsign(id)
);

CREATE TABLE IF NOT EXISTS programme (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  theme jsonb NOT NULL DEFAULT '{}'::jsonb,
  oidc_config jsonb,
  status text NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS programme_rule (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  programme_id uuid NOT NULL REFERENCES programme(id),
  version integer NOT NULL,
  rule_code text NOT NULL,
  configuration jsonb NOT NULL,
  effective_from timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz,
  UNIQUE (programme_id, rule_code, version)
);

CREATE TABLE IF NOT EXISTS award (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  programme_id uuid NOT NULL REFERENCES programme(id),
  code text NOT NULL,
  name text NOT NULL,
  description text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'ACTIVE',
  UNIQUE (programme_id, code)
);

CREATE TABLE IF NOT EXISTS award_rule (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  award_id uuid NOT NULL REFERENCES award(id),
  version integer NOT NULL,
  configuration jsonb NOT NULL,
  effective_from timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz,
  UNIQUE (award_id, version)
);

CREATE TABLE IF NOT EXISTS jurisdiction (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  programme_id uuid NOT NULL REFERENCES programme(id),
  code text NOT NULL,
  name text NOT NULL,
  parent_id uuid REFERENCES jurisdiction(id),
  external_reference jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (programme_id, code)
);

CREATE TABLE IF NOT EXISTS approver_scope (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  programme_id uuid NOT NULL REFERENCES programme(id),
  jurisdiction_id uuid REFERENCES jurisdiction(id),
  entity_type_code text,
  scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz
);

CREATE TABLE IF NOT EXISTS activation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  programme_id uuid NOT NULL REFERENCES programme(id),
  entity_id uuid NOT NULL,
  operator_id uuid NOT NULL REFERENCES account(id),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  status text NOT NULL DEFAULT 'OPEN',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qso (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  activation_id uuid NOT NULL REFERENCES activation(id),
  worked_callsign text NOT NULL,
  occurred_at timestamptz NOT NULL,
  band text,
  mode text,
  rst text,
  source text NOT NULL DEFAULT 'manual',
  UNIQUE (activation_id, worked_callsign, occurred_at)
);

CREATE TABLE IF NOT EXISTS audit_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);

CREATE INDEX IF NOT EXISTS audit_event_unpublished_idx ON audit_event (published_at) WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS service_state (
  service text PRIMARY KEY,
  state jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS idempotency_record (
  service text NOT NULL,
  key text NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (service, key)
);
CREATE TABLE IF NOT EXISTS outbox_event (
  event_id uuid PRIMARY KEY,
  event_type text NOT NULL,
  producer text NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id text NOT NULL,
  payload jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL DEFAULT now(),
  attempts integer NOT NULL DEFAULT 0,
  published_at timestamptz,
  last_error text
);
CREATE INDEX IF NOT EXISTS outbox_pending_idx ON outbox_event (available_at, occurred_at) WHERE published_at IS NULL;
CREATE TABLE IF NOT EXISTS consumer_checkpoint (
  consumer text PRIMARY KEY,
  last_event_id uuid,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS consumer_processed_event (
  consumer text NOT NULL,
  event_id uuid NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, event_id)
);
CREATE TABLE IF NOT EXISTS dead_letter_event (
  event_id uuid PRIMARY KEY,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  attempts integer NOT NULL,
  error text,
  dead_lettered_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS programme_policy_version (
  programme_id uuid NOT NULL REFERENCES programme(id),
  version integer NOT NULL,
  policy jsonb NOT NULL,
  effective_from timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz,
  PRIMARY KEY (programme_id, version)
);

CREATE TABLE IF NOT EXISTS account_credential (
  account_id uuid PRIMARY KEY REFERENCES account(id),
  password_hash text NOT NULL,
  password_changed_at timestamptz NOT NULL DEFAULT now(),
  failed_attempts integer NOT NULL DEFAULT 0,
  locked_until timestamptz
);

CREATE TABLE IF NOT EXISTS auth_session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  refresh_token_hash text NOT NULL UNIQUE,
  access_jti uuid NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  user_agent text,
  remote_addr inet
);
CREATE INDEX IF NOT EXISTS auth_session_account_idx ON auth_session (account_id, revoked_at);

CREATE TABLE IF NOT EXISTS auth_revocation (
  jti uuid PRIMARY KEY,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS account_recovery_token (
  token_hash text PRIMARY KEY,
  account_id uuid NOT NULL REFERENCES account(id),
  expires_at timestamptz NOT NULL,
  used_at timestamptz
);

CREATE TABLE IF NOT EXISTS callsign_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  callsign_id uuid NOT NULL REFERENCES callsign(id),
  submitted_by uuid REFERENCES account(id),
  evidence_type text NOT NULL,
  source text NOT NULL,
  checksum text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'PENDING',
  submitted_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz
);

CREATE TABLE IF NOT EXISTS account_role (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES account(id),
  programme_id uuid REFERENCES programme(id),
  role_code text NOT NULL,
  jurisdiction_id uuid REFERENCES jurisdiction(id),
  entity_type_code text,
  scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz
);
CREATE INDEX IF NOT EXISTS account_role_scope_idx ON account_role (account_id, programme_id, valid_to);

CREATE TABLE IF NOT EXISTS oidc_provider_mapping (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  programme_id uuid NOT NULL REFERENCES programme(id),
  issuer text NOT NULL,
  client_id text NOT NULL,
  configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (programme_id, issuer, client_id)
);

CREATE TABLE IF NOT EXISTS security_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES account(id),
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
