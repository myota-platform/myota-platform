from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from activity import ActivityHandler
from geodata import GeoHandler
from identity import IdentityHandler, seed as seed_identity
from import_adapters import normalize
from programmes import ProgrammeHandler, seed as seed_programmes


class VerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        for handler in (
            IdentityHandler,
            ProgrammeHandler,
            GeoHandler,
            ActivityHandler,
        ):
            handler.store.items.clear()
            handler.store.events.clear()
            handler.store.idempotency.clear()
        seed_identity()
        seed_programmes()
        GeoHandler.store.items.update(
            {
                "fixture-candidate": {
                    "id": "fixture-candidate",
                    "programmeSlug": "mpota",
                    "entityType": "MUNICIPAL_PARK",
                    "entityTypes": ["MUNICIPAL_PARK"],
                    "entityTypeCodes": ["MUNICIPAL_PARK"],
                    "name": "Candidate fixture",
                    "status": "CANDIDATE",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-5.99, 37.39],
                    },
                },
                "fixture-approved-mpota": {
                    "id": "fixture-approved-mpota",
                    "programmeSlug": "mpota",
                    "entityType": "MUNICIPAL_PARK",
                    "entityTypes": ["MUNICIPAL_PARK"],
                    "entityTypeCodes": ["MUNICIPAL_PARK"],
                    "name": "Approved fixture one",
                    "status": "APPROVED",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-5.98, 37.39],
                    },
                },
                "fixture-approved-regional": {
                    "id": "fixture-approved-regional",
                    "programmeSlug": "regional-ota",
                    "entityType": "NATURE_RESERVE",
                    "entityTypes": ["NATURE_RESERVE"],
                    "entityTypeCodes": ["NATURE_RESERVE"],
                    "name": "Approved fixture two",
                    "status": "APPROVED",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-5.97, 37.39],
                    },
                },
            }
        )

    def test_identity_supports_operator_multiple_callsigns_and_primary(
        self,
    ) -> None:
        result = IdentityHandler.create_account(
            None,
            {
                "_body": {"displayName": "SWL", "participationType": "SWL"},
                "Idempotency-Key": "account-1",
            },
        )
        self.assertEqual(result["participationType"], "SWL")
        account_id = result["id"]
        operator = IdentityHandler.create_account(
            None,
            {
                "_body": {
                    "displayName": "Operator",
                    "participationType": "OPERATOR",
                    "callsign": "N0TEST",
                },
                "Idempotency-Key": "account-2",
            },
        )
        added = IdentityHandler.add_callsign(
            None,
            {
                "accountId": operator["id"],
                "_body": {"callsign": "K1TEST"},
                "Idempotency-Key": "call-1",
            },
        )
        self.assertEqual(
            operator["primaryCallsignId"], operator["callsigns"][0]["id"]
        )
        self.assertEqual(len(added["account"]["callsigns"]), 2)
        self.assertNotEqual(account_id, operator["id"])

    def test_programmes_own_rules_and_theme(self) -> None:
        programmes = ProgrammeHandler.list_programmes(None, {})["items"]
        self.assertEqual(
            {p["slug"] for p in programmes}, {"mpota", "regional-ota"}
        )
        self.assertNotEqual(programmes[0]["theme"], programmes[1]["theme"])
        self.assertNotEqual(programmes[0]["rules"], programmes[1]["rules"])

    def test_candidate_review_lifecycle(self) -> None:
        candidates = GeoHandler.list_entities(
            None,
            {"_path": "/v1/geodata/entities?programme=mpota&status=CANDIDATE"},
        )["items"]
        self.assertEqual(len(candidates), 1)
        entity_id = candidates[0]["id"]
        candidate = GeoHandler.get_entity(None, {"entityId": entity_id})
        self.assertEqual(candidate["status"], "CANDIDATE")
        approved = GeoHandler.review(
            None,
            {
                "entityId": entity_id,
                "_body": {"decision": "APPROVED", "reviewerId": "approver-1"},
            },
        )
        self.assertEqual(approved["status"], "APPROVED")

    def test_community_proposal_is_a_candidate_source(self) -> None:
        proposal = GeoHandler.draw_proposal(
            None,
            {
                "_body": {
                    "programmeSlug": "mpota",
                    "proposerId": "operator-1",
                    "feature": {
                        "properties": {
                            "name": "Community trail",
                            "entityType": "TRAIL",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-5.99, 37.38], [-5.98, 37.39]],
                        },
                    },
                }
            },
        )
        entity = GeoHandler.get_entity(
            None, {"entityId": proposal["created"][0]}
        )
        self.assertEqual(entity["status"], "CANDIDATE")
        self.assertEqual(
            entity["candidateSource"]["type"], "COMMUNITY_PROPOSAL"
        )

    def test_geodata_review_filters_statuses_and_pages_deterministically(
        self,
    ) -> None:
        result = GeoHandler.list_entities(
            None,
            {
                "_path": "/v1/geodata/entities?status=CANDIDATE&status=APPROVED&page=1&pageSize=2"
            },
        )
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["pageSize"], 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(
            all(
                entity["status"] in {"CANDIDATE", "APPROVED"}
                for entity in result["items"]
            )
        )
        second_page = GeoHandler.list_entities(
            None,
            {
                "_path": "/v1/geodata/entities?status=CANDIDATE,APPROVED&page=2&pageSize=2"
            },
        )
        self.assertEqual(len(second_page["items"]), 1)

    def test_import_is_provenance_aware_and_idempotent(self) -> None:
        body = {
            "programmeSlug": "regional-ota",
            "adapter": "OSM",
            "entityType": "NATURE_RESERVE",
            "source": {"name": "OSM", "license": "ODbL 1.0"},
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": "A reserve",
                        "sourceRef": "osm/1",
                        "entityType": "NATURE_RESERVE",
                        "leisure": "nature_reserve",
                    },
                    "geometry": {"type": "Point", "coordinates": [2, 41]},
                }
            ],
        }
        p = {"_body": body, "Idempotency-Key": "import-1"}
        first = GeoHandler.import_manual(None, p)
        second = GeoHandler.import_manual(None, p)
        self.assertEqual(first, second)
        candidate_id = first["preprocessed"][0]
        GeoHandler.validate_import_candidates(
            None,
            {
                "runId": first["importRunId"],
                "_body": {
                    "candidateIds": [candidate_id],
                    "reviewerId": "admin",
                },
            },
        )
        queue = GeoHandler.process_import_candidates(
            None,
            {
                "runId": first["importRunId"],
                "_body": {
                    "candidateIds": [candidate_id],
                    "targetStatus": "CANDIDATE",
                    "processorId": "admin",
                },
            },
        )
        entity = GeoHandler.get_entity(
            None, {"entityId": queue["result"]["created"][0]}
        )
        self.assertEqual(entity["provenance"]["adapter"], "OSM")
        self.assertEqual(entity["status"], "CANDIDATE")

    def test_import_is_platform_wide_and_uses_shared_category(self) -> None:
        body = {
            "adapter": "MANUAL",
            "source": {"name": "shared-catalogue-test", "license": "CC0"},
            "entityType": "TRAIL",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Unassigned trail"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[2, 41], [2.01, 41.01]],
                    },
                }
            ],
        }
        result = GeoHandler.import_manual(
            None, {"_body": body, "Idempotency-Key": "import-unscoped-1"}
        )
        candidate_id = result["preprocessed"][0]
        GeoHandler.validate_import_candidates(
            None,
            {
                "runId": result["importRunId"],
                "_body": {
                    "candidateIds": [candidate_id],
                    "reviewerId": "admin",
                },
            },
        )
        queue = GeoHandler.process_import_candidates(
            None,
            {
                "runId": result["importRunId"],
                "_body": {
                    "candidateIds": [candidate_id],
                    "targetStatus": "CANDIDATE",
                    "processorId": "admin",
                },
            },
        )
        entity = GeoHandler.get_entity(
            None, {"entityId": queue["result"]["created"][0]}
        )
        self.assertIsNone(entity["programmeSlug"])
        self.assertEqual(entity["entityType"], "TRAIL")
        self.assertEqual(entity["status"], "CANDIDATE")

    def test_platform_wide_entity_category_and_name_are_editable_and_audited(
        self,
    ) -> None:
        result = GeoHandler.import_manual(
            None,
            {
                "_body": {
                    "adapter": "MANUAL",
                    "source": {"name": "review-edit-test", "license": "CC0"},
                    "entityType": "TRAIL",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "Old trail"},
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[2, 41], [2.01, 41.01]],
                            },
                        }
                    ],
                },
                "Idempotency-Key": "review-edit-1",
            },
        )
        candidate_id = result["preprocessed"][0]
        GeoHandler.validate_import_candidates(
            None,
            {
                "runId": result["importRunId"],
                "_body": {
                    "candidateIds": [candidate_id],
                    "reviewerId": "admin",
                },
            },
        )
        queue = GeoHandler.process_import_candidates(
            None,
            {
                "runId": result["importRunId"],
                "_body": {
                    "candidateIds": [candidate_id],
                    "targetStatus": "CANDIDATE",
                    "processorId": "admin",
                },
            },
        )
        entity_id = queue["result"]["created"][0]
        changed_category = GeoHandler.change_entity_type(
            None,
            {
                "entityId": entity_id,
                "_body": {
                    "entityType": "MUNICIPAL_PARK",
                    "editorId": "reviewer-1",
                    "note": "Shared catalogue correction",
                },
            },
        )
        changed_name = GeoHandler.change_entity_name(
            None,
            {
                "entityId": entity_id,
                "_body": {
                    "name": "Renamed trail",
                    "editorId": "reviewer-1",
                    "note": "Corrected source spelling",
                },
            },
        )
        self.assertIsNone(changed_category["programmeSlug"])
        self.assertEqual(changed_category["entityType"], "MUNICIPAL_PARK")
        self.assertEqual(changed_name["name"], "Renamed trail")
        self.assertEqual(
            [entry["action"] for entry in changed_name["reviewHistory"]][-2:],
            ["ENTITY_TYPE_CHANGED", "ENTITY_NAME_CHANGED"],
        )

    def test_manual_draw_proposal_can_be_platform_wide(self) -> None:
        result = GeoHandler.draw_proposal(
            None,
            {
                "_body": {
                    "source": {"name": "manual-map-test", "license": "CC0"},
                    "feature": {
                        "properties": {
                            "name": "Unassigned drawn trail",
                            "entityType": "TRAIL",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[2, 41], [2.01, 41.01]],
                        },
                    },
                }
            },
        )
        entity = GeoHandler.get_entity(
            None, {"entityId": result["created"][0]}
        )
        self.assertIsNone(entity["programmeSlug"])
        self.assertEqual(entity["status"], "CANDIDATE")

    def test_manual_draw_proposal_persists_multiple_categories_and_primary(
        self,
    ) -> None:
        result = GeoHandler.draw_proposal(
            None,
            {
                "_body": {
                    "source": {
                        "name": "multi-category-map-test",
                        "license": "CC0",
                    },
                    "feature": {
                        "properties": {
                            "name": "Park and trail",
                            "entityTypes": ["TRAIL", "NATURE_RESERVE"],
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[2, 41], [2.01, 41.01]],
                        },
                    },
                }
            },
        )
        entity = GeoHandler.get_entity(
            None, {"entityId": result["created"][0]}
        )
        self.assertEqual(entity["entityType"], "TRAIL")
        self.assertEqual(entity["entityTypes"], ["TRAIL", "NATURE_RESERVE"])
        changed = GeoHandler.change_entity_type(
            None,
            {
                "entityId": entity["id"],
                "_body": {
                    "entityTypes": ["NATURE_RESERVE", "TRAIL"],
                    "editorId": "reviewer-1",
                    "note": "Additional classification",
                },
            },
        )
        self.assertEqual(changed["entityType"], "NATURE_RESERVE")
        self.assertEqual(changed["entityTypes"], ["NATURE_RESERVE", "TRAIL"])
        filtered = GeoHandler.list_entities(
            None, {"_path": "/v1/geodata/entities?entityType=TRAIL"}
        )
        self.assertIn(entity["id"], {item["id"] for item in filtered["items"]})

    def test_supported_import_adapters_normalize_without_owning_policy(
        self,
    ) -> None:
        osm = normalize(
            "OSM",
            {
                "properties": {"osm_id": "way/7", "leisure": "park"},
                "geometry": {"type": "Point", "coordinates": [1, 2]},
            },
        )
        self.assertEqual(osm["properties"]["sourceRef"], "way/7")
        self.assertEqual(
            normalize("PARKSERVE_US", {"properties": {"sourceRef": "park/1"}})[
                "properties"
            ]["sourceRef"],
            "park/1",
        )

    def test_activation_and_qso_primitives(self) -> None:
        activation = ActivityHandler.create_activation(
            None,
            {
                "_body": {
                    "programmeSlug": "mpota",
                    "entityId": "entity-1",
                    "operatorId": "operator-1",
                    "startedAt": "2026-01-01T10:00:00Z",
                },
                "Idempotency-Key": "activation-1",
            },
        )
        qso = ActivityHandler.add_qso(
            None,
            {
                "activationId": activation["id"],
                "_body": {
                    "workedCallsign": "k1abc",
                    "timestamp": "2026-01-01T10:05:00Z",
                },
                "Idempotency-Key": "qso-1",
            },
        )
        self.assertEqual(qso["qsoCount"], 1)
        closed = ActivityHandler.close_activation(
            None, {"activationId": activation["id"], "_body": {}}
        )
        self.assertEqual(closed["status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
