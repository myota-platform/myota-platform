# Postgres/PostGIS storage layout

The production target is one PostgreSQL cluster with two databases:

- `myota_core`: identity, programme configuration, activations, QSOs, awards, permissions and audit/outbox data.
- `myota_geo`: geodata entities, geometries, source snapshots, import runs, conflation candidates and review records.

Migration `geo/003_production_pipeline.sql` adds immutable source manifests, refresh schedules, source-state/disappearance tracking, attachment metadata, conflation history, spatial indexes, and QGIS staging roles/views.

The databases share the cluster and operational tooling initially, but are isolated at the database boundary. This gives geodata its own backup/restore and scaling path without forcing a second cluster on a small deployment. Cross-service references use opaque UUIDs and events, never foreign keys across databases.

The migration SQL is intentionally compatible with a later move to separate PostgreSQL clusters. See ADR-0001 for the tradeoff analysis.
