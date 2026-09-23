from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from activity import ActivityHandler
from geodata import GeoHandler, seed as seed_geo
from identity import IdentityHandler, seed as seed_identity
from import_adapters import normalize
from programmes import ProgrammeHandler, seed as seed_programmes


class VerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        for handler in (IdentityHandler, ProgrammeHandler, GeoHandler, ActivityHandler):
            handler.store.items.clear()
            handler.store.events.clear()
            handler.store.idempotency.clear()
        seed_identity(); seed_programmes(); seed_geo()

    def test_identity_supports_operator_multiple_callsigns_and_primary(self) -> None:
        result = IdentityHandler.create_account(None, {"_body": {"displayName": "SWL", "participationType": "SWL"}, "Idempotency-Key": "account-1"})
        self.assertEqual(result["participationType"], "SWL")
        account_id = result["id"]
        operator = IdentityHandler.create_account(None, {"_body": {"displayName": "Operator", "participationType": "OPERATOR", "callsign": "N0TEST"}, "Idempotency-Key": "account-2"})
        added = IdentityHandler.add_callsign(None, {"accountId": operator["id"], "_body": {"callsign": "K1TEST"}, "Idempotency-Key": "call-1"})
        self.assertEqual(operator["primaryCallsignId"], operator["callsigns"][0]["id"])
        self.assertEqual(len(added["account"]["callsigns"]), 2)
        self.assertNotEqual(account_id, operator["id"])

    def test_programmes_own_rules_and_theme(self) -> None:
        programmes = ProgrammeHandler.list_programmes(None, {})["items"]
        self.assertEqual({p["slug"] for p in programmes}, {"mpota", "regional-ota"})
        self.assertNotEqual(programmes[0]["theme"], programmes[1]["theme"])
        self.assertNotEqual(programmes[0]["rules"], programmes[1]["rules"])

    def test_candidate_propose_review_lifecycle(self) -> None:
        candidates = GeoHandler.list_entities(None, {"_path": "/v1/geodata/entities?programme=mpota&status=CANDIDATE"})["items"]
        self.assertEqual(len(candidates), 1)
        entity_id = candidates[0]["id"]
        proposed = GeoHandler.propose(None, {"entityId": entity_id, "_body": {"proposerId": "operator-1"}})
        self.assertEqual(proposed["status"], "PROPOSED")
        approved = GeoHandler.review(None, {"entityId": entity_id, "_body": {"decision": "APPROVED", "reviewerId": "approver-1"}})
        self.assertEqual(approved["status"], "APPROVED")

    def test_import_is_provenance_aware_and_idempotent(self) -> None:
        body = {"programmeSlug": "regional-ota", "adapter": "OSM", "source": {"name": "OSM", "license": "ODbL 1.0"},
                "features": [{"type": "Feature", "properties": {"name": "A reserve", "sourceRef": "osm/1", "entityType": "NATURE_RESERVE"}, "geometry": {"type": "Point", "coordinates": [2, 41]}}]}
        p = {"_body": body, "Idempotency-Key": "import-1"}
        first = GeoHandler.import_manual(None, p)
        second = GeoHandler.import_manual(None, p)
        self.assertEqual(first, second)
        entity = GeoHandler.get_entity(None, {"entityId": first["created"][0]})
        self.assertEqual(entity["provenance"]["adapter"], "OSM")
        self.assertEqual(entity["status"], "CANDIDATE")

    def test_supported_import_adapters_normalize_without_owning_policy(self) -> None:
        osm = normalize("OSM", {"properties": {"osm_id": "way/7", "leisure": "park"}, "geometry": {"type": "Point", "coordinates": [1, 2]}})
        self.assertEqual(osm["properties"]["sourceRef"], "way/7")
        self.assertEqual(normalize("PARKSERVE_US", {"properties": {"sourceRef": "park/1"}})["properties"]["sourceRef"], "park/1")

    def test_activation_and_qso_primitives(self) -> None:
        activation = ActivityHandler.create_activation(None, {"_body": {"programmeSlug": "mpota", "entityId": "entity-1", "operatorId": "operator-1", "startedAt": "2026-01-01T10:00:00Z"}, "Idempotency-Key": "activation-1"})
        qso = ActivityHandler.add_qso(None, {"activationId": activation["id"], "_body": {"workedCallsign": "k1abc", "timestamp": "2026-01-01T10:05:00Z"}, "Idempotency-Key": "qso-1"})
        self.assertEqual(qso["qsoCount"], 1)
        closed = ActivityHandler.close_activation(None, {"activationId": activation["id"], "_body": {}})
        self.assertEqual(closed["status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
