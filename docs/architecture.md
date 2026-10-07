# MyOTA platform architecture

These are integration-bootstrap notes. The current cross-repository
[architecture](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture.md)
and [scaling delivery checklist](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-horizontal-scaling-roadmap.md)
are maintained in `myota-docs`.

## Scope

MyOTA is an Outdoor Activation Platform. A programme is configuration and policy data consumed by platform capabilities. MPOTA is only an optional programme-configuration example; geodata seed entities are no longer replayed. Future programmes use the same APIs without cloning a codebase. The platform does not copy, inherit or silently normalize another programme's charter, rules, minimum QSOs, award logic or eligibility policy. Those are programme-owned inputs, versioned and auditable as configuration or programme code.

## Service boundaries

```mermaid
flowchart LR
  UI[Universal web frontend] --> G[API gateway / ingress]
  G --> I[Identity service\naccounts, callsigns, roles]
  G --> P[Programme service\nconfiguration, rules, themes]
  G --> Geo[Geodata service\nPostGIS, imports, review]
  G --> A[Activity service\nactivations, QSOs, awards]
  G --> Ops[Operations service\nread-only JetStream status]
  I -. events .-> Bus[(Event broker / outbox)]
  P -. events .-> Bus
  Geo -. events .-> Bus
  A -. events .-> Bus
  I --> C[(myota_core)]
  P --> C
  Ops --> C
  Ops -. metadata .-> Bus
  A --> ADB[(myota_activity\nPostgreSQL)]
  Geo --> D[(myota_geo\nPostGIS)]
  Admin[QGIS / browser map editor] --> Geo
  Bus --> Worker[Geodata-owned durable workers]
  Worker --> D
```

Each service owns its database tables and publishes events. No service reads another service's tables. The gateway/ingress is a routing boundary, not a domain owner.

Only `myota_geo` requires PostGIS; core and activity are separate plain
PostgreSQL containers. Geodata uses authoritative row repositories,
revision/If-Match conflicts and atomic audit/outbox changes. Migration 016
archives the old service snapshot and fences obsolete writers. API and worker
rollout must follow the [migration procedure](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-phase1-relational-authority.md#migration-and-rollout).

## Geodata lifecycle

```mermaid
flowchart TD
  S[Authoritative/imported source] --> R[Adapter + import run]
  R --> Pre[Durable pre-processing records]
  Pre --> Validate[Administrator selection and confirmation]
  Validate --> Queue[NATS promotion job]
  Queue --> C[CANDIDATE]
  Queue -->|Authorized direct approval| A[APPROVED]
  Q[Community proposal] --> C
  C -->|approver scope + review| A
  C -->|approver decision| X[REJECTED]
  A --> M[Public map + activation eligibility]
```

The UI distinguishes `APPROVED` from `CANDIDATE` and never exposes a candidate as a programme reference until approval. Import refreshes update source provenance and geometry while preserving review state; an explicit policy can leave a record unchanged, mark it stale, require review, or retire it when it disappears from an authoritative source. Approved entities remain historical references even when retired.

## Import adapters

The adapter interface is a normalized feature stream:

```text
discover(source_config) -> source snapshot metadata
read(snapshot) -> {source_record_id, name, geometry, properties, license}
normalize(feature) -> canonical geometry/properties
conflate(feature, existing) -> match candidates + score
apply(feature, policy) -> candidate/update/retire
```

Required adapters are represented in the contract and storage model: `PARKSERVE_US`, `OSM`, `GOVERNMENT_GIS`, and `MANUAL`. Government GIS source formats include WFS, GeoJSON, Shapefile and ArcGIS FeatureServer. ParkServe and government feeds remain source-specific integrations; OSM imports preserve ODbL attribution and retrieval metadata and filter to the programme-independent required outdoor-place tags. Manual proposals use the same entity/review path and do not bypass approval. Conflation decisions are append-only and can be reopened.

## Security and operations

- Short-lived access tokens are verified at the gateway; the identity service issues radio-native claims (`account_id`, participation type, verified callsigns, scopes).
- OAuth/OIDC is optional per programme configuration and is never the identity source of truth. External subject mappings point to an internal account.
- Approver authorization is scope-based: optional programme + jurisdiction + shared entity category. Platform-wide candidates can be reviewed before programme assignment; review mutations require an applicable approver scope and are audit events.
- Every mutation accepts `Idempotency-Key`; service outboxes make event publication retry-safe.
- Rate limits apply at gateway, with stricter limits for import and proposal endpoints.
- JSON logs carry request, correlation, actor and programme IDs. Health/readiness endpoints are available per service.
