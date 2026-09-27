# MyOTA event contract

Services publish durable, versioned events to an outbox owned by the emitting service. The initial implementation records the event envelope in memory; production deployment connects the outbox to a broker such as NATS JetStream or RabbitMQ without changing the HTTP contracts.

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

Important events include `identity.account.created.v1`, `identity.callsign.verified.v1`, `programme.created.v1`, `geodata.import.accepted.v1`, `geodata.entity.candidate.created.v1`, `geodata.entity.reviewed.v1`, `activity.activation.created.v1`, and `activity.qso.recorded.v1`.

`CANDIDATE` is the single pre-review lifecycle state. Its `candidateSource`
identifies either an adapter/import run or a community proposal; the former
`PROPOSED` status and event are retired.
