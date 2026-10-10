"""Contract-backed routing and immutable envelope construction."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


CATALOG_PATH = Path(__file__).with_name("event_registry.json")
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
EVENTS = CATALOG["events"]
LEGACY_WORK_ROUTES = CATALOG["legacyWorkRoutes"]
UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class OutboxContractError(ValueError):
    """An outbox row cannot be published under the checked-in contract."""


def event_subject(event: dict) -> str:
    """Route registered facts and the explicitly retained legacy work paths."""
    event_type = event.get("eventType")
    if not isinstance(event_type, str):
        raise OutboxContractError("outbox event type is required")

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise OutboxContractError("outbox payload must be an object")

    work_route = LEGACY_WORK_ROUTES.get(event_type)
    explicit_subject = payload.get("natsSubject")
    if work_route:
        if explicit_subject != work_route["subject"]:
            raise OutboxContractError(
                "legacy work event has an unexpected subject"
            )
        return work_route["subject"]
    if event_type not in EVENTS:
        raise OutboxContractError("unregistered outbox event type")
    if explicit_subject is not None:
        raise OutboxContractError(
            "domain fact cannot override its registered subject"
        )
    return EVENTS[event_type]["subject"]


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OutboxContractError("outbox timestamp must include a timezone")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def event_envelope(row: tuple) -> dict:
    """Build a versioned fact or compatible current Geodata work envelope."""
    (
        event_id,
        event_type,
        producer,
        aggregate_type,
        aggregate_id,
        payload,
        occurred_at,
        _attempts,
    ) = row
    work_route = LEGACY_WORK_ROUTES.get(event_type)
    if event_type not in EVENTS and work_route is None:
        raise OutboxContractError("unregistered outbox event type")
    if not isinstance(payload, dict):
        raise OutboxContractError("outbox payload must be an object")
    try:
        normalized_id = str(UUID(str(event_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OutboxContractError("outbox event ID must be a UUID") from exc
    if not UUID_PATTERN.fullmatch(normalized_id):
        raise OutboxContractError("outbox event ID must be a UUID")
    if not isinstance(producer, str) or not producer:
        raise OutboxContractError("outbox producer is required")
    expected_producers = (
        work_route["producers"]
        if work_route
        else EVENTS[event_type]["producers"]
    )
    if producer not in expected_producers:
        raise OutboxContractError(
            "outbox producer does not match registered event owner"
        )
    if not isinstance(aggregate_type, str) or not aggregate_type:
        raise OutboxContractError("outbox aggregate type is required")
    if aggregate_id is None:
        raise OutboxContractError("outbox aggregate ID is required")

    envelope = {
        "eventId": normalized_id,
        "eventType": event_type,
        "occurredAt": _utc_timestamp(occurred_at),
        "producer": producer,
        "aggregate": {
            "type": aggregate_type,
            "id": str(aggregate_id),
        },
        "payload": payload,
    }
    # Work events remain on their existing consumers until the later queue
    # migration. Domain facts can move to the selected immutable envelope now.
    if work_route is None:
        envelope["envelopeVersion"] = 1
    return envelope
