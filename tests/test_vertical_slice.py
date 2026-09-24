from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from activity import ActivityHandler
from geodata import GeoHandler, seed as seed_geo
from geodata_importer import features_from_document
from identity import IdentityHandler, seed as seed_identity
from import_adapters import normalize
from programmes import ProgrammeHandler, seed as seed_programmes


class VerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        for handler in (IdentityHandler, ProgrammeHandler, GeoHandler, ActivityHandler):
            handler.store.items.clear()
            handler.store.events.clear()
            handler.store.data.clear()
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

    def test_seed_uses_three_sevilla_osm_parks(self) -> None:
        entities = GeoHandler.list_entities(None, {"_path": "/v1/geodata/entities?programme=mpota"})["items"]
        self.assertEqual({entity["name"] for entity in entities}, {
            "Parque de María Luisa", "Parque del Alamillo", "Parque de los Príncipes"})
        self.assertTrue(all(entity["provenance"]["adapter"] == "OSM" for entity in entities))
        self.assertTrue(all(entity["geometry"]["type"] == "Polygon" for entity in entities))

    def test_candidate_propose_review_lifecycle(self) -> None:
        candidates = GeoHandler.list_entities(None, {"_path": "/v1/geodata/entities?programme=mpota&status=CANDIDATE"})["items"]
        self.assertEqual(len(candidates), 1)
        entity_id = candidates[0]["id"]
        proposed = GeoHandler.propose(None, {"entityId": entity_id, "_body": {"proposerId": "operator-1"}})
        self.assertEqual(proposed["status"], "PROPOSED")
        approved = GeoHandler.review(None, {"entityId": entity_id, "_body": {"decision": "APPROVED", "reviewerId": "approver-1"}})
        self.assertEqual(approved["status"], "APPROVED")

    def test_approved_entity_can_only_be_retired(self) -> None:
        approved = GeoHandler.get_entity(None, {"entityId": "00000000-0000-4000-8000-000000000201"})
        with self.assertRaises(ValueError):
            GeoHandler.set_status(None, {"entityId": approved["id"], "_body": {
                "status": "REJECTED", "reviewerId": "approver-1", "note": "Must not invalidate QSOs"}})
        retired = GeoHandler.set_status(None, {"entityId": approved["id"], "_body": {
            "status": "RETIRED", "reviewerId": "approver-1", "note": "Reference superseded"}})
        self.assertEqual(retired["status"], "RETIRED")
        with self.assertRaises(ValueError):
            GeoHandler.set_status(None, {"entityId": approved["id"], "_body": {
                "status": "CANDIDATE", "reviewerId": "approver-1"}})

    def test_geodata_geometry_edit_keeps_history_and_source_snapshot(self) -> None:
        entity = GeoHandler.list_entities(None, {"_path": "/v1/geodata/entities?programme=mpota&status=CANDIDATE"})["items"][0]
        original = entity["geometry"]
        edited = GeoHandler.update_geometry(None, {"entityId": entity["id"], "_body": {
            "geometry": {"type": "Point", "coordinates": [-3.68, 40.43]}, "editorId": "approver-1", "note": "Corrected after source comparison"}})
        self.assertEqual(edited["geometry"]["coordinates"], [-3.68, 40.43])
        self.assertEqual(edited["geometryHistory"][0]["geometry"], original)
        audit = GeoHandler.audit_entity(None, {"entityId": entity["id"]})
        self.assertEqual(len(audit["geometryHistory"]), 1)
        self.assertTrue(any(event["eventType"] == "geodata.entity.geometry-updated.v1" for event in audit["events"]))

    def test_content_and_policy_versions_require_review_and_effective_publication(self) -> None:
        content = ProgrammeHandler.save_content(None, {"slug": "mpota", "_body": {
            "key": "programme.about", "locale": "en", "value": "Programme-owned copy"}})
        content = ProgrammeHandler.submit_content(None, {"slug": "mpota", "contentId": content["id"]})
        content = ProgrammeHandler.review_content(None, {"slug": "mpota", "contentId": content["id"], "_body": {
            "decision": "APPROVED", "reviewerId": "reviewer-1"}})
        content = ProgrammeHandler.publish_content(None, {"slug": "mpota", "contentId": content["id"], "_body": {
            "effectiveFrom": "2026-01-01T00:00:00Z", "publisherId": "publisher-1"}})
        self.assertEqual(content["status"], "PUBLISHED")
        coverage = ProgrammeHandler.content_coverage(None, {"slug": "mpota"})
        self.assertTrue(any(locale["locale"] == "en" for locale in coverage["locales"]))

        draft = ProgrammeHandler.save_policy_draft(None, {"slug": "mpota", "_body": {
            "type": "AWARD", "name": "Local programme award", "schema": {
                "code": "LOCAL-1", "requirements": {"minimumQsos": 25}}}})
        draft = ProgrammeHandler.submit_policy_draft(None, {"slug": "mpota", "draftId": draft["id"]})
        draft = ProgrammeHandler.review_policy_draft(None, {"slug": "mpota", "draftId": draft["id"], "_body": {
            "decision": "APPROVED", "reviewerId": "reviewer-1"}})
        published = ProgrammeHandler.publish_policy_draft(None, {"slug": "mpota", "draftId": draft["id"], "_body": {
            "effectiveFrom": "2026-02-01T00:00:00Z", "publisherId": "publisher-1"}})
        self.assertEqual(published["draft"]["status"], "PUBLISHED")
        self.assertEqual(published["programme"]["awards"][-1]["code"], "LOCAL-1")

    def test_import_is_provenance_aware_and_idempotent(self) -> None:
        body = {"programmeSlug": "regional-ota", "adapter": "OSM", "source": {"name": "OSM", "license": "ODbL 1.0"},
                "features": [{"type": "Feature", "properties": {"name": "A reserve", "sourceRef": "osm/1", "entityType": "NATURE_RESERVE", "leisure": "nature_reserve"}, "geometry": {"type": "Point", "coordinates": [2, 41]}}]}
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
        arcgis = normalize("GOVERNMENT_GIS", {"properties": {"objectId": 7, "sourceFormat": "ARCGIS_FEATURESERVER"}, "geometry": {"x": 1, "y": 2}})
        self.assertEqual(arcgis["geometry"], {"type": "Point", "coordinates": [1, 2]})
        web_mercator = normalize("GOVERNMENT_GIS", {"properties": {"sourceFormat": "WFS", "crs": "EPSG:3857"}, "geometry": {"type": "Point", "coordinates": [0, 0]}})
        self.assertEqual(web_mercator["geometry"]["coordinates"], [0.0, 0.0])

    def test_geodata_pipeline_manifest_filter_and_disappearance_policy(self) -> None:
        body = {"programmeSlug": "regional-ota", "adapter": "OSM", "source": {"name": "OSM Sevilla", "license": "ODbL 1.0"},
                "features": [
                    {"type": "Feature", "properties": {"name": "Included park", "sourceRef": "osm/included", "leisure": "park"},
                     "geometry": {"type": "Point", "coordinates": [-5.99, 37.39]}},
                    {"type": "Feature", "properties": {"name": "Filtered building", "sourceRef": "osm/filtered", "building": "yes"},
                     "geometry": {"type": "Point", "coordinates": [-5.99, 37.39]}}
                ]}
        imported = GeoHandler.import_manual(None, {"_body": body, "Idempotency-Key": "pipeline-import"})
        self.assertEqual(len(imported["created"]), 1)
        self.assertEqual(imported["skipped"][0]["reason"], "FILTERED_TAG")
        self.assertTrue(imported["manifest"]["sourceChanged"])
        schedule = GeoHandler.create_schedule(None, {"_body": {"programmeSlug": "regional-ota", "adapter": "OSM", "source": body["source"], "intervalSeconds": 3600}})
        refreshed = GeoHandler.refresh_import(None, {"scheduleId": schedule["id"], "_body": {"features": [], "completeSnapshot": True}})
        self.assertEqual(len(refreshed["disappeared"]), 1)
        entity = GeoHandler.get_entity(None, {"entityId": imported["created"][0]})
        self.assertEqual(entity["sourceState"], "REVIEW_REQUIRED")

    def test_geodata_conflation_is_reviewable_and_reversible(self) -> None:
        geometry = {"type": "Polygon", "coordinates": [[[-5.99, 37.39], [-5.98, 37.39], [-5.98, 37.40], [-5.99, 37.40], [-5.99, 37.39]]]}
        first = GeoHandler.import_manual(None, {"_body": {"programmeSlug": "regional-ota", "adapter": "GOVERNMENT_GIS",
            "source": {"name": "Seville GIS", "license": "CC-BY", "attribution": "Seville open data"},
            "features": [{"properties": {"name": "Alameda Park", "objectId": 1, "sourceFormat": "GEOJSON", "jurisdiction": "SEVILLA"}, "geometry": geometry}]}})
        second = GeoHandler.import_manual(None, {"_body": {"programmeSlug": "regional-ota", "adapter": "GOVERNMENT_GIS",
            "source": {"name": "Seville GIS", "license": "CC-BY", "attribution": "Seville open data"},
            "features": [{"properties": {"name": "Alameda Park", "objectId": 2, "sourceFormat": "GEOJSON", "jurisdiction": "SEVILLA"}, "geometry": geometry}]}})
        candidates = GeoHandler.list_conflation(None, {"_path": "/v1/geodata/conflation?programme=regional-ota"})["items"]
        self.assertTrue(candidates)
        resolved = GeoHandler.resolve_conflation(None, {"candidateId": candidates[0]["id"], "_body": {"decision": "KEPT_SEPARATE", "reviewerId": "reviewer-1"}})
        self.assertEqual(resolved["resolution"], "KEPT_SEPARATE")
        reopened = GeoHandler.resolve_conflation(None, {"candidateId": resolved["id"], "_body": {"decision": "OPEN", "reviewerId": "reviewer-1", "note": "Re-review after source update"}})
        self.assertEqual(reopened["resolution"], "OPEN")
        self.assertEqual(len(reopened["resolutionHistory"]), 2)

    def test_bbox_tile_and_manual_attachment_metadata(self) -> None:
        proposal = GeoHandler.draw_proposal(None, {"_body": {"programmeSlug": "regional-ota", "source": {"name": "Community proposal"},
            "feature": {"properties": {"name": "Community garden"}, "geometry": {"type": "Point", "coordinates": [-5.99, 37.39]},
                         "attachments": [{"name": "site-photo.jpg", "mediaType": "image/jpeg", "sizeBytes": 100, "uri": "https://example.test/photo.jpg"}]}}})
        entity = GeoHandler.get_entity(None, {"entityId": proposal["created"][0]})
        self.assertEqual(entity["attachments"][0]["name"], "site-photo.jpg")
        bbox = GeoHandler.bbox(None, {"_path": "/v1/geodata/bbox?minLon=-6.1&minLat=37.3&maxLon=-5.8&maxLat=37.5&programme=regional-ota"})
        self.assertGreaterEqual(bbox["count"], 1)
        tile = GeoHandler.tile(None, {"z": "12", "x": "2044", "y": "1600"})
        self.assertIn("features", tile)

    def test_importer_normalizes_arcgis_feature_server_documents(self) -> None:
        features = features_from_document({"features": [{"attributes": {"OBJECTID": 9, "name": "GIS park"},
            "geometry": {"rings": [[[-5.9, 37.3], [-5.8, 37.3], [-5.8, 37.4], [-5.9, 37.4], [-5.9, 37.3]]]}}]}, "ARCGIS_FEATURESERVER")
        self.assertEqual(features[0]["geometry"]["type"], "Polygon")
        self.assertEqual(features[0]["properties"]["OBJECTID"], 9)

    def test_activation_and_qso_primitives(self) -> None:
        activation = ActivityHandler.create_activation(None, {"_body": {"programmeSlug": "mpota", "entityId": "entity-1", "operatorId": "operator-1", "startedAt": "2026-01-01T10:00:00Z"}, "Idempotency-Key": "activation-1"})
        qso = ActivityHandler.add_qso(None, {"activationId": activation["id"], "_body": {"workedCallsign": "k1abc", "timestamp": "2026-01-01T10:05:00Z"}, "Idempotency-Key": "qso-1"})
        self.assertEqual(qso["qsoCount"], 1)
        closed = ActivityHandler.close_activation(None, {"activationId": activation["id"], "_body": {}})
        self.assertEqual(closed["status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
