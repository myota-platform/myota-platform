from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from jetstream_topology import desired_topology, topology_from_environment
from provision_jetstream import consumer_config, validate_consumer


CAPACITY = {
    "NATS_EVENTS_MAX_BYTES": "1048576",
    "NATS_EVENTS_MAX_MESSAGES": "1000",
    "NATS_EVENTS_MAX_MESSAGE_BYTES": "65536",
    "NATS_ACTIVITY_WORK_MAX_AGE_SECONDS": "604800",
    "NATS_ACTIVITY_WORK_MAX_BYTES": "1048576",
    "NATS_ACTIVITY_WORK_MAX_MESSAGES": "1000",
    "NATS_ACTIVITY_WORK_MAX_MESSAGE_BYTES": "65536",
    "NATS_GEODATA_WORK_MAX_AGE_SECONDS": "2592000",
    "NATS_GEODATA_WORK_MAX_BYTES": "1048576",
    "NATS_GEODATA_WORK_MAX_MESSAGES": "1000",
    "NATS_GEODATA_WORK_MAX_MESSAGE_BYTES": "65536",
}


class JetStreamTopologyTests(unittest.TestCase):
    def test_no_capacity_defaults_are_invented(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "must be set"):
                desired_topology()

    def test_apply_requires_explicit_operator_opt_in(self):
        with patch.dict(os.environ, CAPACITY, clear=True):
            with self.assertRaisesRegex(RuntimeError, "NATS_TOPOLOGY_APPLY"):
                topology_from_environment()

    def test_target_topology_is_finite_and_work_filters_are_separate(self):
        with patch.dict(os.environ, CAPACITY, clear=True):
            streams, consumers = desired_topology()
        self.assertEqual(
            [stream.name for stream in streams],
            ["MYOTA_EVENTS", "MYOTA_ACTIVITY_WORK", "MYOTA_GEODATA_WORK"],
        )
        self.assertEqual(len(consumers), 10)
        self.assertTrue(
            all(
                stream.max_bytes > 0 and stream.max_messages > 0
                for stream in streams
            )
        )
        self.assertEqual(
            len({(item.stream, item.filter_subject) for item in consumers}), 10
        )
        self.assertFalse(
            any(
                item.filter_subject.startswith("myota.events.")
                for item in consumers
            )
        )

    def test_activity_work_scope_leaves_fact_and_geodata_topology_untouched(
        self,
    ):
        activity_capacity = {
            key: value
            for key, value in CAPACITY.items()
            if key.startswith("NATS_ACTIVITY_WORK_")
        }
        with patch.dict(os.environ, activity_capacity, clear=True):
            streams, consumers = desired_topology("activity-work")
        self.assertEqual(
            [stream.name for stream in streams], ["MYOTA_ACTIVITY_WORK"]
        )
        self.assertEqual(len(consumers), 6)
        self.assertTrue(
            all(item.stream == "MYOTA_ACTIVITY_WORK" for item in consumers)
        )

    def test_activity_work_scope_can_be_provisioned_without_event_cutover(
        self,
    ):
        activity_capacity = {
            key: value
            for key, value in CAPACITY.items()
            if key.startswith("NATS_ACTIVITY_WORK_")
        }
        with patch.dict(
            os.environ,
            {
                **activity_capacity,
                "NATS_TOPOLOGY_APPLY": "1",
                "NATS_TOPOLOGY_SCOPE": "activity-work",
            },
            clear=True,
        ):
            streams, consumers = topology_from_environment()
        self.assertEqual(
            [stream.name for stream in streams], ["MYOTA_ACTIVITY_WORK"]
        )
        self.assertEqual(len(consumers), 6)

    def test_geodata_work_scope_can_be_provisioned_without_other_streams(self):
        geodata_capacity = {
            key: value
            for key, value in CAPACITY.items()
            if key.startswith("NATS_GEODATA_WORK_")
        }
        with patch.dict(os.environ, geodata_capacity, clear=True):
            streams, consumers = desired_topology("geodata-work")
        self.assertEqual(
            [stream.name for stream in streams], ["MYOTA_GEODATA_WORK"]
        )
        self.assertEqual(len(consumers), 4)
        self.assertTrue(
            all(item.stream == "MYOTA_GEODATA_WORK" for item in consumers)
        )

    def test_geodata_work_scope_from_environment_is_narrow(self):
        geodata_capacity = {
            key: value
            for key, value in CAPACITY.items()
            if key.startswith("NATS_GEODATA_WORK_")
        }
        with patch.dict(
            os.environ,
            {
                **geodata_capacity,
                "NATS_TOPOLOGY_APPLY": "1",
                "NATS_TOPOLOGY_SCOPE": "geodata-work",
            },
            clear=True,
        ):
            streams, consumers = topology_from_environment()
        self.assertEqual(
            [stream.name for stream in streams], ["MYOTA_GEODATA_WORK"]
        )
        self.assertEqual(len(consumers), 4)

    def test_consumer_drift_checks_delivery_and_replay_safety_settings(self):
        with patch.dict(os.environ, CAPACITY, clear=True):
            _, consumers = desired_topology()
        consumer = consumers[0]
        desired = consumer_config(consumer)
        actual = SimpleNamespace(config=desired)
        validate_consumer(actual, desired, consumer.stream)

        server_normalized = consumer_config(consumer)
        server_normalized.mem_storage = None
        server_normalized.headers_only = None
        validate_consumer(
            SimpleNamespace(config=server_normalized),
            desired,
            consumer.stream,
        )

        drifted = consumer_config(consumer)
        drifted.max_waiting += 1
        with self.assertRaisesRegex(RuntimeError, "max_waiting"):
            validate_consumer(
                SimpleNamespace(config=drifted), desired, consumer.stream
            )

        drifted = consumer_config(consumer)
        drifted.headers_only = True
        with self.assertRaisesRegex(RuntimeError, "headers_only"):
            validate_consumer(
                SimpleNamespace(config=drifted), desired, consumer.stream
            )


if __name__ == "__main__":
    unittest.main()
