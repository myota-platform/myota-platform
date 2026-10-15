import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class ObservabilityConfigurationTests(unittest.TestCase):
    def test_all_provisioned_dashboards_have_requested_defaults_and_match_helm(
        self,
    ):
        for source in (ROOT / "observability/grafana/dashboards").glob(
            "myota-*.json"
        ):
            dashboard = json.loads(source.read_text())
            mirror = (
                ROOT
                / "deploy/helm/myota/observability/grafana/dashboards"
                / source.name
            )
            self.assertEqual(dashboard, json.loads(mirror.read_text()))
            self.assertEqual(
                dashboard["time"], {"from": "now-30m", "to": "now"}
            )
            self.assertEqual(dashboard["refresh"], "30s")
            self.assertEqual(dashboard["timezone"], "utc")
            if source.name == "myota-logs-failures.json":
                self.assertFalse(dashboard["editable"])
            else:
                self.assertTrue(dashboard["editable"])

    def test_prometheus_uses_collector_boundary(self):
        config = (ROOT / "observability" / "prometheus.yml").read_text()
        self.assertIn("otel-collector:8889", config)
        self.assertNotIn("identity:8001", config)
        self.assertNotIn("geodata:8003", config)

    def test_collector_has_otlp_and_prometheus_pipelines(self):
        config = (ROOT / "observability" / "otel-collector.yaml").read_text()
        self.assertIn("otlp:", config)
        self.assertIn("prometheus:", config)
        self.assertIn("otlp/tempo", config)
        self.assertIn("endpoint: 0.0.0.0:8889", config)

    def test_dashboard_is_real_data_only(self):
        dashboard = json.loads(
            (
                ROOT
                / "observability"
                / "grafana"
                / "dashboards"
                / "myota-service-health.json"
            ).read_text()
        )
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertTrue(
            any(
                "myota_identity_users_total" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_geodata_entities_total" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_activity_qsos_total" in expression
                for expression in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_http_server_requests_total" in expression
                for expression in expressions
            )
        )
        self.assertFalse(
            any(
                "vector(1)" in expression or "count(up)" in expression
                for expression in expressions
            )
        )

    def test_seaweed_dashboard_is_valid_and_rolls_out_with_helm(self):
        dashboard_path = (
            ROOT
            / "observability"
            / "grafana"
            / "dashboards"
            / "myota-object-storage.json"
        )
        chart_dashboard_path = (
            ROOT
            / "deploy"
            / "helm"
            / "myota"
            / "observability"
            / "grafana"
            / "dashboards"
            / "myota-object-storage.json"
        )
        dashboard = json.loads(dashboard_path.read_text())
        chart_dashboard = json.loads(chart_dashboard_path.read_text())
        deployment_template = (
            ROOT
            / "deploy"
            / "helm"
            / "myota"
            / "templates"
            / "observability.yaml"
        ).read_text()

        self.assertEqual(dashboard, chart_dashboard)
        self.assertEqual("myota-object-storage", dashboard["uid"])
        self.assertGreater(len(dashboard["panels"]), 0)
        self.assertIn("checksum/grafana-config:", deployment_template)
        self.assertIn(
            '.Files.Glob "observability/grafana/**"', deployment_template
        )

    def test_loki_uses_s3_retention_and_native_otlp_pipeline(self):
        compose_config = (ROOT / "observability" / "loki.yaml").read_text()
        helm_config = (
            ROOT / "deploy/helm/myota/observability/loki.yaml"
        ).read_text()
        compose_collector = (
            ROOT / "observability" / "otel-collector.yaml"
        ).read_text()
        helm_collector = (
            ROOT / "deploy/helm/myota/observability/otel-collector.yaml"
        ).read_text()
        helm_template = (
            ROOT / "deploy/helm/myota/templates/observability.yaml"
        ).read_text()
        compose = (ROOT / "compose.yaml").read_text()

        for config in (compose_config, helm_config):
            self.assertIn("store: tsdb", config)
            self.assertIn("object_store: s3", config)
            self.assertIn("retention_enabled: true", config)
            self.assertIn("delete_request_store: s3", config)
            self.assertIn("ignore_defaults: true", config)
            self.assertIn("service.namespace", config)
        self.assertIn("bucketnames: myota-loki", compose_config)
        self.assertIn(".Values.observability.loki.bucketName", helm_config)
        self.assertIn("retention_period: 336h", compose_config)
        self.assertIn(
            ".Values.observability.loki.retentionPeriod", helm_config
        )
        self.assertIn("endpoint: http://loki:3100/otlp", compose_collector)
        self.assertIn("endpoint: http://myota-loki:3100/otlp", helm_collector)
        self.assertIn("exporters: [otlphttp/loki]", helm_collector)
        self.assertIn("loki-data", helm_template)
        self.assertIn("workingStorageSize", helm_template)
        self.assertIn("loki-bucket-init", compose)
        self.assertIn("  loki:", compose)
        self.assertIn("loki-data:", compose)

    def test_k3s_dashboard_and_scrapes_are_internal_and_least_privilege(self):
        dashboard = json.loads(
            (
                ROOT
                / "deploy/helm/myota/observability/grafana/dashboards"
                / "myota-k3s-workload.json"
            ).read_text()
        )
        helm_template = (
            ROOT / "deploy/helm/myota/templates/observability.yaml"
        ).read_text()
        prom_config = (
            ROOT / "deploy/helm/myota/observability/prometheus.yml"
        ).read_text()
        dashboard_provider = (
            ROOT
            / "deploy/helm/myota/observability/grafana/provisioning"
            / "dashboards/dashboards.yml"
        ).read_text()

        self.assertEqual(dashboard["time"], {"from": "now-30m", "to": "now"})
        self.assertEqual(dashboard["refresh"], "30s")
        self.assertEqual(dashboard["timezone"], "utc")
        self.assertIn(
            "kube_deployment_status_replicas_available", json.dumps(dashboard)
        )
        self.assertIn(
            "kube_pod_container_status_restarts_total", json.dumps(dashboard)
        )
        self.assertIn("pod_cpu_usage_seconds_total", json.dumps(dashboard))
        self.assertIn(
            "kubelet_volume_stats_available_bytes", json.dumps(dashboard)
        )
        self.assertIn("kube-state-metrics", prom_config)
        self.assertIn("scrape_interval: 30s", prom_config)
        self.assertNotIn("source_labels: [__name__]", prom_config)
        self.assertIn("serviceAccountName: myota-prometheus", helm_template)
        self.assertNotIn("kind: ClusterRole", helm_template)
        self.assertNotIn("nodes/proxy", helm_template)
        self.assertNotIn("insecure_skip_verify", prom_config)
        self.assertIn(
            'regex: "(pod_cpu_usage_seconds_total|pod_memory_working_set_bytes);myota"',
            prom_config,
        )
        self.assertIn(
            'regex: "(kubelet_volume_stats_available_bytes|kubelet_volume_stats_capacity_bytes);myota"',
            prom_config,
        )
        self.assertIn("folder: K3s", dashboard_provider)
        self.assertIn("myota-k3s-workload.json", helm_template)

    def test_workflow_dashboard_is_chart_provisioned_and_root_mirror_matches(
        self,
    ):
        dashboard = json.loads(
            (
                ROOT
                / "observability/grafana/dashboards"
                / "myota-application-workflows.json"
            ).read_text()
        )
        chart_dashboard = json.loads(
            (
                ROOT
                / "deploy/helm/myota/observability/grafana/dashboards"
                / "myota-application-workflows.json"
            ).read_text()
        )
        self.assertEqual(dashboard, chart_dashboard)
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertTrue(
            any("myota_outbox_pending_events" in e for e in expressions)
        )
        self.assertTrue(
            any("myota_activity_jobs_total" in e for e in expressions)
        )
        self.assertTrue(
            any("myota_geodata_import_queue_depth" in e for e in expressions)
        )
        self.assertTrue(
            any(
                "nats_core_account_jetstream_consumer_count" in e
                for e in expressions
            )
        )
        self.assertFalse(
            any("myota_jetstream_consumer_pending" in e for e in expressions)
        )

    def test_postgresql_dashboard_uses_current_bounded_metrics(self):
        dashboard = json.loads(
            (
                ROOT
                / "observability/grafana/dashboards"
                / "myota-postgresql-postgis.json"
            ).read_text()
        )
        self.assertEqual(dashboard["time"], {"from": "now-30m", "to": "now"})
        expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]
        self.assertTrue(any("postgresql_backends" in e for e in expressions))
        self.assertTrue(
            any("postgresql_connection_max" in e for e in expressions)
        )
        self.assertTrue(
            any(
                "myota_geodata_postgres_pool_waiting_requests" in e
                for e in expressions
            )
        )
        self.assertTrue(
            any(
                "myota_geodata_postgres_lock_waiting_connections" in e
                for e in expressions
            )
        )
        self.assertFalse(any("myota_postgresql_" in e for e in expressions))
        config = (ROOT / "observability" / "otel-collector.yaml").read_text()
        for database in ("core", "activity", "geo"):
            self.assertIn(f"postgresql/{database}:", config)
        receivers = config.split("  prometheus:", 1)[0]
        self.assertEqual(receivers.count("tls: {insecure: true}"), 3)
        self.assertIn("collection_interval: 30s", config)
        self.assertIn("db.server.query_sample: {enabled: false}", config)
        self.assertIn("db.server.top_query: {enabled: false}", config)
        self.assertNotIn("operations:8005", config)

    def test_operations_runtime_and_schema_are_retired(self):
        compose = (ROOT / "compose.yaml").read_text()
        chart_values = (ROOT / "deploy/helm/myota/values.yaml").read_text()
        chart_deployment = (
            ROOT / "deploy/helm/myota/templates/deployment.yaml"
        ).read_text()
        collector = (ROOT / "observability/otel-collector.yaml").read_text()
        self.assertNotIn("myota-operations", compose)
        self.assertNotIn("myota-operations", chart_values)
        self.assertNotIn("myota-operations", chart_deployment)
        self.assertNotIn("operations:8005", collector)
        core_migrations = ROOT / "db/migrations/core"
        self.assertEqual(
            sorted(path.name for path in core_migrations.glob("*.sql")),
            [
                "001_core_baseline.sql",
                "002_identity_auth_support.sql",
                "003_identity_auth_backfill.sql",
            ],
        )
        baseline = (core_migrations / "001_core_baseline.sql").read_text()
        self.assertNotIn("operations_jetstream_snapshot", baseline)
        self.assertNotIn("operations_storage_snapshot", baseline)
        self.assertNotIn("operations_status_sample", baseline)


if __name__ == "__main__":
    unittest.main()
