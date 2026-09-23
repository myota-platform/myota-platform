# ADR-0001: Two databases on one PostgreSQL cluster initially

## Decision

Use PostgreSQL/PostGIS as a core platform capability, with `myota_core` for transactional domain data and `myota_geo` for geometry/import/review data. Run both on one PostgreSQL cluster at first; allow a later move of `myota_geo` to its own cluster without changing service APIs.

## Why

Geodata has different workload characteristics: large bulk imports, spatial indexes, geometry-heavy backups, conflation jobs and map reads. Transactional data has smaller row payloads, stricter relational consistency and a different recovery priority. Separate databases provide operational isolation and a clear ownership boundary while one cluster keeps early operations, cost and connection management simple.

## Alternatives considered

- One database/schema: simplest operations, but bulk imports and spatial maintenance can compete with logins/activations; backup/restore cannot be isolated.
- Separate cluster from day one: strongest failure and scaling isolation, but doubles baseline operations for a small deployment.
- Non-PostGIS geodata store: rejected because geometry validation, spatial indexes, conflation and graphical editing are first-class requirements.

## Consequences

Cross-database relations are opaque IDs and events, not foreign keys. A later cluster split is operationally straightforward but requires event/retry monitoring. QGIS and browser admin tools connect to `myota_geo` with a least-privilege editing role; public APIs expose reviewed records only.

