# MyOTA event contract

## Current behavior

Services persist versioned events in transactional outboxes in their owned
databases. The current shared relay publishes to a file-backed `MYOTA_EVENTS`
stream with Interest retention. That stream currently mixes committed facts and
Geodata work subjects. The relay currently provisions consumers itself and can
change stream retention at startup. The shared envelope has no `envelopeVersion`
and includes a relay `attempts` field; the subject helper currently replaces
dots in event types with underscores. These are current-state observations, not
the selected target contract. See the [Phase 0 inventory](../../myota-docs/docs/operations/messaging/nats-event-migration-inventory.md)
for repository evidence.

## Selected target contract (Phase 1 implementation in progress)

The [machine-readable registry](event-registry.json) enumerates the Phase 0
event facts and selected work commands. Per-event schemas are under
[`schemas/`](schemas/). All schemas constrain the immutable outer envelope and
event identity. The 19 Identity, 12 Programme, and 10 Activity fact payload schemas are
derived from producer call sites in `myota-identity-service/identity.py`,
`myota-programme-service/programmes.py`, `myota-activity-service/activity.py`,
`myota-activity-service/activity_repository.py`, and
`myota-activity-service/awards.py`; additive fields remain accepted. Activity
classifications identify personal activity/QSO data, import object metadata,
internal award configuration, and certificate details. Dynamic rule/configuration
objects and nested award assets remain unconstrained where source code accepts
caller-defined structures. These are source-derived evidence, not jointly approved
producer gates. Geodata and Operations payloads remain pending.

Target domain events use `envelopeVersion: 1`, a stable UUID `eventId`, dotted
`eventType` with its `.vN` suffix, UTC `occurredAt`, producer, aggregate identity,
optional trusted `correlationId` and `causationId`, and payload. `attempts` and
other mutable relay state are excluded. Publish with `Nats-Msg-Id: eventId`.
The target subject is `myota.events.<eventType>` with dots preserved. Version
compatibility is governed by the event type's major version independently of
the envelope version. Unknown subject or envelope versions must fail before the
outbox row is marked published, and the failure must remain visible and
recoverable from the owning database.

Work commands have a distinct envelope with stable `workId` and `workType` and
use the disjoint `myota.work.activity.*` or `myota.work.geodata.*` namespaces.
They carry bounded identifiers and metadata, never large source documents or
blobs. The shared registry declares one competing durable per selected job kind.
PostgreSQL remains the source of truth; JetStream is a bounded delivery/replay
window, not a permanent event archive. The ADR-0008 target is not yet the live
deployment.

```json
{
  "envelopeVersion": 1,
  "eventId": "uuid",
  "eventType": "geodata.entity.reviewed.v1",
  "occurredAt": "2026-01-01T00:00:00Z",
  "producer": "geodata-service",
  "aggregate": { "type": "entity", "id": "uuid" },
  "correlationId": "trusted-request-or-parent-id",
  "causationId": "optional-parent-event-or-work-id",
  "payload": {}
}
```

The JSON above illustrates the target envelope and is not a claim that all
current producers emit it. The source-derived Identity and Programme schemas
describe current payload shapes, including review metadata and sensitive fields;
joint owner review is still required before they become producer enforcement.
Other unresolved payload contracts remain explicitly marked in the registry.

Important events include `identity.account.created.v1`, `identity.callsign.verified.v1`, `programme.created.v1`, `geodata.import.queued.v1`, `geodata.import.cancellation-requested.v1`, `geodata.import.cancelled.v1`, `geodata.import.preprocessed.v1`, `geodata.import.candidates.validated.v1`, `geodata.import.processing.queued.v1`, `geodata.import.processing.completed.v1`, `geodata.import.processed.v1`, `geodata.entity.candidate.created.v1`, `geodata.entity.reviewed.v1`, `geodata.entity.location-enrichment-requested.v1`, `geodata.entity.location-enriched.v1`, `activity.activation.created.v1`, `activity.qso.recorded.v1`, `awards.definition.saved.v1`, `awards.definition.published.v1`, `awards.request.created.v1`, `awards.issued.v1`, and `awards.rendered.v1`.

File and pasted imports stop at `PREPROCESSED`. The administrator validation
queue is paged and selection-based. Processing publishes the selected IDs to
the `myota.geodata.import.process.v1` NATS subject (represented by the durable
outbox in local development and production), with an explicit `CANDIDATE` or `APPROVED` target. Confirmation, the processing job and outbox insert commit together; queued records cannot be submitted to another job.

Preprocessing uses `myota.geodata.import.preprocess.v1`, durable pull consumer
`geodata-preprocessing-v1`. Promotion uses `myota.geodata.import.process.v1`,
consumer `geodata-import-processing-v2`. Confirmed entity deletion uses
`geodata.entity-deletion-job.queued.v1` with `payload.natsSubject` set to
`myota.geodata.entity.delete.v1`, consumer `geodata-entity-deletion-v1`.
Consumers are deployed separately from the HTTP API and remain geodata-owned.
They record side effects/results in PostGIS before acknowledging delivery;
duplicate event delivery is expected and guarded by stable IDs and checkpoints.
Broker metadata and sampled status history are exposed through the authenticated
operations API; that service never consumes, acknowledges or purges messages.

Entity location enrichment is requested by the geodata API in the same
transaction that persists the entity's current geometry and
`locationEnrichmentStatus=QUEUED`. The outbox routes
`geodata.entity.location-enrichment-requested.v1` to
`myota.geodata.entity.location-enrichment.v1`, consumed by the durable
`geodata-location-enrichment-v1` pull consumer. The worker resolves the current
geometry centroid outside a database transaction, then rechecks both request
ID and geometry hash before writing normalized fields and provider provenance.
If geometry changed while the provider lookup was running, that result is
discarded and the newer request remains authoritative. Provider results never
replace explicitly manual location fields or their corresponding codes.
`geodata.entity.location-enriched.v1` records the resulting status; repeated
delivery after a successful commit does not repeat the remote lookup.

`CANDIDATE` is the single pre-review lifecycle state. A candidate records its
origin in `candidateSource.type`: `ADAPTER_IMPORT` identifies an adapter and
import run, while `COMMUNITY_PROPOSAL` identifies a proposal and proposer.
The former `geodata.entity.proposed.v1` event and `PROPOSED` status are retired;
consumers should handle `geodata.entity.candidate.created.v1` and the review
event instead.

Award definitions, requests, and issuance records are owned by the activity service. They are exposed under the same port and bounded API as activation/QSO execution (`8004` locally), while binary backgrounds, signatures, and generated certificates are addressed through the configured S3-compatible object store.
