# MyOTA event contract

Services persist versioned events in a transactional outbox in their owned database. Outbox workers publish the complete event envelope—including its aggregate identity—to the file-backed `MYOTA_EVENTS` NATS JetStream stream. The stream uses Interest retention: an event remains while any matching durable consumer has not acknowledged it and is removed after all such consumers acknowledge it. Outbox startup provisions and validates every supported durable filter before publishing; an explicit geodata work subject without a provisioned consumer is rejected. Consumers use explicit acknowledgements, database checkpoints and recoverable leases. The existing 30-day maximum age remains a safety bound for unconsumed backlog, not a replay window for acknowledged events. JetStream is not the event archive; durable domain state and outbox/dead-letter records remain in service-owned PostgreSQL. No accepted production work relies on an API process's event list or executor queue.

```json
{
  "eventId": "uuid",
  "eventType": "geodata.entity.reviewed.v1",
  "occurredAt": "2026-01-01T00:00:00Z",
  "producer": "geodata-service",
  "aggregate": { "type": "entity", "id": "uuid" },
  "correlationId": "uuid",
  "payload": {}
}
```

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
