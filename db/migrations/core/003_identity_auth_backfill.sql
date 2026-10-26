-- Copy the current Identity JSONB aggregate into the normalized Core tables.
-- The schema migration is applied first. This migration and its completion
-- marker commit atomically, so a failed run can be retried from the snapshot.

DO $$
DECLARE
  legacy jsonb;
  source_counts jsonb;
  target_counts jsonb;
  checksum text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM public.identity_auth_state_migration
     WHERE migration_name = 'service-state-jsonb-v1'
  ) THEN
    RETURN;
  END IF;

  SELECT state INTO legacy
    FROM public.service_state
   WHERE service = 'identity'
   FOR UPDATE;
  legacy := coalesce(legacy, '{}'::jsonb);

  IF jsonb_typeof(legacy->'items') NOT IN ('object', 'null')
     OR jsonb_typeof(legacy->'data') NOT IN ('object', 'null') THEN
    RAISE EXCEPTION 'Identity service_state has an unsupported JSON shape';
  END IF;

  IF EXISTS (
    SELECT 1
      FROM jsonb_each(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb)) AS item(key, value)
     WHERE item.value ? 'email'
       AND item.value->'email' <> 'null'::jsonb
       AND nullif(btrim(item.value->>'email'), '') IS NULL
  ) THEN
    RAISE EXCEPTION
      'blank Identity email addresses in service_state prevent relational cutover';
  END IF;

  IF EXISTS (
    SELECT 1
      FROM jsonb_each(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb)) AS item(key, value)
     WHERE item.value->>'email' IS NOT NULL
     GROUP BY lower(btrim(item.value->>'email'))
    HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION
      'duplicate normalized Identity emails in service_state prevent relational cutover';
  END IF;

  INSERT INTO public.account (
    id, display_name, email, identity_email_key, participation_type, status,
    created_at, updated_at
  )
  SELECT (item.value->>'id')::uuid,
         item.value->>'displayName',
         nullif(lower(btrim(item.value->>'email')), ''),
         nullif(lower(btrim(item.value->>'email')), ''),
         item.value->>'participationType',
         coalesce(nullif(item.value->>'status', ''), 'ACTIVE'),
         coalesce(nullif(item.value->>'createdAt', '')::timestamptz, now()),
         coalesce(nullif(item.value->>'updatedAt', '')::timestamptz, now())
    FROM jsonb_each(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb)) AS item(key, value)
  ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    email = EXCLUDED.email,
    identity_email_key = EXCLUDED.identity_email_key,
    participation_type = EXCLUDED.participation_type,
    status = EXCLUDED.status,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at;

  INSERT INTO public.identity_account_profile (
    account_id, website_url, biography_markdown, profile_image_id,
    profile_image_media_type, profile_image_updated_at
  )
  SELECT (item.value->>'id')::uuid,
         nullif(item.value->>'websiteUrl', ''),
         nullif(item.value->>'biographyMarkdown', ''),
         nullif(item.value->'profileImage'->>'id', '')::uuid,
         nullif(item.value->'profileImage'->>'contentType', ''),
         nullif(item.value->'profileImage'->>'updatedAt', '')::timestamptz
    FROM jsonb_each(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb)) AS item(key, value)
   WHERE coalesce(item.value->>'websiteUrl', '') <> ''
      OR coalesce(item.value->>'biographyMarkdown', '') <> ''
      OR item.value->'profileImage' IS NOT NULL
        AND item.value->'profileImage' <> 'null'::jsonb
  ON CONFLICT (account_id) DO UPDATE SET
    website_url = EXCLUDED.website_url,
    biography_markdown = EXCLUDED.biography_markdown,
    profile_image_id = EXCLUDED.profile_image_id,
    profile_image_media_type = EXCLUDED.profile_image_media_type,
    profile_image_updated_at = EXCLUDED.profile_image_updated_at;

  INSERT INTO public.account_credential (
    account_id, password_hash, password_changed_at, failed_attempts, locked_until
  )
  SELECT entry.key::uuid,
         entry.value->>'passwordHash',
         coalesce(nullif(entry.value->>'passwordChangedAt', '')::timestamptz, now()),
         coalesce(nullif(entry.value->>'failedAttempts', '')::integer, 0),
         nullif(entry.value->>'lockedUntil', '')::timestamptz
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'credentials', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
   WHERE coalesce(entry.value->>'passwordHash', '') <> ''
  ON CONFLICT (account_id) DO UPDATE SET
    password_hash = EXCLUDED.password_hash,
    password_changed_at = EXCLUDED.password_changed_at,
    failed_attempts = EXCLUDED.failed_attempts,
    locked_until = EXCLUDED.locked_until;

  INSERT INTO public.identity_role_definition (
    role_code, display_name, description, scopes, is_system,
    created_at, updated_at
  )
  SELECT entry.key,
         coalesce(entry.value->>'name', entry.key),
         coalesce(entry.value->>'description', ''),
         ARRAY(SELECT jsonb_array_elements_text(coalesce(entry.value->'scopes', '[]'::jsonb))),
         coalesce((entry.value->>'system')::boolean, false),
         coalesce(nullif(entry.value->>'createdAt', '')::timestamptz, now()),
         coalesce(nullif(entry.value->>'updatedAt', '')::timestamptz, now())
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'roleDefinitions', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (role_code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    scopes = EXCLUDED.scopes,
    is_system = EXCLUDED.is_system,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at;

  INSERT INTO public.account_role (
    id, account_id, programme_slug, role_code, jurisdiction_code,
    entity_type_code, scopes, created_at, valid_to
  )
  SELECT (entry.value->>'id')::uuid,
         (entry.value->>'accountId')::uuid,
         nullif(entry.value->>'programmeSlug', ''),
         entry.value->>'role',
         nullif(entry.value->>'jurisdiction', ''),
         nullif(entry.value->>'entityType', ''),
         coalesce(entry.value->'scopes', '[]'::jsonb),
         coalesce(nullif(entry.value->>'createdAt', '')::timestamptz, now()),
         nullif(entry.value->>'validTo', '')::timestamptz
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'roles', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (id) DO UPDATE SET
    account_id = EXCLUDED.account_id,
    programme_slug = EXCLUDED.programme_slug,
    role_code = EXCLUDED.role_code,
    jurisdiction_code = EXCLUDED.jurisdiction_code,
    entity_type_code = EXCLUDED.entity_type_code,
    scopes = EXCLUDED.scopes,
    created_at = EXCLUDED.created_at,
    valid_to = EXCLUDED.valid_to;

  INSERT INTO public.callsign (
    id, account_id, value, lifecycle_status, verification_source,
    verified_at, valid_from, valid_to
  )
  SELECT (call.value->>'id')::uuid,
         (account.value->>'id')::uuid,
         call.value->>'value',
         coalesce(call.value->>'status', 'UNVERIFIED'),
         nullif(call.value->>'verificationSource', ''),
         nullif(call.value->>'verifiedAt', '')::timestamptz,
         nullif(call.value->>'validFrom', '')::timestamptz,
         nullif(call.value->>'validTo', '')::timestamptz
    FROM jsonb_each(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb)) AS account(key, value)
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(account.value->'callsigns', '[]'::jsonb)) AS call(value)
  ON CONFLICT (id) DO UPDATE SET
    account_id = EXCLUDED.account_id,
    value = EXCLUDED.value,
    lifecycle_status = EXCLUDED.lifecycle_status,
    verification_source = EXCLUDED.verification_source,
    verified_at = EXCLUDED.verified_at,
    valid_from = EXCLUDED.valid_from,
    valid_to = EXCLUDED.valid_to;

  INSERT INTO public.account_primary_callsign (account_id, callsign_id)
  SELECT (item.value->>'id')::uuid,
         (item.value->>'primaryCallsignId')::uuid
    FROM jsonb_each(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb)) AS item(key, value)
   WHERE nullif(item.value->>'primaryCallsignId', '') IS NOT NULL
  ON CONFLICT (account_id) DO UPDATE SET callsign_id = EXCLUDED.callsign_id;

  INSERT INTO public.callsign_evidence (
    id, callsign_id, submitted_by, evidence_type, source, checksum, metadata,
    status, submitted_at, reviewed_at
  )
  SELECT (entry.value->>'id')::uuid,
         (entry.value->>'callsignId')::uuid,
         CASE WHEN entry.value->>'accountId' ~* '^[0-9a-f-]{36}$'
              THEN (entry.value->>'accountId')::uuid END,
         entry.value->>'evidenceType',
         entry.value->>'source',
         nullif(entry.value->>'checksum', ''),
         coalesce(entry.value->'metadata', '{}'::jsonb),
         coalesce(entry.value->>'status', 'PENDING'),
         coalesce(nullif(entry.value->>'submittedAt', '')::timestamptz, now()),
         nullif(entry.value->>'reviewedAt', '')::timestamptz
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'callsignEvidence', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (id) DO UPDATE SET
    callsign_id = EXCLUDED.callsign_id,
    submitted_by = EXCLUDED.submitted_by,
    evidence_type = EXCLUDED.evidence_type,
    source = EXCLUDED.source,
    checksum = EXCLUDED.checksum,
    metadata = EXCLUDED.metadata,
    status = EXCLUDED.status,
    submitted_at = EXCLUDED.submitted_at,
    reviewed_at = EXCLUDED.reviewed_at;

  INSERT INTO public.auth_session (
    id, account_id, refresh_token_hash, access_jti, created_at, expires_at,
    revoked_at, user_agent, remote_addr
  )
  SELECT (entry.value->>'id')::uuid,
         (entry.value->>'accountId')::uuid,
         entry.value->>'refreshHash',
         (entry.value->>'accessJti')::uuid,
         coalesce(nullif(entry.value->>'createdAt', '')::timestamptz, now()),
         (entry.value->>'expiresAt')::timestamptz,
         nullif(entry.value->>'revokedAt', '')::timestamptz,
         nullif(entry.value->>'userAgent', ''),
         nullif(entry.value->>'remoteAddr', '')::inet
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'sessions', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (id) DO UPDATE SET
    account_id = EXCLUDED.account_id,
    refresh_token_hash = EXCLUDED.refresh_token_hash,
    access_jti = EXCLUDED.access_jti,
    created_at = EXCLUDED.created_at,
    expires_at = EXCLUDED.expires_at,
    revoked_at = EXCLUDED.revoked_at,
    user_agent = EXCLUDED.user_agent,
    remote_addr = EXCLUDED.remote_addr;

  INSERT INTO public.auth_revocation (jti, expires_at, revoked_at)
  SELECT entry.key::uuid,
         to_timestamp((entry.value->>'expiresAt')::double precision),
         now()
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'revokedJti', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (jti) DO UPDATE SET expires_at = EXCLUDED.expires_at;

  INSERT INTO public.account_recovery_token (token_hash, account_id, expires_at, used_at)
  SELECT entry.key,
         (entry.value->>'accountId')::uuid,
         (entry.value->>'expiresAt')::timestamptz,
         nullif(entry.value->>'usedAt', '')::timestamptz
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'recovery', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (token_hash) DO UPDATE SET
    account_id = EXCLUDED.account_id,
    expires_at = EXCLUDED.expires_at,
    used_at = EXCLUDED.used_at;

  INSERT INTO public.identity_login_rate_limit (
    key_hash, window_started_at, request_count, expires_at
  )
  SELECT encode(public.digest(entry.key, 'sha256'), 'hex'),
         to_timestamp((entry.value->>'windowStart')::double precision),
         coalesce((entry.value->>'count')::integer, 0),
         to_timestamp((entry.value->>'windowStart')::double precision) + interval '15 minutes'
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'rateLimits', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (key_hash) DO UPDATE SET
    window_started_at = EXCLUDED.window_started_at,
    request_count = EXCLUDED.request_count,
    expires_at = EXCLUDED.expires_at,
    updated_at = now();

  INSERT INTO public.identity_oidc_provider_mapping (
    id, programme_slug, issuer, client_id, scopes, enabled, created_at, updated_at
  )
  SELECT (entry.value->>'id')::uuid,
         entry.value->>'programmeSlug',
         entry.value->>'issuer',
         entry.value->>'clientId',
         ARRAY(SELECT jsonb_array_elements_text(coalesce(entry.value->'scopes', '[]'::jsonb))),
         coalesce((entry.value->>'enabled')::boolean, true),
         coalesce(nullif(entry.value->>'createdAt', '')::timestamptz, now()),
         coalesce(nullif(entry.value->>'updatedAt', '')::timestamptz, now())
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'oidcMappings', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (id) DO UPDATE SET
    programme_slug = EXCLUDED.programme_slug,
    issuer = EXCLUDED.issuer,
    client_id = EXCLUDED.client_id,
    scopes = EXCLUDED.scopes,
    enabled = EXCLUDED.enabled,
    created_at = EXCLUDED.created_at,
    updated_at = EXCLUDED.updated_at;

  INSERT INTO public.security_event (id, account_id, event_type, payload, occurred_at)
  SELECT (entry.value->>'id')::uuid,
         CASE WHEN coalesce(entry.value->'payload'->>'accountId', entry.value->'payload'->>'actorId') ~* '^[0-9a-f-]{36}$'
              THEN coalesce(entry.value->'payload'->>'accountId', entry.value->'payload'->>'actorId')::uuid END,
         entry.value->>'eventType',
         coalesce(entry.value->'payload', '{}'::jsonb),
         coalesce(nullif(entry.value->>'occurredAt', '')::timestamptz, now())
    FROM jsonb_each(coalesce(nullif(legacy->'data'->'securityEvents', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (id) DO UPDATE SET
    account_id = EXCLUDED.account_id,
    event_type = EXCLUDED.event_type,
    payload = EXCLUDED.payload,
    occurred_at = EXCLUDED.occurred_at;

  INSERT INTO public.outbox_event (
    event_id, event_type, producer, aggregate_type, aggregate_id, payload,
    occurred_at, correlation_id
  )
  SELECT (entry.value->>'eventId')::uuid,
         entry.value->>'eventType',
         coalesce(entry.value->>'producer', 'identity'),
         entry.value->'aggregate'->>'type',
         entry.value->'aggregate'->>'id',
         coalesce(entry.value->'payload', '{}'::jsonb),
         (entry.value->>'occurredAt')::timestamptz,
         nullif(entry.value->>'correlationId', '')
    FROM jsonb_array_elements(coalesce(nullif(legacy->'events', 'null'::jsonb), '[]'::jsonb)) AS entry(value)
  ON CONFLICT (event_id) DO NOTHING;

  INSERT INTO public.idempotency_record (service, key, response)
  SELECT 'identity', entry.key, entry.value
    FROM jsonb_each(coalesce(nullif(legacy->'idempotency', 'null'::jsonb), '{}'::jsonb)) AS entry(key, value)
  ON CONFLICT (service, key) DO UPDATE SET response = EXCLUDED.response;

  source_counts := jsonb_build_object(
    'accounts', (SELECT count(*) FROM jsonb_object_keys(coalesce(nullif(legacy->'items', 'null'::jsonb), '{}'::jsonb))),
    'credentials', (SELECT count(*) FROM jsonb_object_keys(coalesce(nullif(legacy->'data'->'credentials', 'null'::jsonb), '{}'::jsonb))),
    'roles', (SELECT count(*) FROM jsonb_object_keys(coalesce(nullif(legacy->'data'->'roles', 'null'::jsonb), '{}'::jsonb))),
    'sessions', (SELECT count(*) FROM jsonb_object_keys(coalesce(nullif(legacy->'data'->'sessions', 'null'::jsonb), '{}'::jsonb))),
    'recovery', (SELECT count(*) FROM jsonb_object_keys(coalesce(nullif(legacy->'data'->'recovery', 'null'::jsonb), '{}'::jsonb))),
    'events', jsonb_array_length(coalesce(nullif(legacy->'events', 'null'::jsonb), '[]'::jsonb))
  );
  target_counts := jsonb_build_object(
    'accounts', (SELECT count(*) FROM public.account),
    'credentials', (SELECT count(*) FROM public.account_credential),
    'roles', (SELECT count(*) FROM public.account_role),
    'sessions', (SELECT count(*) FROM public.auth_session),
    'recovery', (SELECT count(*) FROM public.account_recovery_token),
    'events', (SELECT count(*) FROM public.outbox_event WHERE producer = 'identity')
  );
  checksum := encode(public.digest(legacy::text, 'sha256'), 'hex');

  INSERT INTO public.identity_auth_state_migration (
    migration_name, source_sha256, source_counts, target_counts
  ) VALUES (
    'service-state-jsonb-v1', checksum, source_counts, target_counts
  );
END;
$$;
