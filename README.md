# MyOTA Outdoor Activation Platform

MyOTA is a programme-agnostic platform for outdoor activation programmes. MPOTA is represented as a configured programme, not as the platform itself. No rules or charter text are copied from POTA or any other programme: every programme supplies its own configuration, policy, eligibility, awards and public charter.

The platform’s purpose and accessibility motivation are documented in the
[project charter](https://github.com/myota-platform/myota-docs/blob/main/docs/project-charter.md).
This repository supplies the durable local/production topology; it is not the
owner of programme rules or the participant product. Remaining launch gates
are tracked in the [charter gap analysis](https://github.com/myota-platform/myota-docs/blob/main/docs/charter-gap-analysis.md).

This repository owns Compose, Fleet/Helm, migration orchestration and
observability provisioning. Domain implementations remain in their service
repositories; `services/` contains synchronized integration copies.

The Activity notification consumer uses the registered exact-filter durable
`activity-notifications-v1`. Helm pre-upgrade provisioning and post-upgrade
legacy retirement are defined in the notification topology hooks. Its bounded
outcome metrics feed the OpenTelemetry Collector, Grafana dashboard and
Alertmanager rules; notification replay requires the audited Activity redrive
tool.
The shared `MYOTA_EVENTS` stream currently uses Interest retention, mixing facts
with legacy Geodata work. The 30-day maximum age is a backlog safety bound; the
stream is not a replay archive. Geodata cancellation persists lifecycle fields
through the row repository and locks finalization through candidate cleanup.
These fixes are mirrored in `services/` for integrated deployments. See the
[notification runbook](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/activity-notification-consumer.md)
for the legacy push-consumer handoff and cancellation guarantees.

NATS migration Phases 0–4 are complete within their recorded evidence bounds.
Phase 5 is in production cutover: the four Geodata work kinds use the
`MYOTA_GEODATA_WORK` WorkQueue, all four workers subscribe to their exact target
subjects, and migration 021 is applied. The retry-safe partial-deletion handler
is deployed on digest-pinned images. No accepted Geodata production work was
available to process. Helm revision 192 is deployed; Fleet is Ready=True at
Deploy commit `6443473828305ab9d02a918bbe990d01abe97f6a` with 60/60 resources. Four old durable definitions
remain empty and inactive during the rollback observation, anchored at 21:39:22 UTC on 10 October; the shared `MYOTA_EVENTS` stream and
Activity notification durable remain active. Fleet readiness, two-database cross-service failure qualification,
cancellation/expiry replay, and the five work-command recovery paths have been
verified in the recorded isolated run. The 24-hour rollback observation and
legacy durable retirement remain open. Keep migration 021 and authoritative
recovery rows; no obsolete Phase 5 database object was found to purge. NATS
remains cluster-internal without auth/TLS under the accepted single-tenant
boundary; off-node recovery is deferred. See the [provisioning runbook](docs/jetstream-topology.md),
[Phase 5 evidence](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/evidence/phase5-geodata-work-2026-10-10.md),
[migration plan](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/nats-event-migration-plan.md),
and [Phase 4 Activity runbook](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/activity-work-queues.md).

The geodata worker also consumes `myota.geodata.entity.location-enrichment.v1`
through durable consumer `geodata-location-enrichment-v1`. It performs
reverse-geocoding outside the API transaction and applies a result only when
the entity still has the geometry/request version used for the lookup. The
consumer ships in the geodata service image; no extra Deployment or database
container is required. Compose and Helm pass the configured optional
`BIGDATACLOUD_API_KEY` and language to both the API and worker.

## What works now

- All provisioned Grafana dashboards and its default timezone use UTC; retention
  CronJobs specify `Etc/UTC`. The three database/log timezones already use UTC.
  API effective dates and browser inputs are UTC, not programme-local times.
  See the [UTC policy](https://github.com/myota-platform/myota-docs/blob/main/docs/utc-time-policy.md).
- Named award artwork, authenticated binary asset content and transient mock
  PDF previews use the existing activity image/port 8004, S3 buckets and gateway.
  The synchronized renderer/handler changes require image rollouts only;
  Compose/Helm service topology and secrets remain unchanged. See the
  [programme/award design guide](https://github.com/myota-platform/myota-docs/blob/main/docs/programme-and-award-design.md).
- Amateur-radio-aware identity: operator/SWL participation, multiple callsigns, one primary callsign, lifecycle and verification fields.
- Shared entity-category catalogue used by imports and review, with programme assignment and programme-owned rules handled separately.
- Geodata lifecycle: adapter/import run or community proposal → pre-processing → administrator validation → CANDIDATE or APPROVED; normal review then permits CANDIDATE → APPROVED or REJECTED, and approved entities may only be RETIRED.
- Provenance-aware imports with adapter metadata for ParkServe, OSM, government GIS and manual proposals.
- Activation and QSO primitives with idempotency keys and audit events.
- Programme-owned hunter/activator awards, nested conditions, achievement levels, asset metadata and issuance requests are served by the activity service on the same port (8004).
- Universal themed frontend with verified/candidate map distinction.
- OpenAPI and event contracts, ADRs, migration notes, health endpoints and local deployment manifests.
- Phase 2 geodata resource aliases are deployed alongside the legacy routes:
  consolidated imports, proposals, metadata, categories, geometry, reviews,
  bbox-filtered entity collections, and confirmation-based deletion jobs. See
  the [Phase 2 resource model](https://github.com/myota-platform/myota-docs/blob/main/docs/api-phase2-geodata-resource-model.md).
- Phase 3 activity and award job resources are deployed on the shared activity
  API port 8004. The worker handles QSO ingestion, ADIF, statistics, award
  evaluation/recalculation, certificate rendering, notifications, and bounded
  retries. Participant mutations are owner-authorized, recalculation is rule-
  version scoped, and statistics rebuilds replace the current deterministic
  snapshot set. See the [Phase 3 job record](https://github.com/myota-platform/myota-docs/blob/main/docs/api-phase3-activity-award-jobs.md).

## Observability and Phase 4 operations

The Geodata API has a bounded scale profile in Helm: two minimum, three
maximum, CPU-based HPA, an API pod disruption budget, rolling-update surge,
best-effort pod spreading, and per-pod CPU/memory/database-pool bounds. Its
worker scales independently with a two-replica ceiling and queue-age/backlog
signals. The Spainip limits reserve database connections for migrations and
maintenance. Databases, SeaweedFS, and JetStream remain single-replica stateful
services; they are not made highly available by adding API pods. See the
[Phase 4 scaling record](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata/evidence/phase4-infrastructure-scaling-2026-10-09.md)
and the [deployment guide](deploy/helm/myota/DEPLOYMENT.md#geodata-api-replica-safety).

**SeaweedFS storage** (`/object-storage`) follows the NATS status-page pattern:
operations-owned samples/history, authenticated API access, read-only storage
health and native exporter gauges. Core migration 003 creates its history table.
Compose and Helm provide the health/metrics URLs and the live Identity API URL.
Helm overrides are `services.operations.storageHealthUrl`,
`services.operations.storageMetricsUrl` and `services.identity.internalUrl`.

Grafana now uses individual MyOTA identities. GLOBAL_OPERATOR/GLOBAL_ADMIN
receive Editor access for dashboards/panels; other authorized readers receive
Viewer access. The auth proxy synchronizes roles on every request. Provisioned
dashboards are editable and allow UI saves, default to `now-30m` through `now`,
and refresh every 30 seconds. UI-created dashboards persist on Grafana's PVC;
source provisioning overwrites UI edits to provisioned dashboards on update.
See the [storage/admin access guide](https://github.com/myota-platform/myota-docs/blob/main/docs/seaweedfs-admin-status.md).

NATS broker and JetStream observability is provided centrally by the cluster-local Surveyor exporter, Prometheus scrape and Grafana folder `NATS`. Operations retains SeaweedFS inspection and Grafana identity, without a broker dependency. See the [NATS observability migration guide](https://github.com/myota-platform/myota-docs/blob/main/docs/observability/nats-surveyor-migration.md).
The operations dashboard
includes users, geodata entities, imports, programmes, QSOs, participants,
awards, workers, queue lag, HTTP errors and OTel latency. The separate
`MyOTA API performance` dashboard repeats request-rate, p95 latency, 5xx rate,
and availability graphs for every observed service; each graph is split by
normalized API route and HTTP method. It does not contain synthetic business
values.
The **MyOTA Geodata capacity baseline** dashboard adds per-instance process
CPU/memory, request-size and in-flight measurements, PostgreSQL pool and lock
pressure, and durable import/outbox queue age and throughput signals.
The Grafana folder **NATS** contains dashboard 16256 and ten vendored NATS Surveyor dashboards. Surveyor provides broker and JetStream metrics; its upstream cluster, gateway, raft, and service-observation panels can be empty when those features or observation sources are absent. The retired combined MyOTA dashboard and its two PostGIS panels are not provisioned. Compose and Helm both use MyOTA-owned Prometheus datasource/provider configuration. The **MyOTA Object Storage** dashboard shows SeaweedFS S3
request rates, latency, errors, and in-flight uploads. Helm hashes Grafana's
dashboard and provisioning files into the Grafana pod template so ConfigMap
updates restart Grafana; its dashboard files use `subPath` mounts, which do not
refresh in place.

Enable the local observability profile with:

```bash
docker-compose --profile observability up -d --build
```

After signing in to the administration UI, open **Platform health →
Observability** or visit http://localhost:8090/observability/. Grafana,
Prometheus, Alertmanager, Tempo, and collector endpoints are not published on
host ports; Grafana is reverse-proxied through the UI and validates the MyOTA
access token for every request. Prometheus rules cover collector/service
availability, per-route 5xx rate, and per-route p95 latency. Grafana-managed
rules use the same Prometheus signals and forward to the local Alertmanager
receiver; the local profile deliberately does not invent an email or paging
destination. Alertmanager groups and exposes firing alerts, but external email
or paging delivery must be configured separately. The same collector,
dashboards, alert rules and scrape
configuration are deployed by the Helm chart. Deprecated routes remain aliases until the
documented sunset; use service-owned telemetry to monitor remaining callers
before removing them.

Unit tests may use a small in-memory adapter when they explicitly omit a
database URL. The local Compose runtime is different: identity/programmes use
`myota_core` on plain PostgreSQL, activity/workers use `myota_activity` on
plain PostgreSQL, and geodata/import workers use `myota_geo` on PostGIS. Every
database-backed service has its service-specific URL and
`MYOTA_REQUIRE_DURABILITY=1`. A missing URL therefore stops that service
during startup instead of silently accepting writes in process memory. The
named Compose volumes preserve all three databases between restarts.

## Object-storage buckets

All services share the configured S3-compatible endpoint and credentials, but
use distinct buckets to isolate contents and lifecycle policies:

| Purpose | Default bucket | Configuration |
|---|---|---|
| Geodata imports/source snapshots | `myota-geodata-imports` | `MYOTA_GEODATA_IMPORT_BUCKET` / `objectStorage.geodataImportBucket` |
| ADIF source logs | `myota-adif` | `MYOTA_ADIF_BUCKET` / `objectStorage.adifBucket` |
| Editable award backgrounds | `myota-award-assets` | `MYOTA_AWARD_ASSET_BUCKET` / `objectStorage.awardAssetBucket` |
| Award-manager signatures | `myota-award-signatures` | `MYOTA_AWARD_SIGNATURE_BUCKET` / `objectStorage.awardSignatureBucket` |
| Issued award certificates | `myota-certificates` | `MYOTA_CERTIFICATE_BUCKET` / `objectStorage.certificateBucket` |

Completed and failed ADIF source objects in `myota-adif` are deleted after 15
days; the activity import result remains in PostgreSQL. Queued and processing
ADIF imports are excluded. The separate geodata-import bucket is subject to
its own 30-day import expunge.
Existing object references keep their recorded bucket; installations upgrading
from the former shared `myota-awards` bucket should migrate asset objects and
metadata before removing it. See the
[object-storage operations guide](https://github.com/myota-platform/myota-docs/blob/main/docs/operations.md#object-storage-bucket-boundaries).

## Run the vertical slice

```bash
python3 -m unittest discover -s tests -v
docker-compose up -d --build
```

Open <http://127.0.0.1:8090> for administration or
<http://127.0.0.1:8080> for the participant web/gateway. Domain APIs use
ports 8001–8004; the read-only operations service uses 8005. Activations and awards
intentionally share the activity service on port 8004; there is no standalone
awards port. Use `python3 services/dev_server.py` only as the dependency-free
unit-test harness; it is not a durable runtime unless database URLs and
`MYOTA_REQUIRE_DURABILITY=1` are supplied explicitly.

For the three-database local environment, start Colima and run
`docker-compose up -d --build`. The gateway is available on
`http://localhost:8080`; the authenticated administration web is available on
`http://localhost:8090`; SeaweedFS exposes its S3 endpoint on
`http://localhost:8333` and filer UI on `http://localhost:8888` for local
object administration. Container and Kubernetes health probes use the S3
`/status` endpoint rather than the filer HTML root; the latter is a streaming
directory page and can log harmless broken-pipe messages when a probe closes
early. Activity and awards share port 8004, while
`activity-worker`, `activity-notifications`, `activity-adif-retention`, and `geodata-import-processing`
run asynchronously and can be scaled independently. The geodata processing
worker consumes preprocessing, promotion and confirmed permanent-deletion
subjects with separate durable JetStream pull consumers; promotion and deletion
follow explicit administrator authorization. Browser uploads
use bounded resumable SeaweedFS multipart sessions and need no shared
upload-spool PVC. The activity migration is applied by
`db/migrations/run.sh`; core, activity and geodata migration ownership is
separated under `db/migrations/core/`, `db/migrations/activity/` and
`db/migrations/geo/`. The canonical activity source is maintained in
`myota-activity-service/migrations/` and reviewed into this deployment copy.
The Helm chart exposes the same processor as
`geodataImportProcessing`, so production Kubernetes deployments keep the
promotion worker separate from the HTTP geodata pods. Helm rendering and
linting run in the GitHub workflow rather than being a local prerequisite.
The production geodata load-test cleanup endpoint is disabled by default.
For an approved load-test window only, set
`geodataLoadTestCleanup.enabled=true` and
`geodataLoadTestCleanup.allowProductionCleanup=true` with
`auth.environment=production`; immediately disable both settings after the
test's cleanup succeeds. The API requires a dedicated `GLOBAL_ADMIN` and
refuses deletion of fixtures linked to QSOs, activations, or award progress.
The daily `geodataImportRetention` CronJob (and local Compose retention worker)
expunges source objects and import-specific history after 30 days. `PROCESSED`
runs age from finalization; pending, failed, and stalled imports age from their
latest activity. Active heartbeats keep long-running work safe. The worker
does not remove promoted entities or provenance.
The daily `activityAdifRetention` CronJob (and local Compose retention worker)
deletes source objects for completed or failed ADIF imports after 15 days from
their terminal processing timestamp. Its database marker makes deletion
safely retryable; import status, result counts, and diagnostics remain
available. Queued and processing imports are excluded. The policy never
applies to award assets, signatures, or issued certificates.
For deployment to the Spainip K3s cluster through Rancher Fleet and Traefik,
see [`deploy/helm/myota/DEPLOYMENT.md`](deploy/helm/myota/DEPLOYMENT.md) and
the non-secret Fleet values in
[`deploy/helm/myota/values-spainip.yaml`](deploy/helm/myota/values-spainip.yaml).

The Vue administration image listens on port `8080` inside its container and
is exposed on port `8090` by Compose and the Helm Service. Nginx proxies the
same-origin `/v1` and `/healthz` requests to the gateway, so the browser does
not need a separate API origin or CORS configuration. Local Vite development
uses port `8090` and proxies to the gateway on `8080`.

### Migrating filesystem-adapter objects

Before removing a development `MYOTA_OBJECT_STORAGE_LOCAL_DIR`, copy its
bucket/key tree into SeaweedFS with:

```bash
MYOTA_OBJECT_STORAGE_ENDPOINT=http://localhost:8333 \
MYOTA_OBJECT_STORAGE_ACCESS_KEY=myota-s3 \
MYOTA_OBJECT_STORAGE_SECRET_KEY=myota-s3-dev-only \
python3 scripts/migrate-local-object-store.py --source /path/to/object-store
```

The tool preserves bucket names and object keys. It is safe to run with
`--dry-run` first and is idempotent for the same source tree. The current
checkout was inventoried during the migration; no filesystem-adapter object
directory was present, and the old development object-store volume was empty.

The admin web's Geodata imports page sends pasted GeoJSON/KML/GPX/WFS/ArcGIS
documents to the geodata service and uploads binary/text files through the
SeaweedFS-backed intake endpoint. Imports stop at `PREPROCESSED`; normalized
records are duplicate-checked against existing geometry and can carry a
non-blocking `POSSIBLE_DUPLICATE` warning with comparison geometry. The admin
page shows active runs in a dedicated pre-processing queue, separate from
Geodata Review, with pending/confirmed counts. Its modal provides compact
paging, select-all, duplicate map comparison, validation, and explicit
promotion to `CANDIDATE` or `APPROVED`. The multi-select category control reads the
complete shared Master data catalogue from the programme service database;
imports may carry several categories, are not assigned to a programme, and
enter as `CANDIDATE`. The first category remains the compatibility primary
`entityType`; all assignments are persisted in `geodata_entity_category`. The
geodata outbox publishes the processing request to NATS. Global entity deletion
is a two-step API workflow: activity impact and
QSO cascade/award recalculation first, then geodata entity/audit cleanup.

## Architecture

Read the authoritative [architecture](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture.md),
[storage topology ADR](https://github.com/myota-platform/myota-docs/blob/main/docs/adr/0001-storage-topology.md)
and [repository map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md).
The [scaling delivery/evidence checklist](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-horizontal-scaling-roadmap.md#latest-delivery-and-evidence--7-october-2026)
records migration 016, separate workers, operations integration and remaining
failure/load gates. Keep replica counts unchanged until those gates pass;
render/validate Helm through the GitHub chart workflow.

## Source project

The original `ea7klk/mpota` repository remains untouched; see the central
[migration strategy](https://github.com/myota-platform/myota-docs/blob/main/docs/migration-from-mpota.md).


Phase 4 source changes move six Activity job kinds to dedicated per-kind
JetStream pull durables. The Activity database remains the status, payload,
retry, and redrive authority; a guarded migration backfills queued jobs and
removes the obsolete poller claim index. The production worker drain and
migration rollout must follow the staged procedure in the [Activity work queue
runbook](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/activity-work-queues.md)
and [Phase 4 evidence](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/evidence/phase4-activity-work-2026-10-10.md).

Phase 5 Geodata work source, migration 021, and isolated reliability tests are
complete within their recorded evidence bounds. Helm revision 192 is deployed;
Fleet reports Ready=True at `6443473828305ab9d02a918bbe990d01abe97f6a` with 60/60 resources. First-party
image references use configured immutable digests, which match live Activity,
Geodata, and shared-runtime pod IDs. The four target durables are empty with
active workers; four legacy Geodata durables remain inactive and empty through
the rollback observation ending no earlier than 21:39:22 UTC on 11 October 2026.
Only that observation and safe retirement of those four legacy durables remain open. See the
[Phase 5 evidence](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/evidence/phase5-geodata-work-2026-10-10.md).
