"""One-shot, create-only JetStream topology provisioner.

It never mutates or deletes an existing stream or durable. A mismatch is a
hard failure that requires a reviewed migration, which prevents accidental
retention conversion of the existing shared MYOTA_EVENTS stream.
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
