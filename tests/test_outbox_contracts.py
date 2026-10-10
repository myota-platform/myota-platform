"""Relay contract, compatibility, and broker-failure behavior tests."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault(
    "OUTBOX_DATABASE_URL", "postgresql://test:test@127.0.0.1/test"
)
sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from outbox_routing import OutboxContractError, event_envelope, event_subject
from outbox_worker import relay_one, retry_delay


EVENT_ID = "3e29e282-6c20-4c6d-8e2a-3d7490c3df40"
OCCURRED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def row(
    event_type="identity.account.created.v1",
    producer="identity",
    payload=None,
):
    return (
        EVENT_ID,
        event_type,
        producer,
        "account",
        "d1cedf47-6d04-48d5-85d8-6c6d64b0ec65",
        payload or {"accountId": "d1cedf47-6d04-48d5-85d8-6c6d64b0ec65"},
        OCCURRED_AT,
        1,
    )


def claimed(
    event_type="identity.account.created.v1", producer="identity", payload=None
):
    values = row(event_type, producer, payload)
    return {
        "eventId": str(values[0]),
        "eventType": values[1],
        "producer": values[2],
        "aggregateType": values[3],
        "aggregateId": values[4],
        "payload": values[5],
        "occurredAt": values[6],
        "attempts": values[7],
    }


class FakeJetStream:
    def __init__(self, error=None):
        self.error = error
        self.published = []

    async def publish(self, subject, body, headers, timeout):
        self.published.append((subject, body, headers, timeout))
        if self.error:
            raise self.error
        return type("Ack", (), {"stream": "MYOTA_EVENTS"})()


class OutboxContractTests(unittest.TestCase):
    def test_domain_fact_uses_registered_dotted_subject_and_v1_envelope(self):
        envelope = event_envelope(row())
        self.assertEqual(
            event_subject(envelope), "myota.events.identity.account.created.v1"
        )
        self.assertEqual(envelope["envelopeVersion"], 1)
        self.assertNotIn("attempts", envelope)
        self.assertEqual(envelope["eventId"], EVENT_ID)
        self.assertEqual(envelope["occurredAt"], "2026-10-10T12:00:00.000000Z")

    def test_legacy_geodata_work_keeps_subject_until_phase_five(self):
        work = event_envelope(
            row(
                "geodata.entity-deletion-job.queued.v1",
                "geodata",
                {
                    "jobId": "job-1",
                    "natsSubject": "myota.geodata.entity.delete.v1",
                },
            )
        )
        self.assertEqual(event_subject(work), "myota.geodata.entity.delete.v1")
        self.assertNotIn("envelopeVersion", work)
        self.assertNotIn("attempts", work)

    def test_unknown_event_and_subject_override_are_rejected(self):
        with self.assertRaisesRegex(OutboxContractError, "unregistered"):
            event_subject({"eventType": "identity.unknown.v1", "payload": {}})
        with self.assertRaisesRegex(OutboxContractError, "override"):
            event_subject(
                {
                    "eventType": "identity.account.created.v1",
                    "payload": {"natsSubject": "myota.events.other.v1"},
                }
            )

    def test_legacy_work_subject_must_match_registered_source_type(self):
        with self.assertRaisesRegex(OutboxContractError, "unexpected subject"):
            event_subject(
                {
                    "eventType": "geodata.entity-deletion-job.queued.v1",
                    "payload": {"natsSubject": "myota.geodata.other.v1"},
                }
            )

    def test_registered_producer_is_required(self):
        with self.assertRaisesRegex(OutboxContractError, "producer"):
            event_envelope(row(producer="programme-service"))

    def test_naive_timestamp_is_rejected(self):
        values = list(row())
        values[6] = datetime(2026, 10, 10, 12, 0)
        with self.assertRaisesRegex(OutboxContractError, "timezone"):
            event_envelope(tuple(values))

    def test_retry_delay_is_exponential_and_capped(self):
        self.assertGreaterEqual(retry_delay(1), 1)
        self.assertLessEqual(retry_delay(1), 3)
        self.assertLessEqual(retry_delay(100), 300)


class RelayFailureWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_id_is_sent_and_marked_only_after_broker_ack(self):
        js = FakeJetStream()
        event = claimed()
        with patch("outbox_worker.mark_published") as mark:
            await relay_one(js, event)
        self.assertEqual(len(js.published), 1)
        subject, _, headers, timeout = js.published[0]
        self.assertEqual(subject, "myota.events.identity.account.created.v1")
        self.assertEqual(headers["Nats-Msg-Id"], EVENT_ID)
        self.assertGreater(timeout, 0)
        mark.assert_called_once_with(EVENT_ID)

    async def test_publish_failure_schedules_retry_without_marking_published(
        self,
    ):
        js = FakeJetStream(error=TimeoutError("ack timeout"))
        with (
            patch("outbox_worker.mark_failed", return_value=False) as failed,
            patch("outbox_worker.mark_published") as published,
        ):
            await relay_one(js, claimed())
        failed.assert_called_once()
        published.assert_not_called()

    async def test_database_mark_failure_leaves_acknowledged_event_for_safe_retry(
        self,
    ):
        js = FakeJetStream()
        with (
            patch(
                "outbox_worker.mark_published", side_effect=OSError("db down")
            ),
            patch("outbox_worker.mark_failed") as failed,
            patch("outbox_worker.LOG") as logger,
        ):
            await relay_one(js, claimed())
        self.assertEqual(len(js.published), 1)
        failed.assert_not_called()
        logger.exception.assert_called_once()

    async def test_unknown_route_is_dead_lettered_without_broker_publish(self):
        js = FakeJetStream()
        event = claimed("identity.not-registered.v1")
        with patch("outbox_worker.mark_failed") as failed:
            await relay_one(js, event)
        failed.assert_called_once()
        self.assertTrue(failed.call_args.kwargs["permanent"])
        self.assertEqual(js.published, [])

    async def test_oversized_envelope_is_dead_lettered_without_publish(self):
        js = FakeJetStream()
        event = claimed(payload={"large": "x" * 2048})
        with (
            patch("outbox_worker.MAX_MESSAGE_BYTES", 1024),
            patch("outbox_worker.mark_failed") as failed,
        ):
            await relay_one(js, event)
        failed.assert_called_once()
        self.assertTrue(failed.call_args.kwargs["permanent"])
        self.assertEqual(js.published, [])

    async def test_contract_failure_persistence_error_leaves_row_retryable(
        self,
    ):
        js = FakeJetStream()
        event = claimed("identity.not-registered.v1")
        with (
            patch("outbox_worker.mark_failed", side_effect=OSError("db down")),
            patch("outbox_worker.LOG") as logger,
        ):
            await relay_one(js, event)
        self.assertEqual(js.published, [])
        logger.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
