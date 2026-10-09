from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from jetstream_topology import desired_topology, topology_from_environment


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


if __name__ == "__main__":
    unittest.main()
