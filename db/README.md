# Postgres/PostGIS storage layout

The deployment uses three service-owned database targets:

- `myota_core` on plain PostgreSQL: identity, programme configuration, permissions, core audit/outbox data, and the operations service's JetStream status samples.
- `myota_activity` on plain PostgreSQL: activations, QSOs, aggregates, awards, activity jobs, and notifications.
- `myota_geo` on PostgreSQL with PostGIS: geodata entities, geometries, source snapshots, import runs, conflation candidates, review records, and relational entity-to-category assignments.

Local development uses three database containers; Helm can deploy three
persistent StatefulSets or use externally managed database endpoints. Only
`myota_geo` requires PostGIS. Keep backups, migrations, and capacity planning
independent for each database target. Cross-service references use opaque IDs
and events, never foreign keys across databases.

Core `002_operations.sql` mirrors the operations service's `001_operations.sql`.
Geo `019_maidenhead_locators.sql` is the current migration head. It mirrors
the geodata service migration and adds automatically calculated Maidenhead
coverage arrays. All shared geo migrations mirror the geodata service-owned
schema.

The migration runner discovers numbered `NNN_*.sql` files separately in each
domain directory and applies them in lexical order. Add a new numbered file to
the owning migration directory and synchronized copies; do not maintain a
second filename list in the runner.
Synchronize service-owned migration sources before modifying the runner; see
the [Phase 1 migration procedure](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-phase1-relational-authority.md).

The migration SQL is intentionally compatible with a later move to separate
PostgreSQL clusters. See the
[three-database migration ADR](https://github.com/myota-platform/myota-docs/blob/main/docs/adr/0007-three-database-migration.md)
for ownership and migration details.
