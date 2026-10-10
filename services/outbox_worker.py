"""Bounded transactional-outbox relay for NATS JetStream."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import signal
import sys

import psycopg
from nats.aio.client import Client as NATS
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    ReplayPolicy,
    RetentionPolicy,
    StorageType,
)
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from jetstream_topology import ACTIVITY_WORK, GEODATA_WORK
from outbox_routing import (
    CATALOG,
    OutboxContractError,
    event_envelope,
    event_stream,
    event_subject,
)


LOG = logging.getLogger("myota.outbox")
DB_URL = os.environ["OUTBOX_DATABASE_URL"]
NATS_URL = os.environ.get("NATS_URL", "nats://nats:4222")
MAX_ATTEMPTS = max(1, int(os.environ.get("OUTBOX_MAX_ATTEMPTS", "12")))
MAX_MESSAGE_BYTES = max(
    1024, int(os.environ.get("OUTBOX_MAX_MESSAGE_BYTES", "1048576"))
)
PUBLISH_TIMEOUT_SECONDS = max(
    1, float(os.environ.get("OUTBOX_PUBLISH_TIMEOUT_SECONDS", "10"))
)
WORKER_NAME = os.environ.get("OUTBOX_WORKER", "myota-outbox")
METRICS_PORT = max(0, int(os.environ.get("OUTBOX_METRICS_PORT", "9108")))
STREAM_NAME = "MYOTA_EVENTS"
STREAM_SUBJECTS = ("myota.events.>",)

PUBLISHED_TOTAL = Counter(
    "myota_outbox_published_events_total",
    "Outbox events acknowledged by JetStream.",
    ("worker",),
)
RETRY_TOTAL = Counter(
    "myota_outbox_retries_total",
    "Outbox events scheduled for retry.",
    ("worker", "failure_class"),
)
DEAD_LETTER_TOTAL = Counter(
    "myota_outbox_dead_lettered_events_total",
    "Outbox events moved to the database dead-letter table.",
    ("worker", "failure_class"),
)
PUBLISH_DURATION = Histogram(
    "myota_outbox_publish_duration_seconds",
    "Time spent waiting for JetStream publish acknowledgements.",
    ("worker",),
)
PENDING_EVENTS = Gauge(
    "myota_outbox_pending_events",
    "Unpublished events in this relay's configured database.",
    ("worker",),
)
OLDEST_PENDING_AGE = Gauge(
    "myota_outbox_oldest_pending_age_seconds",
    "Age of the oldest unpublished event in this relay's database.",
    ("worker",),
)
UNRESOLVED_DEAD_LETTERS = Gauge(
    "myota_outbox_unresolved_dead_letters",
    "Unresolved outbox dead letters in this relay's database.",
    ("worker",),
)
DATABASE_UP = Gauge(
    "myota_outbox_database_up",
    "Whether the last outbox database operation succeeded.",
    ("worker",),
)
NATS_UP = Gauge(
    "myota_outbox_nats_up",
    "Whether the relay is connected to NATS.",
    ("worker",),
)


def required_consumers() -> tuple[ConsumerConfig, ...]:
    """Describe the current fact-stream subscriber before fact publication."""
    return (
        ConsumerConfig(
            durable_name="activity-notifications-v1",
            filter_subjects=[
                "myota.events.geodata.entity.reviewed.v1",
                "myota.events.geodata.entity.status-changed.v1",
                "myota.events.identity.account.admin-updated.v1",
                "myota.events.identity.account.created.v1",
                "myota.events.identity.account.deactivated.v1",
                "myota.events.identity.bootstrap-admin.created.v1",
                "myota.events.identity.callsign.added.v1",
                "myota.events.identity.callsign.evidence-submitted.v1",
                "myota.events.identity.callsign.primary-changed.v1",
                "myota.events.identity.callsign.retired.v1",
                "myota.events.identity.callsign.verified.v1",
                "myota.events.identity.login.failed.v1",
                "myota.events.identity.login.succeeded.v1",
                "myota.events.identity.oidc.mapping.updated.v1",
                "myota.events.identity.recovery.completed.v1",
                "myota.events.identity.recovery.requested.v1",
                "myota.events.identity.role-definition.created.v1",
                "myota.events.identity.role-definition.updated.v1",
                "myota.events.identity.role.assigned.v1",
                "myota.events.identity.roles.replaced.v1",
                "myota.events.identity.service-token.issued.v1",
            ],
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.ALL,
            replay_policy=ReplayPolicy.INSTANT,
            ack_wait=60,
            max_deliver=8,
            max_ack_pending=64,
            max_waiting=32,
            backoff=[60, 120, 300, 300, 300, 300, 300, 300],
        ),
    )


async def validate_consumer(js, desired: ConsumerConfig) -> None:
    """Read-only validation of a legacy durable before publishing begins."""
    durable = desired.durable_name
    try:
        info = await js.consumer_info(STREAM_NAME, durable)
    except Exception as exc:
        raise RuntimeError(
            f"required legacy JetStream durable {durable} is missing"
        ) from exc

    actual = info.config
    if (
        tuple(actual.filter_subjects or ())
        != tuple(desired.filter_subjects or ())
        or actual.filter_subject != desired.filter_subject
    ):
        raise RuntimeError(
            f"JetStream durable {durable} has unexpected subject filter"
        )
    if actual.ack_policy != AckPolicy.EXPLICIT:
        raise RuntimeError(
            f"JetStream durable {durable} must use explicit acknowledgements"
        )
    for setting in (
        "deliver_policy",
        "replay_policy",
        "ack_wait",
        "max_deliver",
        "max_ack_pending",
        "backoff",
    ):
        if getattr(actual, setting, None) != getattr(desired, setting, None):
            raise RuntimeError(
                f"JetStream durable {durable} has unexpected {setting}"
            )
    if getattr(actual, "deliver_subject", None) is not None:
        raise RuntimeError(
            f"JetStream durable {durable} must use pull delivery"
        )


async def ensure_stream(nc: NATS) -> None:
    """Validate the legacy mixed stream without mutating broker topology."""
    js = nc.jetstream()
    try:
        stream = await js.stream_info(STREAM_NAME)
    except Exception as exc:
        raise RuntimeError(
            f"required legacy JetStream stream {STREAM_NAME} is missing; "
            "provision it through the deployment-owned topology workflow"
        ) from exc

    subjects = set(stream.config.subjects or [])
    required_subjects = set(STREAM_SUBJECTS)
    if not required_subjects.issubset(subjects):
        raise RuntimeError(
            f"legacy {STREAM_NAME} is missing required subject coverage"
        )

    for consumer in required_consumers():
        await validate_consumer(js, consumer)

    retention = getattr(
        stream.config.retention, "value", stream.config.retention
    )
    if str(retention).lower() != RetentionPolicy.INTEREST.value:
        raise RuntimeError(
            f"legacy {STREAM_NAME} must retain its current Interest policy; "
            f"found {retention}"
        )
    if stream.config.storage != StorageType.FILE:
        raise RuntimeError(f"legacy {STREAM_NAME} must use file storage")

    if WORKER_NAME == "activity-outbox":
        await validate_target_work_topology(
            js,
            "MYOTA_ACTIVITY_WORK",
            "myota.work.activity.>",
            ACTIVITY_WORK,
            6,
        )
    elif WORKER_NAME == "geo-outbox":
        await validate_target_work_topology(
            js,
            "MYOTA_GEODATA_WORK",
            "myota.work.geodata.>",
            GEODATA_WORK,
            4,
        )


async def validate_target_work_topology(
    js, stream_name: str, subject: str, definitions, expected_count: int
) -> None:
    """Fail closed unless a registered service work stream is fully provisioned."""
    routes = CATALOG.get("targetWorkRoutes", {})
    routes = {
        work_type: route
        for work_type, route in routes.items()
        if route["stream"] == stream_name
    }
    if len(routes) != expected_count:
        raise RuntimeError(
            f"{stream_name} work routes are incomplete in the registry"
        )
    try:
        stream = await js.stream_info(stream_name)
    except Exception as exc:
        raise RuntimeError(
            f"required work stream {stream_name} is missing"
        ) from exc
    config = stream.config
    subjects = set(config.subjects or [])
    if subjects != {subject}:
        raise RuntimeError(f"{stream_name} has unexpected subject coverage")
    retention = getattr(config.retention, "value", config.retention)
    if str(retention).lower() != RetentionPolicy.WORK_QUEUE.value:
        raise RuntimeError(f"{stream_name} must use WorkQueue retention")
    if (
        config.storage != StorageType.FILE
        or config.num_replicas != 1
        or min(
            config.max_age,
            config.max_bytes,
            config.max_msgs,
            config.max_msg_size,
        )
        <= 0
    ):
        raise RuntimeError(
            f"{stream_name} storage, replica, or finite capacity policy drifted"
        )
    expected = {
        durable: (
            filter_subject,
            ack_wait,
            max_deliver,
            max_pending,
            max_waiting,
        )
        for durable, filter_subject, ack_wait, max_deliver, max_pending, max_waiting in definitions
    }
    for route in routes.values():
        if route["durable"] not in expected:
            raise RuntimeError(
                f"unprovisioned durable in route {route['durable']}"
            )
        filter_subject, ack_wait, max_deliver, max_pending, max_waiting = (
            expected[route["durable"]]
        )
        if route["subject"] != filter_subject:
            raise RuntimeError(
                f"registered route filter drifted for {route['durable']}"
            )
        try:
            info = await js.consumer_info(stream_name, route["durable"])
        except Exception as exc:
            raise RuntimeError(
                f"required work durable {stream_name}/{route['durable']} is missing"
            ) from exc
        consumer = info.config
        if consumer.filter_subject != filter_subject:
            raise RuntimeError(
                f"work durable {route['durable']} has an unexpected filter"
            )
        if consumer.ack_policy != AckPolicy.EXPLICIT:
            raise RuntimeError(
                f"work durable {route['durable']} must use explicit ACK"
            )
        ack_wait_value = consumer.ack_wait
        if hasattr(ack_wait_value, "total_seconds"):
            ack_wait_value = ack_wait_value.total_seconds()
        actual = (
            ack_wait_value,
            consumer.max_deliver,
            consumer.max_ack_pending,
            consumer.max_waiting,
        )
        if actual != (ack_wait, max_deliver, max_pending, max_waiting):
            raise RuntimeError(
                f"work durable {route['durable']} retry or pending limits drifted"
            )
        deliver_policy = getattr(consumer, "deliver_policy", None)
        replay_policy = getattr(consumer, "replay_policy", None)
        deliver_policy = getattr(deliver_policy, "value", deliver_policy)
        replay_policy = getattr(replay_policy, "value", replay_policy)
        if (
            getattr(consumer, "deliver_subject", None) is not None
            or deliver_policy != "all"
            or replay_policy != "instant"
        ):
            raise RuntimeError(
                f"work durable {route['durable']} delivery policy drifted"
            )


def claim() -> dict | None:
    """Atomically claim one pending event from this relay's own database."""
    with psycopg.connect(DB_URL, connect_timeout=5) as connection:
        with connection.cursor() as cur:
            cur.execute(
                """WITH next_event AS (
                  SELECT event_id FROM outbox_event
                  WHERE published_at IS NULL AND available_at <= now()
                  ORDER BY occurred_at, event_id
                  FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE outbox_event e SET attempts = e.attempts + 1
                FROM next_event n WHERE e.event_id = n.event_id
                RETURNING e.event_id, e.event_type, e.producer,
                  e.aggregate_type, e.aggregate_id, e.payload,
                  e.occurred_at, e.attempts"""
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "eventId": str(row[0]),
                "eventType": row[1],
                "producer": row[2],
                "aggregateType": row[3],
                "aggregateId": str(row[4]),
                "payload": row[5],
                "occurredAt": row[6],
                "attempts": row[7],
            }


def _safe_error(error: Exception) -> str:
    # Keep errors useful for operators without retaining newlines or huge text.
    return re.sub(r"[\r\n\t]+", " ", str(error))[:1000]


def mark_published(event_id: str) -> None:
    """Record broker ack; resolve an earlier dead-letter after a redrive."""
    with psycopg.connect(DB_URL, connect_timeout=5) as connection:
        connection.execute(
            "UPDATE outbox_event SET published_at = now(), last_error = NULL WHERE event_id = %s",
            (event_id,),
        )
        connection.execute(
            "UPDATE dead_letter_event SET resolved_at = now() "
            "WHERE event_id = %s AND resolved_at IS NULL",
            (event_id,),
        )


def retry_delay(attempts: int) -> float:
    """Exponential retry with bounded jitter to avoid synchronized retries."""
    base = min(300, 2 ** min(max(1, attempts), 8))
    return min(300, max(1, random.uniform(base * 0.8, base * 1.2)))


def mark_failed(
    event: dict, error: Exception, *, permanent: bool = False
) -> bool:
    """Retry transient failures or preserve permanent failures for redrive."""
    event_id = event["eventId"]
    event_type = event["eventType"]
    attempts = int(event["attempts"])
    error_text = _safe_error(error)
    dead_letter = permanent or attempts >= MAX_ATTEMPTS
    with psycopg.connect(DB_URL, connect_timeout=5) as connection:
        if dead_letter:
            connection.execute(
                """INSERT INTO dead_letter_event(
                     event_id, event_type, payload, attempts, error,
                     dead_lettered_at, resolved_at
                   ) VALUES (%s, %s, %s::jsonb, %s, %s, now(), NULL)
                   ON CONFLICT (event_id) DO UPDATE SET
                     event_type = EXCLUDED.event_type,
                     payload = EXCLUDED.payload,
                     attempts = EXCLUDED.attempts,
                     error = EXCLUDED.error,
                     dead_lettered_at = now(),
                     resolved_at = NULL""",
                (
                    event_id,
                    event_type,
                    json.dumps(event["payload"], separators=(",", ":")),
                    attempts,
                    error_text,
                ),
            )
            connection.execute(
                "UPDATE outbox_event SET published_at = now(), last_error = %s WHERE event_id = %s",
                (f"dead-lettered: {error_text}", event_id),
            )
        else:
            delay = retry_delay(attempts)
            connection.execute(
                "UPDATE outbox_event SET available_at = now() + make_interval(secs => %s), last_error = %s WHERE event_id = %s",
                (delay, error_text, event_id),
            )
    return dead_letter


def refresh_database_metrics() -> None:
    """Refresh bounded backlog gauges without reading or exporting payloads."""
    try:
        with psycopg.connect(DB_URL, connect_timeout=5) as connection:
            row = connection.execute(
                """SELECT count(*),
                     COALESCE(max(EXTRACT(EPOCH FROM (now() - occurred_at))), 0)
                   FROM outbox_event WHERE published_at IS NULL"""
            ).fetchone()
            dead_letters = connection.execute(
                "SELECT count(*) FROM dead_letter_event WHERE resolved_at IS NULL"
            ).fetchone()[0]
        PENDING_EVENTS.labels(WORKER_NAME).set(row[0])
        OLDEST_PENDING_AGE.labels(WORKER_NAME).set(max(0, row[1]))
        UNRESOLVED_DEAD_LETTERS.labels(WORKER_NAME).set(dead_letters)
        DATABASE_UP.labels(WORKER_NAME).set(1)
    except Exception:
        DATABASE_UP.labels(WORKER_NAME).set(0)
        LOG.exception("Unable to refresh outbox backlog metrics")


def _envelope(claimed: dict) -> dict:
    return event_envelope(
        (
            claimed["eventId"],
            claimed["eventType"],
            claimed["producer"],
            claimed["aggregateType"],
            claimed["aggregateId"],
            claimed["payload"],
            claimed["occurredAt"],
            claimed["attempts"],
        )
    )


async def relay_one(js, claimed: dict) -> None:
    """Publish one row, requiring JetStream ack before marking it complete."""
    event_id = claimed["eventId"]
    event_type = claimed["eventType"]
    try:
        envelope = _envelope(claimed)
        subject = event_subject(envelope)
        body = json.dumps(
            envelope, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if len(body) > MAX_MESSAGE_BYTES:
            raise OutboxContractError(
                f"serialized event exceeds {MAX_MESSAGE_BYTES} bytes"
            )
    except OutboxContractError as exc:
        try:
            is_dead_letter = await asyncio.to_thread(
                mark_failed, claimed, exc, permanent=True
            )
            if is_dead_letter:
                DEAD_LETTER_TOTAL.labels(WORKER_NAME, "contract").inc()
        except Exception:
            # The row remains unpublished if its failure cannot be persisted.
            # Leave it claimable so a later pass can persist the same failure.
            LOG.exception(
                "Unable to persist outbox contract failure",
                extra={"event_id": event_id, "event_type": event_type},
            )
        LOG.error(
            "Outbox event rejected by contract",
            extra={"event_id": event_id, "event_type": event_type},
        )
        return

    started = asyncio.get_running_loop().time()
    try:
        ack = await js.publish(
            subject,
            body,
            headers={"Nats-Msg-Id": event_id},
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        PUBLISH_DURATION.labels(WORKER_NAME).observe(
            asyncio.get_running_loop().time() - started
        )
        expected_stream = event_stream(envelope)
        if getattr(ack, "stream", expected_stream) != expected_stream:
            raise RuntimeError("JetStream acknowledged an unexpected stream")
    except Exception as exc:
        PUBLISH_DURATION.labels(WORKER_NAME).observe(
            asyncio.get_running_loop().time() - started
        )
        # Metric labels must stay bounded regardless of exception text/type.
        failure_class = "publish"
        try:
            is_dead_letter = await asyncio.to_thread(mark_failed, claimed, exc)
            if is_dead_letter:
                DEAD_LETTER_TOTAL.labels(WORKER_NAME, "publish").inc()
            else:
                RETRY_TOTAL.labels(WORKER_NAME, failure_class).inc()
        except Exception:
            LOG.exception(
                "Unable to persist outbox publish failure",
                extra={"event_id": event_id, "event_type": event_type},
            )
        LOG.warning(
            "JetStream publish failed",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "failure_class": failure_class,
            },
        )
        return

    PUBLISHED_TOTAL.labels(WORKER_NAME).inc()
    try:
        await asyncio.to_thread(mark_published, event_id)
    except Exception:
        # The ack may be durable while the DB mark failed. Leave the row
        # pending; the next publish uses the exact same Nats-Msg-Id.
        LOG.exception(
            "JetStream acknowledged event but outbox mark failed; retry is safe",
            extra={"event_id": event_id, "event_type": event_type},
        )


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if METRICS_PORT:
        start_http_server(METRICS_PORT, addr="0.0.0.0")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop_event.set)

    nc = NATS()
    connection_retry_delay = 1

    async def disconnected() -> None:
        NATS_UP.labels(WORKER_NAME).set(0)

    async def reconnected() -> None:
        NATS_UP.labels(WORKER_NAME).set(1)

    while not stop_event.is_set():
        try:
            await nc.connect(
                NATS_URL,
                name=WORKER_NAME,
                connect_timeout=5,
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                ping_interval=20,
                max_outstanding_pings=5,
                pending_size=8 * 1024 * 1024,
                disconnected_cb=disconnected,
                reconnected_cb=reconnected,
            )
            NATS_UP.labels(WORKER_NAME).set(1)
            break
        except Exception:
            NATS_UP.labels(WORKER_NAME).set(0)
            LOG.exception("Unable to connect to cluster-internal NATS")
            await asyncio.sleep(connection_retry_delay)
            connection_retry_delay = min(connection_retry_delay * 2, 30)
    if stop_event.is_set():
        return

    try:
        await ensure_stream(nc)
    except Exception:
        NATS_UP.labels(WORKER_NAME).set(0)
        await nc.close()
        raise

    js = nc.jetstream()
    last_metrics = 0.0
    db_retry_delay = 1
    try:
        while not stop_event.is_set():
            now = loop.time()
            if now >= last_metrics:
                await asyncio.to_thread(refresh_database_metrics)
                last_metrics = now + 15
            try:
                claimed = await asyncio.to_thread(claim)
                DATABASE_UP.labels(WORKER_NAME).set(1)
                db_retry_delay = 1
            except Exception:
                DATABASE_UP.labels(WORKER_NAME).set(0)
                LOG.exception("Unable to claim an outbox event")
                await asyncio.sleep(db_retry_delay)
                db_retry_delay = min(db_retry_delay * 2, 30)
                continue
            if claimed is None:
                await asyncio.sleep(1)
                continue
            await relay_one(js, claimed)
    finally:
        NATS_UP.labels(WORKER_NAME).set(0)
        await nc.drain()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
