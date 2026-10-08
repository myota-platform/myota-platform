"""Tests for durable outbox event envelopes and JetStream routing."""

from datetime import datetime, timezone
import os
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path

os.environ.setdefault(
    "OUTBOX_DATABASE_URL", "postgresql://test:test@127.0.0.1/test"
)

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from outbox_routing import event_envelope, event_subject
from nats.js.api import AckPolicy, RetentionPolicy
from outbox_worker import STREAM_NAME, ensure_stream, required_consumers


class OutboxWorkerTests(unittest.TestCase):
    def test_explicit_geodata_subject_is_used_for_queue_events(self):
        event = {
            "eventType": "geodata.entity-deletion-job.queued.v1",
            "payload": {
                "jobId": "job-123",
                "natsSubject": "myota.geodata.entity.delete.v1",
            },
        }

        self.assertEqual(
            event_subject(event), "myota.geodata.entity.delete.v1"
        )

    def test_events_without_subject_keep_generic_event_routing(self):
        event = {
            "eventType": "identity.account.created.v1",
            "payload": {},
        }

        self.assertEqual(
            event_subject(event),
            "myota.events.identity_account_created_v1",
        )

    def test_explicit_subject_is_limited_to_geodata_namespace(self):
        with self.assertRaisesRegex(ValueError, "unsupported explicit"):
            event_subject(
                {
                    "eventType": "geodata.entity-deletion-job.queued.v1",
                    "payload": {"natsSubject": "other.service.delete"},
                }
            )

    def test_explicit_geodata_queue_must_have_a_durable_consumer(self):
        with self.assertRaisesRegex(ValueError, "unsupported explicit"):
            event_subject(
                {
                    "eventType": "geodata.entity.updated.v1",
                    "payload": {"natsSubject": "myota.geodata.unhandled.v1"},
                }
            )

    def test_claimed_row_becomes_complete_json_safe_envelope(self):
        occurred_at = datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
        event = event_envelope(
            (
                "job-123",
                "geodata.entity-deletion-job.queued.v1",
                "geodata-service",
                "entity_deletion_job",
                "job-123",
                {
                    "jobId": "job-123",
                    "natsSubject": "myota.geodata.entity.delete.v1",
                },
                occurred_at,
                1,
            )
        )

        self.assertEqual(event["aggregate"]["id"], "job-123")
        self.assertEqual(event["occurredAt"], "2026-10-08T12:30:00Z")
        self.assertEqual(event["payload"]["jobId"], "job-123")


class OutboxRetentionTests(unittest.IsolatedAsyncioTestCase):
    class FakeJetStream:
        def __init__(self, initial_stream=None, consumers=None):
            self.stream = initial_stream
            self.consumers = consumers or {}
            self.calls = []

        async def stream_info(self, name):
            if name != STREAM_NAME or self.stream is None:
                raise LookupError("stream not found")
            return self.stream

        async def add_stream(self, config):
            self.calls.append(("add_stream", config.retention))
            self.stream = SimpleNamespace(config=config)
            return self.stream

        async def update_stream(self, config):
            self.calls.append(("update_stream", config.retention))
            self.stream.config = config
            return self.stream

        async def consumer_info(self, stream, durable):
            if stream != STREAM_NAME or durable not in self.consumers:
                raise LookupError("consumer not found")
            return self.consumers[durable]

        async def add_consumer(self, stream, config):
            self.calls.append(("add_consumer", config.durable_name))
            self.consumers[config.durable_name] = SimpleNamespace(
                config=config
            )

    class FakeNats:
        def __init__(self, jetstream):
            self._jetstream = jetstream

        def jetstream(self):
            return self._jetstream

    async def test_registers_durables_before_switching_to_interest_retention(
        self,
    ):
        jetstream = self.FakeJetStream()

        await ensure_stream(self.FakeNats(jetstream))

        self.assertEqual(
            jetstream.stream.config.retention, RetentionPolicy.INTEREST
        )
        self.assertEqual(len(jetstream.consumers), 5)
        self.assertEqual(
            [
                durable
                for action, durable in jetstream.calls
                if action == "add_consumer"
            ],
            [consumer.durable_name for consumer in required_consumers()],
        )
        self.assertEqual(
            jetstream.calls[-1],
            ("update_stream", RetentionPolicy.INTEREST),
        )
        self.assertTrue(
            all(
                consumer.config.ack_policy == AckPolicy.EXPLICIT
                for consumer in jetstream.consumers.values()
            )
        )

    async def test_existing_interest_stream_keeps_all_durable_consumers(self):
        jetstream = self.FakeJetStream(
            SimpleNamespace(
                config=SimpleNamespace(
                    name=STREAM_NAME,
                    subjects=["myota.events.>", "myota.geodata.>"],
                    retention=RetentionPolicy.INTEREST,
                )
            )
        )

        await ensure_stream(self.FakeNats(jetstream))

        self.assertEqual(
            jetstream.stream.config.retention, RetentionPolicy.INTEREST
        )
        self.assertEqual(len(jetstream.consumers), 5)
        self.assertFalse(
            any(call[0] == "update_stream" for call in jetstream.calls)
        )

    async def test_mismatched_durable_filter_fails_before_retention_change(
        self,
    ):
        required = required_consumers()
        consumers = {
            required[0].durable_name: SimpleNamespace(
                config=SimpleNamespace(
                    filter_subject="myota.events.>",
                    ack_policy=AckPolicy.EXPLICIT,
                )
            ),
            required[1].durable_name: SimpleNamespace(
                config=SimpleNamespace(
                    filter_subject="myota.geodata.unhandled.v1",
                    ack_policy=AckPolicy.EXPLICIT,
                )
            ),
        }
        jetstream = self.FakeJetStream(
            SimpleNamespace(
                config=SimpleNamespace(
                    name=STREAM_NAME,
                    subjects=["myota.events.>", "myota.geodata.>"],
                    retention=RetentionPolicy.LIMITS,
                )
            ),
            consumers=consumers,
        )

        with self.assertRaisesRegex(RuntimeError, "unexpected subject filter"):
            await ensure_stream(self.FakeNats(jetstream))

        self.assertEqual(
            jetstream.stream.config.retention, RetentionPolicy.LIMITS
        )


if __name__ == "__main__":
    unittest.main()
