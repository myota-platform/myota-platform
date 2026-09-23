# Security and threat notes

| Threat | Control |
|---|---|
| Callsign impersonation | Callsigns have lifecycle/verification state; only verified callsigns enter trusted claims; changes are audited. |
| Unauthorized approval | Approver scope is programme/jurisdiction/entity-type specific and checked by the geodata service. |
| Malicious geometry or import flood | Validate GeoJSON/CRS/size, rate-limit imports, quarantine candidates, and run geometry validity checks before PostGIS insert. |
| Cross-programme data leakage | Programme ID is required on domain queries; service-owned repositories do not share tables; gateway scopes requests. |
| Replay/duplicate mutations | `Idempotency-Key`, unique source references and outbox event IDs make retries safe. |
| OIDC account takeover | OIDC is opt-in per programme and maps external subjects to internal accounts; it does not replace callsign verification. |
| Database compromise | Separate core/geo credentials, least-privilege QGIS role, encrypted secrets, private DB network, audited migrations and independent backups. |
| Sensitive log exposure | Do not log access tokens, email bodies or raw ADIF; use correlation IDs and structured operational metadata. |

The dependency-free slice intentionally omits production token signing, network policy and rate-limit middleware; those are deployment/service hardening tasks before public exposure.

