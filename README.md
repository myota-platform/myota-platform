# MyOTA Outdoor Activation Platform

MyOTA is a programme-agnostic platform for outdoor activation programmes. MPOTA is represented as a configured programme, not as the platform itself. No rules or charter text are copied from POTA or any other programme: every programme supplies its own configuration, policy, eligibility, awards and public charter.

The [MyOTA project charter](https://github.com/myota-platform/myota-docs/blob/main/docs/project-charter.md)
records the accessibility motivation and public positioning. The
[charter gap analysis](https://github.com/myota-platform/myota-docs/blob/main/docs/charter-gap-analysis.md)
distinguishes this integration bootstrap from the remaining public-launch and
production-readiness work.

This repository is the integration bootstrap and synchronized deployment
mirror. Domain implementations belong to the repositories in the
[repository map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md).
Production/local deployment is maintained in `myota-deploy`; identity,
programmes, geodata, activity and the read-only operations status service are
separate runtime components.

The integration copies include durable pull delivery for Activity notifications
and transactional geodata cancellation/finalization. The notification worker
can overlap during rollouts and drains on SIGTERM; cancelled imports discard
stale preprocessing projections under a row lock. See the
[operations runbook](https://github.com/myota-platform/myota-docs/blob/main/docs/operations.md#activity-notification-consumer-rollouts)
for rollout and retry behavior.

The synchronized outbox relay provisions the supported durable consumers
before publishing and configures `MYOTA_EVENTS` for Interest retention. A
message remains until every matching consumer acknowledges it, then is removed;
the 30-day maximum age is only a safety bound for a stalled backlog. Keep
consumer filters and explicit geodata queue subjects synchronized with the
[event contract](contracts/events.md).

## What works now

- Operational timestamps and publication inputs use UTC. Integration mirrors
  normalize effective dates, and Compose/dashboard settings default to UTC.
  See the [UTC policy](https://github.com/myota-platform/myota-docs/blob/main/docs/utc-time-policy.md).
- Activity/award integration mirrors the activity-owned handler, repository
  boundary and certificate renderer. Authenticated PNG/JPEG content and bounded
  mock PDF previews use the existing activity/gateway paths and port, not a new
  service. See the [designer guide](https://github.com/myota-platform/myota-docs/blob/main/docs/programme-and-award-design.md).
- Operations integration includes read-only SeaweedFS samples/history and
  live Identity API validation for per-user Grafana roles. GLOBAL_OPERATOR
  and GLOBAL_ADMIN map to Editor; other authorized readers remain Viewer.
  Service-owned storage migration 002 is mirrored as core migration 003.

- Geodata Phase 1 uses database-authoritative rows, revision conflicts, atomic
  audit/outbox writes, and a durable deletion consumer. Migration 016 fences
  old writers; new API/consumer images wait for it before accepting work.
- The admin UI's **NATS / JetStream** page uses authenticated operations APIs
  for real broker queues, consumers and seven days of sampled history.
  See the [status service guide](https://github.com/myota-platform/myota-docs/blob/main/docs/jetstream-admin-status.md).
- Amateur-radio-aware identity: operator/SWL participation, multiple callsigns, one primary callsign, lifecycle and verification fields.
- Shared entity-category catalogue used by imports and review, with programme assignment and programme-owned rules handled separately.
- Geodata lifecycle: adapter/import run or community proposal → pre-processing → administrator validation → CANDIDATE or APPROVED; normal review then permits CANDIDATE → APPROVED or REJECTED, and approved entities may only be RETIRED.
- Production geodata pipeline with ParkServe/OSM/government/manual adapters, immutable manifests, refresh schedules, geometry validation, conflation review, disappearance policy, QGIS staging, and bounded spatial/tile APIs.
- Activation and QSO primitives with idempotency keys and audit events.
- Universal themed frontend with verified/candidate map distinction.
- OpenAPI and event contracts, ADRs, migration notes, health endpoints and local deployment manifests.

Unit tests may use an in-memory adapter when they explicitly omit a database
URL. Local Compose enables `MYOTA_REQUIRE_DURABILITY=1` for every
database-backed service, so a missing PostgreSQL/PostGIS URL stops startup
instead of silently losing writes in process memory. Named database volumes
preserve local data between restarts.

## Run the vertical slice

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 services/dev_server.py
```

Open <http://127.0.0.1:8080> for the test harness. For the current durable
stack, run Compose from sibling `myota-deploy`; its admin UI is on port 8090,
domain APIs on 8001–8004 and read-only operations API on 8005. Use the dependency-free
`dev_server.py` process only for tests; it is not a durable runtime unless
database URLs and `MYOTA_REQUIRE_DURABILITY=1` are supplied explicitly.

For the complete durable environment, start Colima and follow the
[deployment README](https://github.com/myota-platform/myota-deploy#run-the-vertical-slice).
It runs three database containers, SeaweedFS, JetStream, independent domain
workers and the Vue UI. This repository retains integration mirrors, not the
authoritative domain implementations or operational deployment instructions.

## Architecture

Read the current [architecture](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture.md),
[storage topology ADR](https://github.com/myota-platform/myota-docs/blob/main/docs/adr/0001-storage-topology.md)
and [12-repository ownership map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md).
The [latest scaling delivery and evidence](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-horizontal-scaling-roadmap.md#latest-delivery-and-evidence--7-october-2026)
distinguishes verified database authority from open restart, memory, load and
canary gates. Local bootstrap docs are integration notes; `myota-docs` remains
the cross-repository architecture and roadmap authority.

## Source project

The original `ea7klk/mpota` repository remains untouched. Its charter and planned flows are treated as the migration source; see [`docs/migration-from-mpota.md`](docs/migration-from-mpota.md).
