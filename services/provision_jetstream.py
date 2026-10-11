"""Drift-checked JetStream topology provisioner with one guarded Phase 6 migration.

Existing topology is create-only except for the explicitly gated, empty-stream
MYOTA_EVENTS Interest-to-Limits migration. That migration refuses any retained
message, unexpected subject/configuration, pending consumer state, or extra
durable. All other mismatches remain hard failures.
"""

from __future__ import annotations

import asyncio
import os
import sys

from nats.aio.client import Client as NATS
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    DiscardPolicy,
    RetentionPolicy,
    ReplayPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.errors import NotFoundError

from jetstream_topology import Consumer, Stream, topology_from_environment


def stream_config(stream: Stream) -> StreamConfig:
    return StreamConfig(
        name=stream.name,
        subjects=list(stream.subjects),
        retention=RetentionPolicy.LIMITS
        if stream.retention == "limits"
        else RetentionPolicy.WORK_QUEUE,
        storage=StorageType.FILE,
        num_replicas=stream.replicas,
        max_age=stream.max_age_seconds,
        max_bytes=stream.max_bytes,
        max_msgs=stream.max_messages,
        max_msg_size=stream.max_message_bytes,
        discard=DiscardPolicy.NEW,
    )


def consumer_config(consumer: Consumer) -> ConsumerConfig:
    return ConsumerConfig(
        durable_name=consumer.durable,
        filter_subject=consumer.filter_subject,
        deliver_policy=DeliverPolicy.ALL,
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=consumer.ack_wait_seconds,
        max_deliver=consumer.max_deliveries,
        max_ack_pending=consumer.max_ack_pending,
        max_waiting=consumer.max_waiting,
        replay_policy=ReplayPolicy.INSTANT,
        num_replicas=0,
        mem_storage=False,
        headers_only=False,
    )


def _value(value):
    return getattr(value, "value", value)


def validate_stream(actual, desired: StreamConfig) -> None:
    config = actual.config
    fields = {
        "subjects": (set(config.subjects or []), set(desired.subjects or [])),
        "retention": (_value(config.retention), _value(desired.retention)),
        "storage": (_value(config.storage), _value(desired.storage)),
        "replicas": (config.num_replicas, desired.num_replicas),
        "max_age": (config.max_age, desired.max_age),
        "max_bytes": (config.max_bytes, desired.max_bytes),
        "max_msgs": (config.max_msgs, desired.max_msgs),
        "max_msg_size": (config.max_msg_size, desired.max_msg_size),
        "discard": (_value(config.discard), _value(desired.discard)),
    }
    drift = [key for key, pair in fields.items() if pair[0] != pair[1]]
    if drift:
        raise RuntimeError(
            f"stream {desired.name} configuration drift ({', '.join(drift)}); "
            "existing streams are never changed by this provisioner"
        )


def validate_consumer(actual, desired: ConsumerConfig, stream: str) -> None:
    config = actual.config
    fields = {
        "filter_subject": (config.filter_subject, desired.filter_subject),
        "deliver_policy": (
            _value(config.deliver_policy),
            _value(desired.deliver_policy),
        ),
        "ack_policy": (_value(config.ack_policy), _value(desired.ack_policy)),
        "ack_wait": (config.ack_wait, desired.ack_wait),
        "max_deliver": (config.max_deliver, desired.max_deliver),
        "max_ack_pending": (config.max_ack_pending, desired.max_ack_pending),
        "max_waiting": (config.max_waiting, desired.max_waiting),
        "replay_policy": (
            _value(config.replay_policy),
            _value(desired.replay_policy),
        ),
        "num_replicas": (config.num_replicas, desired.num_replicas),
        # The server may omit false-valued optional fields in its info reply.
        # Treat omitted and false as the same effective delivery behavior.
        "mem_storage": (bool(config.mem_storage), bool(desired.mem_storage)),
        "headers_only": (
            bool(config.headers_only),
            bool(desired.headers_only),
        ),
        "deliver_subject": (
            config.deliver_subject or None,
            desired.deliver_subject,
        ),
        "deliver_group": (config.deliver_group or None, desired.deliver_group),
        "filter_subjects": (
            config.filter_subjects or None,
            desired.filter_subjects,
        ),
    }
    drift = [key for key, pair in fields.items() if pair[0] != pair[1]]
    if drift:
        raise RuntimeError(
            f"durable {stream}/{desired.durable_name} configuration drift "
            f"({', '.join(drift)}); create an explicitly reviewed successor durable"
        )


async def migrate_shared_event_stream(js, desired_stream: Stream, consumers) -> None:
    """Apply the one-time Interest-to-Limits cutover only after strict preflight."""
    if os.environ.get("NATS_EVENTS_RETENTION_MIGRATION") != "1":
        return
    if os.environ.get("NATS_TOPOLOGY_SCOPE", "all") != "all":
        raise RuntimeError("event retention migration requires topology scope=all")
    target = stream_config(desired_stream)
    try:
        info = await js.stream_info("MYOTA_EVENTS")
    except NotFoundError as exc:
        raise RuntimeError("MYOTA_EVENTS must already exist for in-place migration") from exc
    config = info.config
    if (
        set(config.subjects or []) == set(target.subjects or [])
        and _value(config.retention) == _value(target.retention)
        and config.max_bytes == target.max_bytes
        and config.max_msgs == target.max_msgs
        and config.max_msg_size == target.max_msg_size
        and _value(config.discard) == _value(target.discard)
    ):
        print("MYOTA_EVENTS already matches the target; migration is a no-op")
        return
    expected_legacy = {
        "subjects": {"myota.events.>", "myota.geodata.>"},
        "retention": RetentionPolicy.INTEREST.value,
        "storage": StorageType.FILE.value,
        "replicas": 1,
        "max_bytes": -1,
        "max_msgs": -1,
        "max_msg_size": -1,
        "discard": DiscardPolicy.OLD.value,
    }
    actual = {
        "subjects": set(config.subjects or []),
        "retention": _value(config.retention),
        "storage": _value(config.storage),
        "replicas": config.num_replicas,
        "max_bytes": config.max_bytes,
        "max_msgs": config.max_msgs,
        "max_msg_size": config.max_msg_size,
        "discard": _value(config.discard),
    }
    if actual != expected_legacy or config.max_age != desired_stream.max_age_seconds:
        raise RuntimeError("MYOTA_EVENTS is not the reviewed legacy configuration")
    state = info.state
    if state.messages != 0 or state.bytes != 0 or state.consumer_count != 1:
        raise RuntimeError(
            "MYOTA_EVENTS migration requires zero messages/bytes and exactly "
            "the single Activity notification durable"
        )
    try:
        durable = await js.consumer_info("MYOTA_EVENTS", "activity-notifications-v1")
    except Exception as exc:
        raise RuntimeError("expected Activity notification durable is missing") from exc
    consumer = durable.config
    if (
        durable.num_pending != 0
        or durable.num_ack_pending != 0
        or durable.num_redelivered != 0
        or consumer.ack_policy != AckPolicy.EXPLICIT
        or consumer.deliver_subject is not None
        or not (consumer.filter_subjects or consumer.filter_subject)
    ):
        raise RuntimeError("Activity notification durable is not drained and pull-based")

    await js.update_stream(target)
    migrated = await js.stream_info("MYOTA_EVENTS")
    validate_stream(migrated, target)
    print("migrated MYOTA_EVENTS to bounded Limits retention")


async def ensure_stream(js, desired: Stream) -> None:
    config = stream_config(desired)
    try:
        actual = await js.stream_info(desired.name)
    except NotFoundError:
        await js.add_stream(config)
        actual = await js.stream_info(desired.name)
    validate_stream(actual, config)


async def ensure_consumer(js, desired: Consumer) -> None:
    config = consumer_config(desired)
    try:
        actual = await js.consumer_info(desired.stream, desired.durable)
    except NotFoundError:
        await js.add_consumer(desired.stream, config)
        actual = await js.consumer_info(desired.stream, desired.durable)
    validate_consumer(actual, config, desired.stream)


async def main() -> None:
    streams, consumers = topology_from_environment()
    nc = NATS()
    await nc.connect(
        os.environ.get("NATS_URL", "nats://nats:4222"),
        name="myota-jetstream-provisioner",
        reconnect_time_wait=2,
        max_reconnect_attempts=3,
    )
    try:
        js = nc.jetstream()
        if os.environ.get("NATS_EVENTS_RETENTION_MIGRATION") == "1":
            event_stream = next(
                (stream for stream in streams if stream.name == "MYOTA_EVENTS"),
                None,
            )
            if event_stream is None:
                raise RuntimeError("event retention migration requires MYOTA_EVENTS")
            await migrate_shared_event_stream(js, event_stream, consumers)
        for stream in streams:
            await ensure_stream(js, stream)
            print(f"validated stream {stream.name}")
        for consumer in consumers:
            await ensure_consumer(js, consumer)
            print(f"validated durable {consumer.stream}/{consumer.durable}")
    finally:
        await nc.drain()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"JetStream provisioning failed: {exc}", file=sys.stderr)
        raise
