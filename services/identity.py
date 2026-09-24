from __future__ import annotations

from http.server import ThreadingHTTPServer
from typing import Any

from common import JsonHandler, Store, new_id, now, require


class IdentityHandler(JsonHandler):
    service = "identity-service"
    store = Store("identity", "CORE_DATABASE_URL")

    @staticmethod
    def create_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "displayName", "participationType")
        if body["participationType"] not in ("OPERATOR", "SWL"):
            raise ValueError("participationType must be OPERATOR or SWL")
        def create() -> dict[str, Any]:
            account_id = new_id()
            account = {"id": account_id, "displayName": body["displayName"], "email": body.get("email"),
                       "participationType": body["participationType"], "status": "ACTIVE", "callsigns": [],
                       "primaryCallsignId": None, "createdAt": now(), "updatedAt": now()}
            IdentityHandler.store.items[account_id] = account
            IdentityHandler.store.event("identity.account.created.v1", "account", account_id, account)
            if body.get("callsign"):
                IdentityHandler._add_callsign(account, body["callsign"], "UNVERIFIED", "self-asserted")
            return {**account, "_status": 201}
        return IdentityHandler.store.once(p.get("Idempotency-Key"), create)

    @staticmethod
    def get_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        return IdentityHandler.store.items[p["accountId"]]

    @staticmethod
    def add_callsign(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "callsign")
        account = IdentityHandler.store.items[p["accountId"]]
        def add() -> dict[str, Any]:
            callsign = IdentityHandler._add_callsign(account, body["callsign"], body.get("status", "UNVERIFIED"), body.get("source", "self-asserted"))
            return {"account": account, "callsign": callsign, "_status": 201}
        return IdentityHandler.store.once(p.get("Idempotency-Key"), add)

    @staticmethod
    def set_primary(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "callsignId")
        account = IdentityHandler.store.items[p["accountId"]]
        if not any(c["id"] == body["callsignId"] and c["status"] != "RETIRED" for c in account["callsigns"]):
            raise ValueError("callsignId is not an active callsign on this account")
        account["primaryCallsignId"] = body["callsignId"]
        account["updatedAt"] = now()
        IdentityHandler.store.event("identity.callsign.primary-changed.v1", "account", account["id"], {"callsignId": body["callsignId"]})
        return account

    @staticmethod
    def verify_callsign(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        account = IdentityHandler.store.items[p["accountId"]]
        callsign = next(c for c in account["callsigns"] if c["id"] == p["callsignId"])
        callsign["status"] = "VERIFIED"
        callsign["verifiedAt"] = now()
        callsign["updatedAt"] = now()
        IdentityHandler.store.event("identity.callsign.verified.v1", "callsign", callsign["id"], callsign)
        return callsign

    @staticmethod
    def _add_callsign(account: dict[str, Any], value: str, status: str, source: str) -> dict[str, Any]:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("callsign cannot be empty")
        if any(c["value"] == normalized and c["status"] != "RETIRED" for c in account["callsigns"]):
            raise ValueError("callsign already exists on account")
        callsign = {"id": new_id(), "value": normalized, "status": status, "source": source,
                    "verifiedAt": now() if status == "VERIFIED" else None, "createdAt": now(), "updatedAt": now()}
        account["callsigns"].append(callsign)
        if account["primaryCallsignId"] is None and account["participationType"] == "OPERATOR":
            account["primaryCallsignId"] = callsign["id"]
        account["updatedAt"] = now()
        IdentityHandler.store.event("identity.callsign.added.v1", "callsign", callsign["id"], {"accountId": account["id"], **callsign})
        return callsign


IdentityHandler.routes = {
    ("POST", "/v1/identity/accounts"): IdentityHandler.create_account,
    ("GET", "/v1/identity/accounts/{accountId}"): IdentityHandler.get_account,
    ("POST", "/v1/identity/accounts/{accountId}/callsigns"): IdentityHandler.add_callsign,
    ("POST", "/v1/identity/accounts/{accountId}/primary-callsign"): IdentityHandler.set_primary,
    ("POST", "/v1/identity/accounts/{accountId}/callsigns/{callsignId}/verify"): IdentityHandler.verify_callsign,
}


def seed() -> None:
    IdentityHandler.store.hydrate()
    if IdentityHandler.store.items:
        return
    account = {"id": "00000000-0000-4000-8000-000000000001", "displayName": "Demo Operator", "email": "demo@example.test",
              "participationType": "OPERATOR", "status": "ACTIVE", "callsigns": [], "primaryCallsignId": None,
              "createdAt": now(), "updatedAt": now()}
    IdentityHandler.store.items[account["id"]] = account
    IdentityHandler._add_callsign(account, "EA7DEMO", "VERIFIED", "demo-seed")
    IdentityHandler._add_callsign(account, "EA7ALT", "UNVERIFIED", "demo-seed")


if __name__ == "__main__":
    seed()
    ThreadingHTTPServer(("0.0.0.0", 8001), IdentityHandler).serve_forever()
