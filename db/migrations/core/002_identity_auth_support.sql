-- Add the Identity-owned relational structures that are missing from the
-- original Core baseline. The JSONB service_state snapshot remains intact;
-- backfill and runtime cutover are separate forward migrations.

ALTER TABLE public.account
  ADD COLUMN IF NOT EXISTS identity_email_key text;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM public.account
     WHERE email IS NOT NULL
       AND length(btrim(email::text)) = 0
  ) THEN
    RAISE EXCEPTION
      'blank Identity email addresses prevent relational cutover';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM public.account
     WHERE email IS NOT NULL
     GROUP BY lower(btrim(email::text))
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION
      'duplicate normalized Identity email addresses prevent relational cutover';
  END IF;
END;
$$;

UPDATE public.account
   SET email = lower(btrim(email::text)),
       identity_email_key = lower(btrim(email::text))
 WHERE email IS NOT NULL;

UPDATE public.account
   SET identity_email_key = NULL
 WHERE email IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS account_normalized_email_uidx
  ON public.account (lower(btrim(identity_email_key)))
  WHERE email IS NOT NULL;

ALTER TABLE public.account_role
  ADD COLUMN IF NOT EXISTS programme_slug text,
  ADD COLUMN IF NOT EXISTS jurisdiction_code text;

CREATE TABLE IF NOT EXISTS public.identity_role_definition (
  role_code text PRIMARY KEY,
  display_name text NOT NULL,
  description text NOT NULL DEFAULT '',
  scopes text[] NOT NULL DEFAULT '{}',
  is_system boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identity_role_definition_code_nonempty
    CHECK (length(btrim(role_code)) > 0),
  CONSTRAINT identity_role_definition_name_nonempty
    CHECK (length(btrim(display_name)) > 0)
);

CREATE TABLE IF NOT EXISTS public.identity_account_profile (
  account_id uuid PRIMARY KEY REFERENCES public.account(id),
  website_url text,
  biography_markdown text,
  profile_image_id uuid,
  profile_image_media_type text,
  profile_image_updated_at timestamptz,
  CONSTRAINT identity_profile_image_pair_check CHECK (
    (profile_image_id IS NULL
      AND profile_image_media_type IS NULL
      AND profile_image_updated_at IS NULL)
    OR
    (profile_image_id IS NOT NULL
      AND profile_image_media_type = 'image/webp'
      AND profile_image_updated_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS public.identity_login_rate_limit (
  key_hash text PRIMARY KEY,
  window_started_at timestamptz NOT NULL,
  request_count integer NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identity_login_rate_limit_hash_check
    CHECK (length(key_hash) = 64 AND key_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT identity_login_rate_limit_count_check
    CHECK (request_count >= 0),
  CONSTRAINT identity_login_rate_limit_expiry_check
    CHECK (expires_at > window_started_at)
);

CREATE INDEX IF NOT EXISTS identity_login_rate_limit_expiry_idx
  ON public.identity_login_rate_limit (expires_at);

CREATE TABLE IF NOT EXISTS public.identity_oidc_provider_mapping (
  id uuid PRIMARY KEY,
  programme_slug text NOT NULL,
  issuer text NOT NULL,
  client_id text NOT NULL,
  scopes text[] NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identity_oidc_programme_slug_nonempty
    CHECK (length(btrim(programme_slug)) > 0),
  CONSTRAINT identity_oidc_issuer_nonempty
    CHECK (length(btrim(issuer)) > 0),
  CONSTRAINT identity_oidc_client_id_nonempty
    CHECK (length(btrim(client_id)) > 0)
);

CREATE TABLE IF NOT EXISTS public.identity_auth_state_migration (
  migration_name text PRIMARY KEY,
  source_sha256 text NOT NULL,
  source_counts jsonb NOT NULL,
  target_counts jsonb NOT NULL,
  completed_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identity_auth_migration_checksum_check
    CHECK (source_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS account_recovery_token_expiry_idx
  ON public.account_recovery_token (expires_at);

CREATE INDEX IF NOT EXISTS auth_revocation_expiry_idx
  ON public.auth_revocation (expires_at);
