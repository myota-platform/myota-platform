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
from datetime import datetime, timezone

import psycopg
from nats.aio.client import Client as NATS
from nats.js.api import RetentionPolicy, StorageType, StreamConfig


DB_URL = os.environ["OUTBOX_DATABASE_URL"]
NATS_URL = os.environ.get("NATS_URL", "nats://nats:4222")
MAX_ATTEMPTS = int(os.environ.get("OUTBOX_MAX_ATTEMPTS", "12"))
WORKER_NAME = os.environ.get("OUTBOX_WORKER", "myota-outbox")


async def ensure_stream(nc: NATS) -> None:
    js = nc.jetstream()
    try:
        await js.stream_info("MYOTA_EVENTS")
    except Exception:
        try:
            await js.add_stream(StreamConfig(name="MYOTA_EVENTS", subjects=["myota.events.>"],
                                             retention=RetentionPolicy.LIMITS, storage=StorageType.FILE,
                                             max_age=30 * 24 * 60 * 60))
        except Exception:
            # Two relays can start concurrently; the winner creates the stream.
            await js.stream_info("MYOTA_EVENTS")


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
            RETURNING e.event_id, e.event_type, e.payload, e.attempts""")
            row = cur.fetchone()
            if not row:
                return None
            return {"eventId": str(row[0]), "eventType": row[1], "payload": row[2], "attempts": row[3]}


def mark_published(event_id: str) -> None:
    with psycopg.connect(DB_URL) as connection:
        connection.execute("UPDATE outbox_event SET published_at = now(), last_error = NULL WHERE event_id = %s", (event_id,))


def mark_failed(event: dict, error: Exception) -> None:
    with psycopg.connect(DB_URL) as connection:
        if event["attempts"] >= MAX_ATTEMPTS:
            connection.execute("""INSERT INTO dead_letter_event(event_id, event_type, payload, attempts, error)
                VALUES (%s, %s, %s::jsonb, %s, %s) ON CONFLICT (event_id) DO NOTHING""",
                               (event["eventId"], event["eventType"], json.dumps(event["payload"]), event["attempts"], str(error)))
            connection.execute("UPDATE outbox_event SET published_at = now(), last_error = %s WHERE event_id = %s",
                               (f"dead-lettered: {error}", event["eventId"]))
        else:
            delay = min(300, 2 ** min(event["attempts"], 8))
            connection.execute("UPDATE outbox_event SET available_at = now() + make_interval(secs => %s), last_error = %s WHERE event_id = %s",
                               (delay, str(error), event["eventId"]))


async def main() -> None:
    nc = NATS()
    await nc.connect(NATS_URL, name=WORKER_NAME, reconnect_time_wait=2, max_reconnect_attempts=-1)
    await ensure_stream(nc)
    js = nc.jetstream()
    try:
        while True:
            event = await asyncio.to_thread(claim)
            if not event:
                await asyncio.sleep(1)
                continue
            try:
                subject = "myota.events." + event["eventType"].replace(".", "_")
                await js.publish(subject, json.dumps(event).encode(), headers={"Nats-Msg-Id": event["eventId"]})
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
