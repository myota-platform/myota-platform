"""JetStream retention setup must preserve pending delivery semantics."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault(
    "OUTBOX_DATABASE_URL", "postgresql://test:test@127.0.0.1/test"
)
sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from nats.js.api import RetentionPolicy, StorageType
from outbox_routing import event_subject
from outbox_worker import STREAM_NAME, ensure_stream, required_consumers


class FakeJetStream:
    def __init__(self, stream=None, consumers=None):
        self.stream = stream
        self.consumers = consumers or {}
        self.calls = []

    async def stream_info(self, name):
        if name != STREAM_NAME or self.stream is None:
            raise LookupError("stream not found")
        return self.stream

    async def consumer_info(self, stream, durable):
        if stream != STREAM_NAME or durable not in self.consumers:
            raise LookupError("consumer not found")
        return self.consumers[durable]


class FakeNats:
    def __init__(self, jetstream):
        self._jetstream = jetstream

    def jetstream(self):
        return self._jetstream


class OutboxRetentionTests(unittest.IsolatedAsyncioTestCase):
    def test_activity_consumer_uses_exact_registered_event_filters(self):
        consumer = next(
            item
            for item in required_consumers()
            if item.durable_name == "activity-notifications-v1"
        )
        self.assertEqual(consumer.filter_subject, None)
        self.assertEqual(len(consumer.filter_subjects), 21)
        self.assertTrue(
            all(
                subject.startswith("myota.events.")
                for subject in consumer.filter_subjects
            )
        )
        self.assertNotIn("myota.events.>", consumer.filter_subjects)

    def test_geodata_work_requires_a_provisioned_queue(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            event_subject(
                {
                    "eventType": "geodata.other-work.queued.v1",
                    "payload": {"natsSubject": "myota.geodata.unhandled.v1"},
                }
            )

    async def test_legacy_topology_is_validated_without_mutation(self):
        js = FakeJetStream(
            SimpleNamespace(
                config=SimpleNamespace(
                    name=STREAM_NAME,
                    subjects=["myota.events.>", "myota.geodata.>"],
                    retention=RetentionPolicy.INTEREST,
                    storage=StorageType.FILE,
                )
            ),
            {
                consumer.durable_name: SimpleNamespace(config=consumer)
                for consumer in required_consumers()
            },
        )

        await ensure_stream(FakeNats(js))

        self.assertEqual(js.stream.config.retention, RetentionPolicy.INTEREST)
        self.assertEqual(len(js.consumers), len(required_consumers()))
        self.assertEqual(js.calls, [])

    async def test_missing_stream_fails_closed_without_creating_topology(self):
        js = FakeJetStream()
        with self.assertRaisesRegex(RuntimeError, "deployment-owned"):
            await ensure_stream(FakeNats(js))
        self.assertIsNone(js.stream)

    async def test_missing_consumer_fails_closed_without_mutation(self):
        js = FakeJetStream(
            SimpleNamespace(
                config=SimpleNamespace(
                    name=STREAM_NAME,
                    subjects=["myota.events.>", "myota.geodata.>"],
                    retention=RetentionPolicy.INTEREST,
                    storage=StorageType.FILE,
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "durable.*missing"):
            await ensure_stream(FakeNats(js))
        self.assertEqual(js.calls, [])


if __name__ == "__main__":
    unittest.main()
