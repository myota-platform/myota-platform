# Production-grade platform core

Phase 1 uses a service-owned PostgreSQL boundary with a practical compatibility
projection (`service_state`) for the current vertical slice. Domain migrations
remain relational and are the target for replacing individual JSON projections as
each service grows. No service talks directly to another service's tables.

## Durability and events

The runtime selects PostgreSQL whenever `CORE_DATABASE_URL` or
`GEO_DATABASE_URL` is set. Psycopg's bounded connection pool provides one
transaction boundary per request, startup retries five times with exponential
backoff, and shutdown closes the pool. State, idempotency responses and events
are committed together. `outbox_event` is relayed by the core and geodata
workers to NATS JetStream. Claiming uses `FOR UPDATE SKIP LOCKED`, NATS message
deduplication uses the event ID, and repeated failures are delayed and then
written to `dead_letter_event`.

The current runtime event envelope is versioned by its `*.v1` event type. A
consumer must tolerate additive fields, reject incompatible schema versions, and
record a checkpoint/idempotency key before applying a side effect. The
`consumer_checkpoint` table is reserved for those consumers.

## API conventions

All responses include `X-Request-ID`, `X-Correlation-ID`, `API-Version: v1`, and
machine-readable problem details for errors. Collection endpoints return
`items`, `page`, `pageSize`, `total`, and `nextPage`; page size is capped at 100.
Request bodies are capped at 1 MiB. `Idempotency-Key` is persisted for mutating
requests. The canonical source is `contracts/openapi.yaml`; the checked-in
stdlib client under `contracts/python/` is a usable typed baseline while the
generator job is introduced.

## Migrations and recovery

Run `db/migrations/run.sh` once per deployment release. Helm executes it as a
pre-install/pre-upgrade hook; Compose runs the same script as a one-shot
`migrations` service. Apply additive migrations first, deploy code second, and
remove old columns only after all readers have moved. Rollbacks are release
specific: roll back application images first, restore a database only when a
backward-compatible application rollback is impossible.

`db/backup.sh` creates timestamped custom-format dumps for both databases;
`db/restore.sh` restores an explicitly selected pair. Restore into an isolated
environment, run migrations, start the services, exercise the health and sample
API flows, and record the recovery point/time before using it for production.

## Local stack

`docker compose -f compose.yaml up --build` starts PostGIS, migrations, four
services, the gateway, NATS JetStream, and two outbox relays. The first run
creates `myota_core` and `myota_geo`; a named volume preserves them across runs.
Use `docker compose -f compose.yaml run --rm migrations` after changing a
migration on an existing volume.
