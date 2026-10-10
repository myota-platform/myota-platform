from __future__ import annotations

import json
import ast
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_deploy_event_registry import runtime_catalog  # noqa: E402

OWNER_REPOSITORIES = {
    "identity-service": "myota-identity-service",
    "programme-service": "myota-programme-service",
    "activity-service": "myota-activity-service",
    "geodata-service": "myota-geodata-service",
    "operations-service": "myota-operations-service",
}


class EventRegistryTests(unittest.TestCase):
    def test_deploy_routing_catalog_is_generated_from_contract_registry(self):
        registry = json.loads(
            (ROOT / "contracts/event-registry.json").read_text(
                encoding="utf-8"
            )
        )
        catalog = runtime_catalog(registry)
        expected_routes = {
            "geodata.import.queued.v1": "myota.geodata.import.preprocess.v1",
            "geodata.import.recovered.v1": "myota.geodata.import.preprocess.v1",
            "geodata.import.processing.queued.v1": "myota.geodata.import.process.v1",
            "geodata.import.processing.recovered.v1": "myota.geodata.import.process.v1",
            "geodata.entity-deletion-job.queued.v1": "myota.geodata.entity.delete.v1",
            "geodata.entity.location-enrichment-requested.v1": (
                "myota.geodata.entity.location-enrichment.v1"
            ),
        }
        self.assertEqual(
            {
                event_type: route["subject"]
                for event_type, route in catalog["legacyWorkRoutes"].items()
            },
            expected_routes,
        )
        for repo in ("myota-deploy", "myota-platform"):
            source_root = ROOT.parent / repo
            if not source_root.is_dir():
                continue
            checked_in = json.loads(
                (source_root / "services/event_registry.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(checked_in, catalog)
        for event in registry["events"]:
            self.assertIn(event["owner"], registry["producerNamesByOwner"])
            self.assertTrue(registry["producerNamesByOwner"][event["owner"]])

    def test_registry_entries_have_unique_subjects_and_checked_in_schemas(
        self,
    ):
        registry = json.loads(
            (ROOT / "contracts/event-registry.json").read_text(
                encoding="utf-8"
            )
        )
        subjects = [
            item["subject"] for item in registry["events"] + registry["work"]
        ]
        self.assertEqual(len(subjects), len(set(subjects)))
        self.assertEqual(len(registry["events"]), 68)
        identity_events = [
            event
            for event in registry["events"]
            if event["owner"] == "identity-service"
        ]
        programme_events = [
            event
            for event in registry["events"]
            if event["owner"] == "programme-service"
        ]
        self.assertEqual(len(identity_events), 19)
        self.assertEqual(len(programme_events), 12)
        activity_events = [
            event
            for event in registry["events"]
            if event["owner"] == "activity-service"
        ]
        self.assertEqual(len(activity_events), 10)
        geodata_events = [
            event
            for event in registry["events"]
            if event["owner"] == "geodata-service"
        ]
        self.assertEqual(len(geodata_events), 27)
        geodata_by_type = {
            event["eventType"]: event for event in geodata_events
        }
        activity_by_type = {
            event["eventType"]: event for event in activity_events
        }
        self.assertEqual(
            set(activity_by_type),
            {
                "activity.activation.closed.v1",
                "activity.activation.created.v1",
                "activity.adif.queued.v1",
                "activity.entity.cascade-deleted.v1",
                "activity.qso.recorded.v1",
                "awards.definition.published.v1",
                "awards.definition.saved.v1",
                "awards.issued.v1",
                "awards.rendered.v1",
                "awards.request.created.v1",
            },
        )
        self.assertEqual(len(registry["work"]), 10)
        self.assertEqual(
            {
                event_type
                for work in registry["work"]
                for event_type in work.get("sourceEventTypes", [])
            },
            {
                "geodata.import.queued.v1",
                "geodata.import.recovered.v1",
                "geodata.import.processing.queued.v1",
                "geodata.import.processing.recovered.v1",
                "geodata.entity-deletion-job.queued.v1",
                "geodata.entity.location-enrichment-requested.v1",
            },
        )
        for event in registry["events"]:
            self.assertEqual(event["class"], "domain-fact")
            self.assertEqual(
                event["subject"], f"myota.events.{event['eventType']}"
            )
            self.assertIn("consumerGroups", event)
            self.assertIsInstance(event["consumerGroups"], list)
            self.assertIn("disposition", event)
            self.assertTrue(event["disposition"].strip())
            sources = event["producerSources"]
            self.assertTrue(sources)
            self.assertEqual(sources, sorted(set(sources)))
            for source in sources:
                repository, relative_path = source.split("/", 1)
                self.assertEqual(
                    repository, OWNER_REPOSITORIES[event["owner"]]
                )
                self.assertTrue(relative_path.endswith(".py"))
            schema_path = ROOT / "contracts" / event["schema"]
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(
                schema["allOf"][1]["properties"]["eventType"]["const"],
                event["eventType"],
            )
            if event["owner"] in {
                "identity-service",
                "programme-service",
                "activity-service",
                "geodata-service",
            }:
                owner_slug = event["owner"].replace("-service", "")
                self.assertEqual(
                    event["payloadEvidence"],
                    f"source-derived-{owner_slug}-callsite",
                )
                self.assertEqual(
                    schema["x-payload-evidence"], event["payloadEvidence"]
                )
                self.assertEqual(
                    schema["x-data-classification"],
                    event["dataClassification"],
                )
                self.assertIn(
                    event["dataClassification"],
                    {
                        "personal",
                        "personal-and-security",
                        "internal-configuration",
                        "internal-configuration-and-user-metadata",
                        "internal-authorization",
                        "security-sensitive",
                        "personal-and-operational-data",
                        "internal-configuration-and-personal",
                        "personal-and-certificate-metadata",
                        "geospatial-and-review-metadata",
                        "geospatial-and-operational-data",
                        "geospatial-and-source-data",
                        "internal-operational-metadata",
                        "internal-configuration-and-source-metadata",
                    },
                )
                payload = schema["allOf"][1]["properties"]["payload"]
                self.assertEqual(payload["type"], "object")
                self.assertTrue(payload["additionalProperties"])
                self.assertTrue(payload["required"])
                if event["eventType"] == "identity.service-token.issued.v1":
                    self.assertEqual(
                        set(payload["properties"]), {"service", "scopes"}
                    )
                    self.assertNotIn("accessToken", payload["properties"])
                if event["eventType"] == "identity.login.failed.v1":
                    self.assertEqual(
                        event["dataClassification"],
                        "personal-and-security",
                    )
                    self.assertEqual(
                        set(payload["properties"]), {"email", "remoteAddr"}
                    )
            else:
                self.assertEqual(
                    event["payloadEvidence"], "pending-source-payload-review"
                )
        for event_type, required_properties in {
            "activity.adif.queued.v1": {"objectKey", "bucket", "sha256"},
            "activity.activation.created.v1": {"programmeSlug", "operatorId"},
            "activity.qso.recorded.v1": {
                "workedCallsign",
                "deduplicationKey",
            },
            "awards.issued.v1": {"personName", "managerName", "artifact"},
            "awards.request.created.v1": {"personName", "facts"},
        }.items():
            event = activity_by_type[event_type]
            payload = json.loads(
                (ROOT / "contracts" / event["schema"]).read_text(
                    encoding="utf-8"
                )
            )["allOf"][1]["properties"]["payload"]
            self.assertTrue(
                required_properties.issubset(payload["properties"])
            )
        for event_type, required_properties in {
            "geodata.entity.location-enriched.v1": {
                "entityId",
                "requestId",
                "geometryHash",
                "status",
                "reason",
            },
            "geodata.import.preprocessed.v1": {
                "importRunId",
                "adapter",
                "preprocessed",
                "errors",
                "manifest",
            },
            "geodata.entity.entity-type-changed.v1": {
                "entityId",
                "editorId",
                "previousEntityTypes",
                "entityTypes",
            },
            "geodata.entity.status-changed.v1": {
                "entityId",
                "status",
                "previousStatus",
                "reviewerId",
            },
            "geodata.entity-deletion-job.created.v1": {
                "id",
                "entityId",
                "status",
                "requestedBy",
                "impact",
            },
        }.items():
            event = geodata_by_type[event_type]
            payload = json.loads(
                (ROOT / "contracts" / event["schema"]).read_text(
                    encoding="utf-8"
                )
            )["allOf"][1]["properties"]["payload"]
            self.assertTrue(
                required_properties.issubset(payload["properties"])
            )
        for work in registry["work"]:
            self.assertEqual(work["class"], "work-command")
            owner_namespace = (
                "activity"
                if work["owner"] == "activity-service"
                else "geodata"
            )
            stream = (
                registry["activityWorkStream"]
                if owner_namespace == "activity"
                else registry["geodataWorkStream"]
            )
            self.assertEqual(work["stream"], stream)
            self.assertEqual(work["subject"], f"myota.work.{work['workType']}")
            self.assertEqual(
                work["subject"].split(".", 3)[:3],
                ["myota", "work", owner_namespace],
            )
            self.assertTrue(
                work["subject"].startswith(f"myota.work.{owner_namespace}.")
            )
            self.assertRegex(
                work["workType"], r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+\.v1$"
            )
            self.assertTrue(re.fullmatch(r"[a-z0-9-]+-v1", work["durable"]))
            self.assertEqual(
                work["schema"],
                f"schemas/work/{work['workType'].replace('.', '-')}.schema.json",
            )
            schema_path = ROOT / "contracts" / work["schema"]
            self.assertTrue(schema_path.is_file())
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            payload = schema["allOf"][1]["properties"]["payload"]
            self.assertEqual(payload, work["payloadSchema"])
            self.assertEqual(payload["type"], "object")
            self.assertFalse(payload["additionalProperties"])
            self.assertTrue(payload["required"])
            self.assertEqual(schema["x-work-id-source"], work["workIdSource"])
            for key in ("producerSources", "consumerSources"):
                self.assertTrue(work[key])
                for source in work[key]:
                    repository, relative_path = source.split("/", 1)
                    self.assertEqual(
                        repository, OWNER_REPOSITORIES[work["owner"]]
                    )
                    source_root = ROOT.parent / repository
                    if source_root.is_dir():
                        self.assertTrue((source_root / relative_path).is_file())
            if work["owner"] == "activity-service":
                self.assertEqual(set(payload["properties"]), {"jobId"})
                self.assertLessEqual(
                    payload["properties"]["jobId"]["maxLength"], 36
                )
            elif work["workType"] == "geodata.location-enrichment.v1":
                self.assertEqual(
                    set(payload["properties"]),
                    {
                        "entityId",
                        "requestId",
                        "geometryHash",
                        "onlyMissing",
                        "reason",
                    },
                )
                self.assertLessEqual(
                    payload["properties"]["reason"]["maxLength"], 80
                )

    def test_registered_work_durables_match_deploy_owned_topology(self):
        """Keep the contracts registry and provisioned command filters aligned."""
        deploy_root = ROOT.parent / "myota-deploy"
        topology_source = deploy_root / "services/jetstream_topology.py"
        if not topology_source.is_file():
            self.skipTest(
                "deploy repository is not checked out beside contracts"
            )
        source = topology_source.read_text(encoding="utf-8")
        registered = json.loads(
            (ROOT / "contracts/event-registry.json").read_text(
                encoding="utf-8"
            )
        )
        for work in registered["work"]:
            self.assertIn(f'"{work["durable"]}"', source)
            self.assertIn(f'"{work["subject"]}"', source)

    def test_runtime_catalog_contains_registered_target_work_routes(self):
        registry = json.loads(
            (ROOT / "contracts/event-registry.json").read_text(
                encoding="utf-8"
            )
        )
        routes = runtime_catalog(registry)["targetWorkRoutes"]
        self.assertEqual(
            set(routes), {item["workType"] for item in registry["work"]}
        )
        for work in registry["work"]:
            self.assertEqual(
                routes[work["workType"]]["subject"], work["subject"]
            )
            self.assertEqual(
                routes[work["workType"]]["stream"], work["stream"]
            )
            self.assertEqual(
                routes[work["workType"]]["durable"], work["durable"]
            )

    def test_activity_notification_filters_match_registry_and_provisioner(
        self,
    ):
        registry = json.loads(
            (ROOT / "contracts/event-registry.json").read_text(
                encoding="utf-8"
            )
        )
        expected = sorted(
            event["subject"]
            for event in registry["events"]
            if "activity-notifications-v1" in event["consumerGroups"]
        )
        activity_root = ROOT.parent / "myota-activity-service"
        deploy_root = ROOT.parent / "myota-deploy"
        if (
            not (activity_root / "event_consumer.py").is_file()
            or not (deploy_root / "services/outbox_worker.py").is_file()
        ):
            self.skipTest(
                "Activity and deploy repositories are not checked out"
            )

        def assigned_filters(path, variable):
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(module):
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == variable
                    for target in node.targets
                ):
                    return sorted(ast.literal_eval(node.value))
            self.fail(f"{variable} not found in {path}")

        activity_filters = assigned_filters(
            activity_root / "event_consumer.py",
            "ACTIVITY_NOTIFICATION_SUBJECTS",
        )
        self.assertEqual(activity_filters, expected)

        deploy_source = ast.parse(
            (deploy_root / "services/outbox_worker.py").read_text(
                encoding="utf-8"
            )
        )
        deploy_filters = None
        for node in ast.walk(deploy_source):
            if not isinstance(node, ast.Call):
                continue
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id != "ConsumerConfig"
            ):
                continue
            values = {keyword.arg: keyword.value for keyword in node.keywords}
            durable = values.get("durable_name")
            filters = values.get("filter_subjects")
            if (
                isinstance(durable, ast.Constant)
                and durable.value == "activity-notifications-v1"
                and filters is not None
            ):
                deploy_filters = sorted(ast.literal_eval(filters))
                break
        self.assertEqual(deploy_filters, expected)

    def test_outer_event_envelope_rejects_relay_mutable_fields(self):
        schema = json.loads(
            (ROOT / "contracts/schemas/event-envelope.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["properties"]["envelopeVersion"]["const"], 1)
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("attempts", schema["properties"])
        self.assertIn("causationId", schema["properties"])
        self.assertEqual(schema["properties"]["eventId"]["format"], "uuid")
        self.assertEqual(schema["properties"]["occurredAt"]["pattern"], "Z$")
        work_schema = json.loads(
            (ROOT / "contracts/schemas/work-command.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(work_schema["properties"]["workId"]["format"], "uuid")
        self.assertEqual(
            work_schema["properties"]["createdAt"]["pattern"], "Z$"
        )

    def test_work_payloads_are_bounded_database_references(self):
        registry = json.loads(
            (ROOT / "contracts/event-registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(registry["work"]), 10)
        for work in registry["work"]:
            payload = work["payloadSchema"]
            self.assertFalse(payload["additionalProperties"])
            self.assertTrue(payload["required"])
            self.assertTrue(
                work["workIdSource"].endswith(".id")
                or "RequestId" in work["workIdSource"]
                or "[jobId]" in work["workIdSource"]
            )
            self.assertTrue(work["producerSources"])
            self.assertTrue(work["consumerSources"])
            serialized = json.dumps(payload).lower()
            for forbidden in (
                "sourceDocument",
                "featureCollection",
                "qsoBatch",
                "certificateBytes",
            ):
                self.assertNotIn(forbidden.lower(), serialized)
            for name, definition in payload["properties"].items():
                if definition.get("type") == "string":
                    self.assertLessEqual(
                        definition.get("maxLength", 0), 80, name
                    )


if __name__ == "__main__":
    unittest.main()
