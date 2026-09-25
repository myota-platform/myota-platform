# MyOTA Outdoor Activation Platform

MyOTA is a programme-agnostic platform for outdoor activation programmes. MPOTA is represented as a configured programme, not as the platform itself. No rules or charter text are copied from POTA or any other programme: every programme supplies its own configuration, policy, eligibility, awards and public charter.

This repository is a runnable vertical-slice bootstrap for the service repositories described in [`docs/repository-map.md`](docs/repository-map.md). It contains four independently runnable Python services, an API-first contract, a universal browser UI, PostGIS migrations, and Kubernetes/Helm deployment assets.

## What works now

- Amateur-radio-aware identity: operator/SWL participation, multiple callsigns, one primary callsign, lifecycle and verification fields.
- Shared entity-category catalogue used by imports and review, with programme assignment and programme-owned rules handled separately.
- Geodata lifecycle: imported candidate → community proposal → approver review → approved entity.
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
python3 -m unittest discover -s tests -v
python3 services/dev_server.py
```

Open <http://127.0.0.1:8080>. The Compose stack starts the four services on
ports 8001–8004 and proxies the browser API calls. Use the dependency-free
`dev_server.py` process only for tests; it is not a durable runtime unless
database URLs and `MYOTA_REQUIRE_DURABILITY=1` are supplied explicitly.

For a containerized PostGIS environment, use `docker compose up --build` after starting Colima. The image uses the same service code with `SERVICE=identity|programmes|geodata|activity`.

## Architecture

Read [`docs/architecture.md`](docs/architecture.md), [`docs/adr/0001-storage-topology.md`](docs/adr/0001-storage-topology.md), and [`docs/repository-map.md`](docs/repository-map.md). The current bootstrap is kept together to make the vertical slice easy to run; the repository map defines the justified GitHub split once the MyOTA organization is available.

## Source project

The original `ea7klk/mpota` repository remains untouched. Its charter and planned flows are treated as the migration source; see [`docs/migration-from-mpota.md`](docs/migration-from-mpota.md).
