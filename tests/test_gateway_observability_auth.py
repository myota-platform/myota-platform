import json
import unittest
from unittest.mock import patch

from services.dev_server import grafana_auth_response


class GrafanaGatewayAuthTests(unittest.TestCase):
    def test_requires_bearer_without_calling_identity(self):
        with patch("services.dev_server.urllib.request.urlopen") as urlopen:
            status, body, headers = grafana_auth_response("")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"], "authentication_required")
        self.assertEqual(headers["Cache-Control"], "no-store")
        urlopen.assert_not_called()

    def test_global_role_maps_to_editor_from_live_identity_response(self):
        account = {
            "id": "account-1",
            "displayName": "Operator",
            "email": "operator@example.test",
            "roles": [{"role": "GLOBAL_OPERATOR"}],
            "scopes": [],
        }
        with patch("services.dev_server.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = (
                json.dumps(account).encode()
            )
            status, body, headers = grafana_auth_response("Bearer live-token")
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-MyOTA-Grafana-User"], "myota:account-1")
        self.assertEqual(headers["X-MyOTA-Grafana-Role"], "Editor")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body, b"{}")

    def test_observability_scope_maps_to_viewer_and_retired_scope_is_denied(
        self,
    ):
        for scopes, expected in (
            (["observability.view"], (200, "Viewer")),
            (["operations.read"], (403, None)),
        ):
            account = {"id": "account-2", "roles": [], "scopes": scopes}
            with (
                self.subTest(scopes=scopes),
                patch("services.dev_server.urllib.request.urlopen") as urlopen,
            ):
                urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                    account
                ).encode()
                status, _, headers = grafana_auth_response("Bearer live-token")
            self.assertEqual(status, expected[0])
            if expected[1]:
                self.assertEqual(headers["X-MyOTA-Grafana-Role"], expected[1])
            else:
                self.assertNotIn("X-MyOTA-Grafana-Role", headers)


if __name__ == "__main__":
    unittest.main()
