"""Pure helpers for assembling and routing transactional outbox events."""

from __future__ import annotations


def event_subject(event: dict) -> str:
    """Route explicit domain work while retaining generic event routing."""
    subject = (event.get("payload") or {}).get("natsSubject")
    if subject:
        if not isinstance(subject, str) or not subject.startswith(
            "myota.geodata."
        ):
            raise ValueError("unsupported explicit outbox subject")
        return subject
    return "myota.events." + event["eventType"].replace(".", "_")


def event_envelope(row: tuple) -> dict:
    """Build the consumer contract from a claimed outbox row."""
    (
        event_id,
        event_type,
        producer,
        aggregate_type,
        aggregate_id,
        payload,
        occurred_at,
        attempts,
    ) = row
    occurred_at = occurred_at.isoformat().replace("+00:00", "Z")
    return {
        "eventId": str(event_id),
        "eventType": event_type,
        "occurredAt": occurred_at,
        "producer": producer,
        "aggregate": {"type": aggregate_type, "id": str(aggregate_id)},
        "correlationId": str(event_id),
        "payload": payload,
        "attempts": attempts,
    }
