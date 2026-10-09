"""Reviewed desired JetStream topology for explicit provisioning.

The required finite capacity values deliberately have no production defaults:
the Phase 0 evidence register requires measured traffic and recovery objectives
before a live topology can be activated. Importing this module is side-effect
free and does not connect to or mutate a broker.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Stream:
    name: str
    subjects: tuple[str, ...]
    retention: str
    max_age_seconds: int
    max_bytes: int
    max_messages: int
    max_message_bytes: int
    replicas: int = 1
    discard: str = "new"
    storage: str = "file"


@dataclass(frozen=True)
class Consumer:
    stream: str
    durable: str
    filter_subject: str
    ack_wait_seconds: int
    max_deliveries: int
    max_ack_pending: int


ACTIVITY_WORK = (
    (
        "activity-qso-ingestion-v1",
        "myota.work.activity.qso-ingestion.v1",
        120,
        8,
        4,
    ),
    (
        "activity-adif-import-v1",
        "myota.work.activity.adif-import.v1",
        300,
        8,
        1,
    ),
    (
        "activity-award-recalculate-v1",
        "myota.work.activity.award-recalculate.v1",
        120,
        8,
        2,
    ),
    (
        "activity-award-evaluation-v1",
        "myota.work.activity.award-evaluation.v1",
        120,
        8,
        2,
    ),
    ("activity-pdf-render-v1", "myota.work.activity.pdf-render.v1", 300, 8, 1),
    (
        "activity-statistics-rebuild-v1",
        "myota.work.activity.statistics-rebuild.v1",
        300,
        8,
        1,
    ),
)
GEODATA_WORK = (
    (
        "geodata-preprocessing-v1",
        "myota.work.geodata.import-preprocess.v1",
        300,
        100,
        1,
    ),
    (
        "geodata-import-promotion-v1",
        "myota.work.geodata.import-promotion.v1",
        300,
        100,
        1,
    ),
    (
        "geodata-entity-deletion-v1",
        "myota.work.geodata.entity-delete.v1",
        120,
        100,
        1,
    ),
    (
        "geodata-location-enrichment-v1",
        "myota.work.geodata.location-enrichment.v1",
        120,
        8,
        4,
    ),
)


def _positive_int(env_name: str) -> int:
    raw = os.environ.get(env_name, "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{env_name} must be set to a measured positive integer"
        ) from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be a measured positive integer")
    return value


def desired_topology() -> tuple[tuple[Stream, ...], tuple[Consumer, ...]]:
    """Build finite target limits from explicitly supplied capacity evidence."""
    streams = (
        Stream(
            "MYOTA_EVENTS",
            ("myota.events.>",),
            "limits",
            30 * 86400,
            _positive_int("NATS_EVENTS_MAX_BYTES"),
            _positive_int("NATS_EVENTS_MAX_MESSAGES"),
            _positive_int("NATS_EVENTS_MAX_MESSAGE_BYTES"),
        ),
        Stream(
            "MYOTA_ACTIVITY_WORK",
            ("myota.work.activity.>",),
            "workqueue",
            _positive_int("NATS_ACTIVITY_WORK_MAX_AGE_SECONDS"),
            _positive_int("NATS_ACTIVITY_WORK_MAX_BYTES"),
            _positive_int("NATS_ACTIVITY_WORK_MAX_MESSAGES"),
            _positive_int("NATS_ACTIVITY_WORK_MAX_MESSAGE_BYTES"),
        ),
        Stream(
            "MYOTA_GEODATA_WORK",
            ("myota.work.geodata.>",),
            "workqueue",
            _positive_int("NATS_GEODATA_WORK_MAX_AGE_SECONDS"),
            _positive_int("NATS_GEODATA_WORK_MAX_BYTES"),
            _positive_int("NATS_GEODATA_WORK_MAX_MESSAGES"),
            _positive_int("NATS_GEODATA_WORK_MAX_MESSAGE_BYTES"),
        ),
    )
    consumers = tuple(
        Consumer(stream, durable, subject, ack_wait, max_deliver, max_pending)
        for stream, definitions in (
            ("MYOTA_ACTIVITY_WORK", ACTIVITY_WORK),
            ("MYOTA_GEODATA_WORK", GEODATA_WORK),
        )
        for durable, subject, ack_wait, max_deliver, max_pending in definitions
    )
    validate_topology(streams, consumers)
    return streams, consumers


def validate_topology(
    streams: tuple[Stream, ...], consumers: tuple[Consumer, ...]
) -> None:
    names = [stream.name for stream in streams]
    if len(names) != len(set(names)):
        raise ValueError("JetStream stream names must be unique")
    subject_owners: dict[str, str] = {}
    for stream in streams:
        if stream.retention not in {"limits", "workqueue"}:
            raise ValueError(f"unsupported retention policy for {stream.name}")
        if (
            stream.storage != "file"
            or stream.discard != "new"
            or stream.replicas != 1
        ):
            raise ValueError(
                f"unsafe storage/discard/replica policy for {stream.name}"
            )
        if (
            min(
                stream.max_age_seconds,
                stream.max_bytes,
                stream.max_messages,
                stream.max_message_bytes,
            )
            <= 0
        ):
            raise ValueError(
                f"all stream limits must be finite for {stream.name}"
            )
        for subject in stream.subjects:
            if subject in subject_owners:
                raise ValueError(f"overlapping subject capture {subject}")
            subject_owners[subject] = stream.name
    required = {"MYOTA_EVENTS", "MYOTA_ACTIVITY_WORK", "MYOTA_GEODATA_WORK"}
    if set(names) != required:
        raise ValueError(
            "target topology must contain exactly the three ADR-0008 streams"
        )
    durable_keys: set[tuple[str, str]] = set()
    work_filters: set[tuple[str, str]] = set()
    for consumer in consumers:
        key = (consumer.stream, consumer.durable)
        if key in durable_keys:
            raise ValueError(f"duplicate durable {key}")
        durable_keys.add(key)
        if consumer.stream not in {
            "MYOTA_ACTIVITY_WORK",
            "MYOTA_GEODATA_WORK",
        }:
            raise ValueError(
                "Phase 1 only provisions registered work durables"
            )
        filter_key = (consumer.stream, consumer.filter_subject)
        if filter_key in work_filters:
            raise ValueError(f"overlapping work durable filter {filter_key}")
        work_filters.add(filter_key)
        if (
            min(
                consumer.ack_wait_seconds,
                consumer.max_deliveries,
                consumer.max_ack_pending,
            )
            <= 0
        ):
            raise ValueError(
                f"consumer settings must be positive for {consumer.durable}"
            )


def topology_from_environment() -> tuple[
    tuple[Stream, ...], tuple[Consumer, ...]
]:
    """Require an explicit operator opt-in before loading live capacity values."""
    if os.environ.get("NATS_TOPOLOGY_APPLY") != "1":
        raise RuntimeError(
            "set NATS_TOPOLOGY_APPLY=1 only after Phase 0 gates and capacity review"
        )
    return desired_topology()
