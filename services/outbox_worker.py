"""Transactional-outbox relay for NATS JetStream.

Rows are claimed with SKIP LOCKED, published with an event id as the NATS
message id, and only marked published after JetStream acknowledges them.
Failures are retried with backoff and eventually copied to the dead-letter table.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import psycopg
from nats.aio.client import Client as NATS
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from outbox_routing import event_envelope, event_subject


DB_URL = os.environ["OUTBOX_DATABASE_URL"]
NATS_URL = os.environ.get("NATS_URL", "nats://nats:4222")
MAX_ATTEMPTS = int(os.environ.get("OUTBOX_MAX_ATTEMPTS", "12"))
WORKER_NAME = os.environ.get("OUTBOX_WORKER", "myota-outbox")
STREAM_NAME = "MYOTA_EVENTS"
STREAM_SUBJECTS = ("myota.events.>", "myota.geodata.>")
STREAM_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def required_consumers() -> tuple[ConsumerConfig, ...]:
    """Describe every durable interest before enabling interest retention."""
    geodata_options = {
        "ack_policy": AckPolicy.EXPLICIT,
        "ack_wait": int(
            os.environ.get("GEODATA_WORKER_ACK_WAIT_SECONDS", "120")
        ),
        "max_deliver": int(
            os.environ.get("GEODATA_WORKER_MAX_DELIVERIES", "100")
        ),
        "max_ack_pending": int(
            os.environ.get("GEODATA_WORKER_MAX_ACK_PENDING", "1")
        ),
    }
    return (
        ConsumerConfig(
            durable_name="activity-notifications-pull-v1",
            filter_subject="myota.events.>",
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=60,
            max_deliver=10,
            max_ack_pending=64,
        ),
        ConsumerConfig(
            durable_name="geodata-entity-deletion-v1",
            filter_subject="myota.geodata.entity.delete.v1",
            **geodata_options,
        ),
        ConsumerConfig(
            durable_name="geodata-preprocessing-v1",
            filter_subject="myota.geodata.import.preprocess.v1",
            **geodata_options,
        ),
        ConsumerConfig(
            durable_name="geodata-import-processing-v2",
            filter_subject="myota.geodata.import.process.v1",
            **geodata_options,
        ),
        ConsumerConfig(
            durable_name="geodata-location-enrichment-v1",
            filter_subject="myota.geodata.entity.location-enrichment.v1",
            **geodata_options,
        ),
    )


async def ensure_consumer(js, desired: ConsumerConfig) -> None:
    """Provision and validate a durable filter before publishing can begin."""
    durable = desired.durable_name
    try:
        info = await js.consumer_info(STREAM_NAME, durable)
    except Exception:
        try:
            await js.add_consumer(STREAM_NAME, desired)
        except Exception:
            # Concurrent outbox relays may create the same durable together.
            pass
        info = await js.consumer_info(STREAM_NAME, durable)

    actual = info.config
    if actual.filter_subject != desired.filter_subject:
        raise RuntimeError(
            f"JetStream durable {durable} has unexpected subject filter"
        )
    if actual.ack_policy != AckPolicy.EXPLICIT:
        raise RuntimeError(
            f"JetStream durable {durable} must use explicit acknowledgements"
        )


async def ensure_stream(nc: NATS) -> None:
    js = nc.jetstream()
    try:
        stream = await js.stream_info(STREAM_NAME)
    except Exception:
        try:
            stream = await js.add_stream(
                StreamConfig(
                    name=STREAM_NAME,
                    subjects=list(STREAM_SUBJECTS),
                    retention=RetentionPolicy.LIMITS,
                    storage=StorageType.FILE,
                    max_age=STREAM_MAX_AGE_SECONDS,
                )
            )
        except Exception:
            # Two relays can start concurrently; the winner creates the stream.
            stream = await js.stream_info(STREAM_NAME)

    subjects = set(stream.config.subjects or [])
    required_subjects = set(STREAM_SUBJECTS)
    if not required_subjects.issubset(subjects):
        stream.config.subjects = sorted(subjects | required_subjects)
        try:
            await js.update_stream(stream.config)
        except Exception:
            stream = await js.stream_info(STREAM_NAME)
            if not required_subjects.issubset(
                set(stream.config.subjects or [])
            ):
                raise

    # Interest retention can discard a message immediately when no durable
    # consumer matches its subject. Register every queue before enabling it.
    for consumer in required_consumers():
        await ensure_consumer(js, consumer)

    stream = await js.stream_info(STREAM_NAME)
    retention = getattr(
        stream.config.retention, "value", stream.config.retention
    )
    if str(retention).lower() == RetentionPolicy.INTEREST.value:
        return
    if str(retention).lower() != RetentionPolicy.LIMITS.value:
        raise RuntimeError(
            f"unsupported {STREAM_NAME} retention policy: {retention}"
        )

    # Limits -> Interest is a supported live transition; it immediately
    # reclaims messages already acked by all matching durable consumers.
    stream.config.retention = RetentionPolicy.INTEREST
    await js.update_stream(stream.config)


def claim() -> dict | None:
    with psycopg.connect(DB_URL) as connection:
        with connection.cursor() as cur:
            cur.execute("""WITH next_event AS (
              SELECT event_id FROM outbox_event
              WHERE published_at IS NULL AND available_at <= now()
              ORDER BY occurred_at FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE outbox_event e SET attempts = e.attempts + 1
            FROM next_event n WHERE e.event_id = n.event_id
            RETURNING e.event_id, e.event_type, e.producer,
              e.aggregate_type, e.aggregate_id, e.payload,
              e.occurred_at, e.attempts""")
            row = cur.fetchone()
            if not row:
                return None
            return event_envelope(row)


def mark_published(event_id: str) -> None:
    with psycopg.connect(DB_URL) as connection:
        connection.execute(
            "UPDATE outbox_event SET published_at = now(), last_error = NULL WHERE event_id = %s",
            (event_id,),
        )


def mark_failed(event: dict, error: Exception) -> None:
    with psycopg.connect(DB_URL) as connection:
        if event["attempts"] >= MAX_ATTEMPTS:
            connection.execute(
                """INSERT INTO dead_letter_event(event_id, event_type, payload, attempts, error)
                VALUES (%s, %s, %s::jsonb, %s, %s) ON CONFLICT (event_id) DO NOTHING""",
                (
                    event["eventId"],
                    event["eventType"],
                    json.dumps(event["payload"]),
                    event["attempts"],
                    str(error),
                ),
            )
            connection.execute(
                "UPDATE outbox_event SET published_at = now(), last_error = %s WHERE event_id = %s",
                (f"dead-lettered: {error}", event["eventId"]),
            )
        else:
            delay = min(300, 2 ** min(event["attempts"], 8))
            connection.execute(
                "UPDATE outbox_event SET available_at = now() + make_interval(secs => %s), last_error = %s WHERE event_id = %s",
                (delay, str(error), event["eventId"]),
            )


async def main() -> None:
    nc = NATS()
    await nc.connect(
        NATS_URL,
        name=WORKER_NAME,
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,
    )
    await ensure_stream(nc)
    js = nc.jetstream()
    try:
        while True:
            event = await asyncio.to_thread(claim)
            if not event:
                await asyncio.sleep(1)
                continue
            try:
                subject = event_subject(event)
                await js.publish(
                    subject,
                    json.dumps(event).encode(),
                    headers={"Nats-Msg-Id": event["eventId"]},
                )
                await asyncio.to_thread(mark_published, event["eventId"])
            except Exception as exc:
                await asyncio.to_thread(mark_failed, event, exc)
    finally:
        await nc.drain()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
