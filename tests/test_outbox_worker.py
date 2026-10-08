"""Tests for durable outbox event envelopes and JetStream routing."""

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from outbox_routing import event_envelope, event_subject


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


if __name__ == "__main__":
    unittest.main()
