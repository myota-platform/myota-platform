# Contract generation and compatibility

The repository's `openapi.yaml` is the versioned source of truth for HTTP contracts. The checked-
in `python/myota_client.py` is a dependency-light client for local integration;
production SDKs should be regenerated in CI with the pinned OpenAPI Generator
version selected by the consuming repository.

The repository-root `openapi.yaml` and `myota-platform/contracts/openapi.yaml`
files are generated mirrors. Do not edit them directly; run
`python3 scripts/sync_contract_mirrors.py --platform-root ../myota-platform`

The event registry and JSON Schemas in `event-registry.json` and `schemas/`
are authoritative here. The mirror sync copies them to `myota-platform` along
with `events.md`. Each fact records its producer source files relative to the
owning repository. The 19 Identity, 12 Programme, 10 Activity, and 27 Geodata fact payloads have
source-derived schemas from their authoritative producer call sites; schemas allow additive
fields and record data classification. Dynamic rule/configuration and nested
award asset shapes remain unconstrained when producer inputs are extensible.
The delegated Phase 1 review has dispositioned all 68 source-derived fact schemas as
inventory contracts, with producer enforcement still conditional on minimal
projections, prohibited-field and payload-size checks, compatibility fixtures,
and consumer evidence. See the [joint review record](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/evidence/phase1-joint-review-2026-10-10.md).
The Geodata preprocessing fact still carries the full result, including internal
`_records` and `_status`; keep v1 source-accurate and introduce a compact versioned
projection before enforcement. The Phase 0 audit found no Operations fact
producer, so no Operations payload schema is required unless that service begins
publishing facts. Run
`python3 scripts/audit_workspace_event_sources.py --workspace-root ..` from a
full workspace to verify source references and ensure Python event-like source
literals have a fact or legacy-work disposition.

Geodata payloads use the shared Master data category catalogue: `entityTypes` is
an ordered, non-empty list, `entityTypeCodes` is a compatibility alias, and
singular `entityType` is deprecated. The first category remains the compatibility
primary; all category assignments are authoritative in the geodata service
relation. Imports do not require a programme and first produce pre-processed
records; administrator promotion explicitly produces CANDIDATE or APPROVED
entities.

Compatibility rules:

- Additive request/response fields are compatible within `/v1`.
- Removing or changing a field requires `/v2` or an explicit deprecation window
  with `Deprecation` and `Sunset` response headers.
- Event names carry their schema version (`*.v1`); consumers reject unknown
  major versions and may accept additive fields.
- Every mutating request supports `Idempotency-Key`; every response carries
  request/correlation IDs.

CI should run an OpenAPI linter, server/client generation, and a breaking-change
diff against the last released contract before publishing a service image.

The proposed REST resource consolidation and compatibility migration is
documented in the
[myota-docs REST API consolidation plan](https://github.com/myota-platform/myota-docs/blob/main/docs/api-rest-consolidation-plan.md).
This file remains contract guidance only; no route changes have been made.
