import unittest

from dev_server import route_template


class GatewayRouteTemplateTests(unittest.TestCase):
    def test_entity_identifiers_are_replaced_by_route_parameters(self):
        route = route_template(
            "GET",
            "/v1/geodata/entities/17a2c7bd-6016-45a1-9483-3a260e03f84a",
        )

        self.assertEqual(route, "/v1/geodata/entities/{entityId}")

    def test_nested_import_routes_keep_the_full_template(self):
        route = route_template(
            "POST",
            "/v1/geodata/imports/17a2c7bd-6016-45a1-9483-3a260e03f84a/candidates/validate",
        )

        self.assertEqual(
            route,
            "/v1/geodata/imports/{runId}/candidates/validate",
        )

    def test_query_strings_do_not_affect_route_labels(self):
        route = route_template(
            "GET", "/v1/geodata/entities?page=4&pageSize=25"
        )

        self.assertEqual(route, "/v1/geodata/entities")

    def test_unknown_paths_do_not_emit_raw_identifiers(self):
        route = route_template(
            "GET",
            "/v1/geodata/unknown/17a2c7bd-6016-45a1-9483-3a260e03f84a",
        )

        self.assertEqual(route, "/v1/geodata/{unmatched}")


if __name__ == "__main__":
    unittest.main()
