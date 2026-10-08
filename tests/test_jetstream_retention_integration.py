"""Opt-in integration coverage for the MYOTA_EVENTS ack-retention contract."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from nats.aio.client import Client as NATS
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)

os.environ.setdefault(
    "OUTBOX_DATABASE_URL", "postgresql://test:test@127.0.0.1/test"
)
sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from outbox_worker import STREAM_NAME, ensure_stream


NATS_TEST_URL = os.environ.get("MYOTA_TEST_NATS_URL", "")


@unittest.skipUnless(
    NATS_TEST_URL,
    "set MYOTA_TEST_NATS_URL to a dedicated local NATS server",
)
class InterestRetentionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        host = urlparse(NATS_TEST_URL).hostname
        local_test_hosts = {
            "localhost",
            "127.0.0.1",
            "::1",
            "myota-nats-retention-test",
        }
        if host not in local_test_hosts:
            self.fail("integration test refuses non-local NATS endpoints")

        self.nc = NATS()
        await self.nc.connect(NATS_TEST_URL)
        self.js = self.nc.jetstream()
        try:
            await self.js.stream_info(STREAM_NAME)
        except Exception:
            return
        await self.nc.drain()
        self.fail("use a fresh, dedicated NATS server for this test")

    async def asyncTearDown(self) -> None:
        if not getattr(self, "nc", None) or not self.nc.is_connected:
            return
        try:
            await self.js.delete_stream(STREAM_NAME)
        finally:
            await self.nc.drain()

    async def test_ack_removes_message_but_pending_delivery_is_retained(self):
        await self.js.add_stream(
            StreamConfig(
                name=STREAM_NAME,
                subjects=["myota.events.>", "myota.geodata.>"],
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_age=30 * 24 * 60 * 60,
            )
        )
        subject = "myota.events.retention.integration.v1"
        await self.js.add_consumer(
            STREAM_NAME,
            ConsumerConfig(
                durable_name="activity-notifications-pull-v1",
                filter_subject="myota.events.>",
                ack_policy=AckPolicy.EXPLICIT,
                ack_wait=60,
                max_deliver=10,
                max_ack_pending=64,
            ),
        )
        sub = await self.js.pull_subscribe(
            "myota.events.>",
            stream=STREAM_NAME,
            durable="activity-notifications-pull-v1",
        )

        await self.js.publish(
            subject,
            b"already-acked",
            headers={"Nats-Msg-Id": str(uuid4())},
        )
        already_acked = (await sub.fetch(batch=1, timeout=2))[0]
        await already_acked.ack()
        await self.js.publish(
            subject,
            b"keep-pending",
            headers={"Nats-Msg-Id": str(uuid4())},
        )

        before = await self.js.stream_info(STREAM_NAME)
        self.assertEqual(before.state.messages, 2)

        # Simulate upgrading the existing Limits stream while one message is
        # acknowledged and another is still waiting on its durable consumer.
        await ensure_stream(self.nc)
        info = await self.js.stream_info(STREAM_NAME)
        consumer = await self.js.consumer_info(
            STREAM_NAME, "activity-notifications-pull-v1"
        )
        self.assertEqual(info.config.retention, RetentionPolicy.INTEREST)
        self.assertEqual(info.state.messages, 1)
        self.assertEqual(consumer.num_pending, 1)

        pending = (await sub.fetch(batch=1, timeout=2))[0]
        await pending.ack()

        for _ in range(40):
            info = await self.js.stream_info(STREAM_NAME)
            if info.state.messages == 0:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(info.state.messages, 0)

        await self.js.publish(
            subject,
            b"leave-pending",
            headers={"Nats-Msg-Id": str(uuid4())},
        )
        info = await self.js.stream_info(STREAM_NAME)
        consumer = await self.js.consumer_info(
            STREAM_NAME, "activity-notifications-pull-v1"
        )
        self.assertEqual(info.state.messages, 1)
        self.assertEqual(consumer.num_pending, 1)


if __name__ == "__main__":
    unittest.main()
