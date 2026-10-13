# Database migrations and ownership

The deployment provisions three independent database targets. Identity and
Programme share 'myota_core'; Activity owns 'myota_activity'; Geodata owns
'myota_geo' with PostGIS. Cross-service relationships use opaque identifiers
and events. The migration runner never copies application rows between these
databases.

The authoritative sources are:

- Core: 'myota-deploy/db/migrations/core/001_core_baseline.sql'.
- Activity: 'myota-activity-service/migrations/001_activity_baseline.sql'.
- Geodata: 'myota-geodata-service/migrations/001_geodata_baseline.sql'.

Deploy contains synchronized Activity and Geodata copies; Platform mirrors the
runner, Compose configuration, and all three SQL files. The migration runner
checks SHA-256 checksums, applies a fresh baseline transactionally, adopts an
already-ready schema only after a database-specific sentinel check, and leaves
the readiness marker false on failure. It fails closed on checksum drift or an
unready database that already contains application relations. Future migrations
are numbered and recorded in 'public.myota_schema_migration'; applied baseline
files are immutable.

A baseline is schema-only and contains no domain rows. The
[database baseline inventory and rebuild procedure](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/databases/baseline-migration-inventory.md)
records captured schema evidence, source ownership, and the data-preserving
backup/restore gates. Backups and capacity planning remain independent for
each database target. Only Geodata requires PostGIS. The chart-managed
StatefulSets are single-replica and are not highly available.

