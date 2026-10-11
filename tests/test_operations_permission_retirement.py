import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services"))

from common import Store
from identity import ADMIN_PERMISSION_CATALOG, IdentityHandler


class RetiredOperationsPermissionTests(unittest.TestCase):
    def setUp(self):
        self.original_store = IdentityHandler.store
        self.store = Store("test-identity")
        IdentityHandler.store = self.store

    def tearDown(self):
        IdentityHandler.store = self.original_store

    def test_catalog_and_persisted_role_definitions_drop_operations_read(self):
        self.store.data["roleDefinitions"] = {
            "CUSTOM_READER": {
                "code": "CUSTOM_READER",
                "scopes": ["operations.read", "observability.view"],
            }
        }
        self.store.data["roles"] = {
            "role-1": {
                "id": "role-1",
                "accountId": "account-1",
                "role": "CUSTOM_READER",
            }
        }
        self.assertNotIn(
            "operations.read",
            {entry["code"] for entry in ADMIN_PERMISSION_CATALOG},
        )
        IdentityHandler._role_definitions()
        self.assertEqual(
            self.store.data["roleDefinitions"]["CUSTOM_READER"]["scopes"],
            ["observability.view"],
        )
        self.assertEqual(
            IdentityHandler._scopes("account-1"),
            ["identity.me", "observability.view"],
        )

    def test_current_account_recalculates_scopes_from_live_roles(self):
        self.store.items["account-1"] = {
            "id": "account-1",
            "displayName": "Reader",
            "email": None,
        }
        self.store.data["roleDefinitions"] = {
            "CUSTOM_READER": {
                "code": "CUSTOM_READER",
                "scopes": ["observability.view"],
            }
        }
        self.store.data["roles"] = {
            "role-1": {
                "id": "role-1",
                "accountId": "account-1",
                "role": "CUSTOM_READER",
            }
        }
        with patch.object(
            IdentityHandler,
            "_auth",
            return_value={"sub": "account-1", "scp": ["operations.read"]},
        ):
            response = IdentityHandler.current_account(None, {})
        self.assertEqual(
            response["scopes"], ["identity.me", "observability.view"]
        )
        self.assertNotIn("operations.read", response["scopes"])


if __name__ == "__main__":
    unittest.main()
