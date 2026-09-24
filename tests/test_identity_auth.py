from __future__ import annotations

import sys
import unittest
from os import environ
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from identity import IdentityHandler, bootstrap_admin, seed
from common import verify_token


class IdentityAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        IdentityHandler.store.items.clear()
        IdentityHandler.store.events.clear()
        IdentityHandler.store.data.clear()
        IdentityHandler.store.idempotency.clear()
        seed()

    def call(self, fn, body=None, **params):
        return fn(None, {"_body": body or {}, **params})

    def test_register_login_refresh_logout_and_revocation(self) -> None:
        registered = self.call(IdentityHandler.register, {
            "displayName": "Auth Operator", "email": "auth@example.test",
            "password": "A secure password 2026!", "participationType": "OPERATOR",
            "callsign": "N0AUTH"}, **{"Idempotency-Key": "register-1"})
        self.assertEqual(registered["account"]["primaryCallsignId"], registered["account"]["callsigns"][0]["id"])
        logged_in = self.call(IdentityHandler.login, {"email": "auth@example.test", "password": "A secure password 2026!", "Remote-Addr": "127.0.0.1"})
        self.assertEqual(verify_token(logged_in["accessToken"], "access")["sub"], registered["account"]["id"])
        refreshed = self.call(IdentityHandler.refresh, {"refreshToken": logged_in["refreshToken"]})
        self.assertNotEqual(refreshed["refreshToken"], logged_in["refreshToken"])
        self.call(IdentityHandler.logout, {"refreshToken": refreshed["refreshToken"]})
        with self.assertRaises(PermissionError):
            IdentityHandler.refresh(None, {"_body": {"refreshToken": refreshed["refreshToken"]}})

    def test_recovery_and_callsign_evidence_lifecycle(self) -> None:
        account = self.call(IdentityHandler.register, {
            "displayName": "Evidence Operator", "email": "evidence@example.test",
            "password": "Another secure password!", "participationType": "OPERATOR", "callsign": "EA7EVID"})["account"]
        token = self.call(IdentityHandler.recovery_request, {"email": "evidence@example.test"})["devResetToken"]
        self.call(IdentityHandler.recovery_reset, {"token": token, "newPassword": "Replacement password 2026!"})
        callsign = account["callsigns"][0]
        evidence = self.call(IdentityHandler.add_evidence, {"evidenceType": "LICENSE", "source": "national-regulator"}, accountId=account["id"], callsignId=callsign["id"])
        self.assertEqual(evidence["status"], "PENDING")
        reviewer = {"Authorization": "Bearer " + IdentityHandler._mint_tokens(IdentityHandler.store.items["00000000-0000-4000-8000-000000000001"], {})["accessToken"], "_http": "1", "_body": {"source": "review"}, "accountId": account["id"], "callsignId": callsign["id"]}
        self.assertEqual(IdentityHandler.verify_callsign(None, reviewer)["status"], "VERIFIED")

    def test_scoped_role_and_privacy_export(self) -> None:
        account = self.call(IdentityHandler.register, {
            "displayName": "Scoped Operator", "email": "scoped@example.test",
            "password": "Scoped secure password!", "participationType": "SWL"})["account"]
        admin = IdentityHandler._mint_tokens(IdentityHandler.store.items["00000000-0000-4000-8000-000000000001"], {})["accessToken"]
        role = self.call(IdentityHandler.assign_role, {"role": "GEO_APPROVER", "programmeSlug": "regional-ota", "scopes": ["geodata.review"]}, accountId=account["id"], Authorization="Bearer " + admin, _http="1")
        self.assertEqual(role["programmeSlug"], "regional-ota")
        export = self.call(IdentityHandler.export_account, {}, accountId=account["id"], Authorization="Bearer " + IdentityHandler._mint_tokens(account, {})["accessToken"], _http="1")
        self.assertEqual(export["account"]["id"], account["id"])
        self.call(IdentityHandler.deactivate_account, {"anonymize": True}, accountId=account["id"], Authorization="Bearer " + IdentityHandler._mint_tokens(account, {})["accessToken"], _http="1")
        self.assertEqual(IdentityHandler.store.items[account["id"]]["status"], "DEACTIVATED")

    def test_bootstrap_admin_uses_deployment_credentials_and_global_scope(self) -> None:
        previous_email = environ.get("MYOTA_BOOTSTRAP_ADMIN_EMAIL")
        previous_password = environ.get("MYOTA_BOOTSTRAP_ADMIN_PASSWORD")
        environ["MYOTA_BOOTSTRAP_ADMIN_EMAIL"] = "bootstrap@example.test"
        environ["MYOTA_BOOTSTRAP_ADMIN_PASSWORD"] = "ShortInit!"
        try:
            bootstrap_admin()
            account = IdentityHandler._account_for_email("bootstrap@example.test")
            self.assertIsNotNone(account)
            self.assertEqual(account["participationType"], "OPERATOR")
            role = IdentityHandler._roles(account["id"])[0]
            self.assertEqual(role["role"], "GLOBAL_OPERATOR")
            self.assertIn("*", role["scopes"])
            bootstrap_admin()
            self.assertEqual(len(IdentityHandler._roles(account["id"])), 1)
        finally:
            if previous_email is None:
                environ.pop("MYOTA_BOOTSTRAP_ADMIN_EMAIL", None)
            else:
                environ["MYOTA_BOOTSTRAP_ADMIN_EMAIL"] = previous_email
            if previous_password is None:
                environ.pop("MYOTA_BOOTSTRAP_ADMIN_PASSWORD", None)
            else:
                environ["MYOTA_BOOTSTRAP_ADMIN_PASSWORD"] = previous_password

    def test_admin_can_define_roles_edit_users_and_assign_multiple_roles(self) -> None:
        admin_token = IdentityHandler._mint_tokens(IdentityHandler.store.items["00000000-0000-4000-8000-000000000001"], {})["accessToken"]
        auth = {"Authorization": "Bearer " + admin_token, "_http": "1"}
        custom = self.call(IdentityHandler.create_admin_role, {
            "code": "SEVILLE_REVIEWER", "name": "Seville reviewer", "description": "Review one regional queue",
            "scopes": ["geodata.review"]}, **auth)
        self.assertFalse(custom["system"])
        self.call(IdentityHandler.update_admin_role, {"name": "Seville GIS reviewer", "scopes": ["geodata.review", "geodata.geometry.manage"]}, roleCode=custom["code"], **auth)
        account = self.call(IdentityHandler.register, {"displayName": "New administrator", "email": "new-admin@example.test",
            "password": "A secure admin password!", "participationType": "OPERATOR"})["account"]
        updated = self.call(IdentityHandler.update_admin_account, {"displayName": "GIS and identity administrator", "roles": [{"code": "IDENTITY_ADMIN"}, {"code": "GIS_ADMIN"}]}, accountId=account["id"], **auth)
        self.assertEqual({role["role"] for role in updated["roles"]}, {"IDENTITY_ADMIN", "GIS_ADMIN"})
        listed = self.call(IdentityHandler.list_admin_accounts, {}, **auth)
        listed_account = next(item for item in listed["items"] if item["id"] == account["id"])
        self.assertEqual(len(listed_account["roles"]), 2)


if __name__ == "__main__":
    unittest.main()
