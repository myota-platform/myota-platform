# Identity, authentication and authorization

The identity service owns accounts, callsigns, credentials, sessions, roles,
scope grants, OIDC programme mappings, recovery tokens and security events. It
does not depend on Keycloak.

## Authentication

Registration requires a 12-character minimum password and supports both
`OPERATOR` and `SWL` accounts. Passwords use salted scrypt hashes. Login returns
a ten-minute HMAC-SHA-256 access token and a 30-day refresh token. Refresh is
rotating: the old session is revoked before a new refresh token is issued.
Logout, password recovery, deactivation and token revocation invalidate active
sessions. Recovery requests always return the same public response; development
tokens are only exposed outside production.

The signing key is supplied through `MYOTA_AUTH_SIGNING_KEY`. Production refuses
the built-in development key. Services that validate a token share the key
through a Kubernetes Secret, while service-to-service tokens are short-lived,
scope-limited tokens issued through the identity API.

## Callsigns and authorization

An account can have many callsigns but at most one active primary callsign.
Evidence records preserve type, source, checksum and metadata. A callsign cannot
be retired while primary without an active replacement. Verification requires
pending evidence and the `callsign.verify` scope.

Roles can be global or scoped to a programme, jurisdiction and entity type.
The geodata service checks the signed role claims before accepting a review; a
`GEO_APPROVER` grant for one programme or entity type cannot review another.
Roles and scope changes produce audit/security events.

Per-programme OIDC provider mappings store issuer, client ID, requested scopes
and enabled state. These mappings define the internal-account integration
boundary; provider secrets and authorization-code exchange belong in a future
provider adapter and deployment secret store, never in public programme config.

## Privacy and abuse controls

Accounts can export their account, roles, evidence and security events, or
deactivate with anonymization. Login attempts are rate-limited by email/IP,
failed credentials temporarily lock an account, and login/recovery/role/session
events are auditable through the durable outbox. Retention jobs should purge
expired recovery tokens, revoked sessions and security events according to the
deployment's policy.
