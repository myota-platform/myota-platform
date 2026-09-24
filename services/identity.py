"""Amateur-radio-aware identity, authentication and authorization service."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from typing import Any

from common import (JsonHandler, Store, hash_secret, new_id, now, page_result, require,
                    sign_token, verify_secret, verify_token)


ACCESS_SECONDS = int(os.environ.get("MYOTA_ACCESS_TOKEN_SECONDS", "600"))
REFRESH_SECONDS = int(os.environ.get("MYOTA_REFRESH_TOKEN_SECONDS", "2592000"))
RECOVERY_SECONDS = int(os.environ.get("MYOTA_RECOVERY_TOKEN_SECONDS", "1800"))
MAX_LOGIN_ATTEMPTS = int(os.environ.get("MYOTA_MAX_LOGIN_ATTEMPTS", "8"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("MYOTA_LOGIN_WINDOW_SECONDS", "900"))
SECURITY_EVENT_RETENTION_SECONDS = int(os.environ.get("MYOTA_SECURITY_EVENT_RETENTION_SECONDS", "31536000"))

ADMIN_PERMISSION_CATALOG = [
    {"code": "identity.admin", "label": "View and edit user accounts", "group": "Identity"},
    {"code": "identity.roles.assign", "label": "Assign roles to users", "group": "Identity"},
    {"code": "identity.roles.manage", "label": "Create and edit role definitions", "group": "Identity"},
    {"code": "identity.audit.read", "label": "View identity audit events", "group": "Identity"},
    {"code": "callsign.verify", "label": "Verify callsigns", "group": "Identity"},
    {"code": "programme.admin", "label": "Administer programmes", "group": "Programmes"},
    {"code": "programme.policy.manage", "label": "Manage programme rules and awards", "group": "Programmes"},
    {"code": "programme.content.manage", "label": "Manage programme content and translations", "group": "Programmes"},
    {"code": "geodata.review", "label": "Review geodata", "group": "Geodata"},
    {"code": "geodata.import", "label": "Import geodata", "group": "Geodata"},
    {"code": "geodata.geometry.manage", "label": "Change entity geometry types", "group": "Geodata"},
    {"code": "geodata.delete", "label": "Delete rejected geodata", "group": "Geodata"},
    {"code": "activity.read", "label": "Read activity and results", "group": "Activity"},
    {"code": "activity.admin", "label": "Administer activity and awards", "group": "Activity"},
    {"code": "audit.read", "label": "View platform audit records", "group": "Operations"},
    {"code": "identity.service.issue", "label": "Issue service credentials", "group": "Operations"},
    {"code": "identity.oidc.configure", "label": "Configure programme OIDC", "group": "Operations"},
]
ADMIN_PERMISSION_CODES = {item["code"] for item in ADMIN_PERMISSION_CATALOG}
DEFAULT_ROLE_DEFINITIONS = [
    {"code": "GLOBAL_OPERATOR", "name": "Global administrator", "description": "Full platform administration, including role management.", "scopes": ["*"], "system": True},
    {"code": "IDENTITY_ADMIN", "name": "Identity administrator", "description": "Manage users, callsigns and role assignments.", "scopes": ["identity.admin", "identity.roles.assign", "identity.audit.read", "callsign.verify"], "system": True},
    {"code": "GIS_ADMIN", "name": "GIS administrator", "description": "Review, import, edit and remove rejected geodata.", "scopes": ["geodata.review", "geodata.import", "geodata.geometry.manage", "geodata.delete"], "system": True},
    {"code": "GEO_APPROVER", "name": "Geodata approver", "description": "Review scoped geodata proposals.", "scopes": ["geodata.review"], "system": True},
    {"code": "PROGRAMME_ADMIN", "name": "Programme administrator", "description": "Manage programme configuration and published content.", "scopes": ["programme.admin", "programme.policy.manage", "programme.content.manage"], "system": True},
    {"code": "ACTIVITY_ADMIN", "name": "Activity administrator", "description": "Manage activations, QSOs, awards and execution operations.", "scopes": ["activity.read", "activity.admin"], "system": True},
    {"code": "AUDITOR", "name": "Auditor", "description": "Read platform audit and security records.", "scopes": ["audit.read", "identity.audit.read"], "system": True},
]


def epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def iso_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class IdentityHandler(JsonHandler):
    service = "identity-service"
    store = Store("identity", "CORE_DATABASE_URL")

    @staticmethod
    def _bucket(name: str) -> dict[str, Any]:
        return IdentityHandler.store.data.setdefault(name, {})

    @staticmethod
    def _account(account_id: str) -> dict[str, Any]:
        return IdentityHandler.store.items[account_id]

    @staticmethod
    def _account_for_email(email: str) -> dict[str, Any] | None:
        wanted = email.strip().casefold()
        return next((a for a in IdentityHandler.store.items.values()
                     if a.get("email") and a["email"].casefold() == wanted), None)

    @staticmethod
    def _roles(account_id: str) -> list[dict[str, Any]]:
        return [r for r in IdentityHandler._bucket("roles").values() if r["accountId"] == account_id and not r.get("validTo")]

    @staticmethod
    def _role_definitions() -> dict[str, dict[str, Any]]:
        definitions = IdentityHandler._bucket("roleDefinitions")
        for template in DEFAULT_ROLE_DEFINITIONS:
            definitions.setdefault(template["code"], {**template, "createdAt": now(), "updatedAt": now()})
        return definitions

    @staticmethod
    def _role_definition(code: str) -> dict[str, Any] | None:
        return IdentityHandler._role_definitions().get(str(code).upper())

    @staticmethod
    def _admin_authorize(p: dict[str, str], permission: str) -> dict[str, Any]:
        claims = IdentityHandler._auth(p)
        if not claims:
            return {}
        granted = set(claims.get("scp", []))
        if "*" not in granted and permission not in granted:
            raise PermissionError(f"{permission} scope is required")
        return claims

    @staticmethod
    def _admin_authorize_any(p: dict[str, str], permissions: tuple[str, ...]) -> dict[str, Any]:
        claims = IdentityHandler._auth(p)
        if not claims:
            return {}
        granted = set(claims.get("scp", []))
        if "*" not in granted and not granted.intersection(permissions):
            raise PermissionError("one of the required administrative scopes is missing")
        return claims

    @staticmethod
    def _scopes(account_id: str) -> list[str]:
        scopes = {"identity.me"}
        for role in IdentityHandler._roles(account_id):
            definition = IdentityHandler._role_definition(role.get("role", ""))
            scopes.update(definition.get("scopes", []) if definition else role.get("scopes", []))
            if role.get("programmeSlug"):
                scopes.add(f"programme:{role['programmeSlug']}:{role['role'].lower()}")
        return sorted(scopes)

    @staticmethod
    def _auth(p: dict[str, str], scopes: tuple[str, ...] = (), account_id: str | None = None) -> dict[str, Any] | None:
        authorization = p.get("Authorization", "")
        if not authorization:
            if p.get("_http"):
                raise PermissionError("Bearer authentication is required")
            return None
        if not authorization.startswith("Bearer "):
            raise PermissionError("Bearer authentication is required")
        claims = verify_token(authorization[7:], None)
        if claims.get("tokenType") not in ("access", "service"):
            raise PermissionError("access token required")
        if claims.get("jti") in IdentityHandler._bucket("revokedJti"):
            raise PermissionError("token has been revoked")
        granted = set(claims.get("scp", []))
        if scopes and "*" not in granted and not set(scopes).issubset(granted):
            raise PermissionError("required scope is missing")
        if account_id and claims.get("sub") != account_id and "*" not in granted:
            raise PermissionError("account scope is missing")
        return claims

    @staticmethod
    def _audit(event_type: str, payload: dict[str, Any], aggregate_id: str | None = None) -> None:
        record = {"id": new_id(), "eventType": event_type, "occurredAt": now(), "payload": payload}
        IdentityHandler._bucket("securityEvents")[record["id"]] = record
        IdentityHandler.store.event(event_type, "account", aggregate_id or payload.get("accountId", "system"), payload)

    @staticmethod
    def _credentials(account_id: str) -> dict[str, Any]:
        return IdentityHandler._bucket("credentials").setdefault(account_id, {"failedAttempts": 0, "lockedUntil": None})

    @staticmethod
    def _set_password(account_id: str, password: str, enforce_length: bool = True) -> None:
        if enforce_length and len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        credential = IdentityHandler._credentials(account_id)
        credential.update({"passwordHash": hash_secret(password), "passwordChangedAt": now(), "failedAttempts": 0, "lockedUntil": None})

    @staticmethod
    def _rate_limit(key: str) -> None:
        limits = IdentityHandler._bucket("rateLimits")
        current = time.time()
        record = limits.get(key, {"windowStart": current, "count": 0})
        if current - record["windowStart"] >= LOGIN_WINDOW_SECONDS:
            record = {"windowStart": current, "count": 0}
        record["count"] += 1
        limits[key] = record
        if record["count"] > MAX_LOGIN_ATTEMPTS:
            raise PermissionError("too many authentication attempts; try again later")

    @staticmethod
    def cleanup_expired() -> int:
        """Apply identity retention rules and return the number of removed records."""
        current = epoch()
        removed = 0
        for key, record in list(IdentityHandler._bucket("recovery").items()):
            if record.get("usedAt") or record.get("expiresAt", "") <= now():
                IdentityHandler._bucket("recovery").pop(key, None)
                removed += 1
        for key, record in list(IdentityHandler._bucket("sessions").items()):
            if record.get("revokedAt") and record.get("revokedAt", "") < iso_after(-REFRESH_SECONDS):
                IdentityHandler._bucket("sessions").pop(key, None)
                removed += 1
        for key, record in list(IdentityHandler._bucket("revokedJti").items()):
            if int(record.get("expiresAt", 0)) <= current:
                IdentityHandler._bucket("revokedJti").pop(key, None)
                removed += 1
        for key, record in list(IdentityHandler._bucket("rateLimits").items()):
            if current - record.get("windowStart", current) > LOGIN_WINDOW_SECONDS:
                IdentityHandler._bucket("rateLimits").pop(key, None)
                removed += 1
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=SECURITY_EVENT_RETENTION_SECONDS)
        for key, record in list(IdentityHandler._bucket("securityEvents").items()):
            if record.get("occurredAt", "") < cutoff.isoformat().replace("+00:00", "Z"):
                IdentityHandler._bucket("securityEvents").pop(key, None)
                removed += 1
        return removed

    @staticmethod
    def _mint_tokens(account: dict[str, Any], p: dict[str, str]) -> dict[str, Any]:
        session_id, access_jti = new_id(), new_id()
        access = sign_token({"sub": account["id"], "sid": session_id, "jti": access_jti,
                             "scp": IdentityHandler._scopes(account["id"]), "iat": epoch(),
                             "exp": epoch() + ACCESS_SECONDS, "tokenType": "access",
                             "roles": IdentityHandler._roles(account["id"])}, "access")
        refresh = sign_token({"sub": account["id"], "sid": session_id, "jti": new_id(),
                              "iat": epoch(), "exp": epoch() + REFRESH_SECONDS, "tokenType": "refresh"}, "refresh")
        IdentityHandler._bucket("sessions")[session_id] = {
            "id": session_id, "accountId": account["id"], "refreshHash": hashlib.sha256(refresh.encode()).hexdigest(),
            "accessJti": access_jti, "createdAt": now(), "expiresAt": iso_after(REFRESH_SECONDS),
            "revokedAt": None, "userAgent": p.get("User-Agent"), "remoteAddr": p.get("Remote-Addr")}
        return {"accessToken": access, "refreshToken": refresh, "tokenType": "Bearer",
                "expiresIn": ACCESS_SECONDS, "account": account}

    @staticmethod
    def create_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "displayName", "participationType")
        if body["participationType"] not in ("OPERATOR", "SWL"):
            raise ValueError("participationType must be OPERATOR or SWL")
        if body.get("email") and IdentityHandler._account_for_email(body["email"]):
            raise ValueError("email already exists")

        def create() -> dict[str, Any]:
            account_id = new_id()
            account = {"id": account_id, "displayName": body["displayName"], "email": body.get("email"),
                       "participationType": body["participationType"], "status": "ACTIVE", "callsigns": [],
                       "primaryCallsignId": None, "createdAt": now(), "updatedAt": now()}
            IdentityHandler.store.items[account_id] = account
            if body.get("password"):
                IdentityHandler._set_password(account_id, body["password"])
            if body.get("callsign"):
                IdentityHandler._add_callsign(account, body["callsign"], "UNVERIFIED", "self-asserted")
            IdentityHandler.store.event("identity.account.created.v1", "account", account_id, {"account": account})
            return {**account, "_status": 201}
        return IdentityHandler.store.once(p.get("Idempotency-Key"), create)

    @staticmethod
    def register(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "displayName", "email", "password", "participationType")
        if len(body["password"]) < 12:
            raise ValueError("password must contain at least 12 characters")
        created = IdentityHandler.create_account(_, p)
        account = {k: v for k, v in created.items() if k != "_status"}
        return {**IdentityHandler._mint_tokens(account, p), "_status": 201}

    @staticmethod
    def login(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler.cleanup_expired()
        body = p["_body"]
        require(body, "email", "password")
        key = f"login:{body['email'].strip().casefold()}:{p.get('Remote-Addr', 'unknown')}"
        IdentityHandler._rate_limit(key)
        account = IdentityHandler._account_for_email(body["email"])
        credential = IdentityHandler._credentials(account["id"]) if account else {}
        locked_until = credential.get("lockedUntil")
        if locked_until and locked_until > now():
            raise PermissionError("account temporarily locked")
        if not account or account.get("status") != "ACTIVE" or not verify_secret(body["password"], credential.get("passwordHash", "")):
            if account:
                credential["failedAttempts"] = credential.get("failedAttempts", 0) + 1
                if credential["failedAttempts"] >= 5:
                    credential["lockedUntil"] = iso_after(900)
            IdentityHandler._audit("identity.login.failed.v1", {"email": body["email"], "remoteAddr": p.get("Remote-Addr")}, account["id"] if account else None)
            raise ValueError("invalid credentials")
        credential.update({"failedAttempts": 0, "lockedUntil": None})
        IdentityHandler._audit("identity.login.succeeded.v1", {"accountId": account["id"], "remoteAddr": p.get("Remote-Addr")}, account["id"])
        return IdentityHandler._mint_tokens(account, p)

    @staticmethod
    def refresh(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "refreshToken")
        claims = verify_token(body["refreshToken"], "refresh")
        session = IdentityHandler._bucket("sessions").get(claims.get("sid"))
        if not session or session.get("revokedAt") or session.get("refreshHash") != hashlib.sha256(body["refreshToken"].encode()).hexdigest():
            raise PermissionError("refresh session is invalid or revoked")
        session["revokedAt"] = now()
        account = IdentityHandler._account(claims["sub"])
        return IdentityHandler._mint_tokens(account, p)

    @staticmethod
    def logout(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        if body.get("refreshToken"):
            try:
                claims = verify_token(body["refreshToken"], "refresh")
                session = IdentityHandler._bucket("sessions").get(claims.get("sid"))
                if session:
                    session["revokedAt"] = now()
                    IdentityHandler._bucket("revokedJti")[claims.get("jti", "")] = {"expiresAt": claims.get("exp")}
            except PermissionError:
                pass
        if p.get("Authorization"):
            claims = IdentityHandler._auth(p)
            if claims:
                IdentityHandler._bucket("revokedJti")[claims.get("jti", "")] = {"expiresAt": claims.get("exp")}
        return {"status": "logged_out"}

    @staticmethod
    def recovery_request(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler.cleanup_expired()
        body = p["_body"]
        require(body, "email")
        account = IdentityHandler._account_for_email(body["email"])
        response: dict[str, Any] = {"status": "accepted"}
        if account:
            raw = secrets.token_urlsafe(32)
            IdentityHandler._bucket("recovery")[hashlib.sha256(raw.encode()).hexdigest()] = {
                "accountId": account["id"], "expiresAt": iso_after(RECOVERY_SECONDS), "usedAt": None}
            IdentityHandler._audit("identity.recovery.requested.v1", {"accountId": account["id"]}, account["id"])
            if os.environ.get("MYOTA_ENV", "development") != "production" or os.environ.get("MYOTA_EXPOSE_DEV_TOKENS") == "1":
                response["devResetToken"] = raw
        return response

    @staticmethod
    def recovery_reset(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "token", "newPassword")
        record = IdentityHandler._bucket("recovery").get(hashlib.sha256(body["token"].encode()).hexdigest())
        if not record or record.get("usedAt") or record["expiresAt"] <= now():
            raise ValueError("recovery token is invalid or expired")
        IdentityHandler._set_password(record["accountId"], body["newPassword"])
        record["usedAt"] = now()
        for session in IdentityHandler._bucket("sessions").values():
            if session["accountId"] == record["accountId"]:
                session["revokedAt"] = now()
        IdentityHandler._audit("identity.recovery.completed.v1", {"accountId": record["accountId"]}, record["accountId"])
        return {"status": "password_reset"}

    @staticmethod
    def current_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        claims = IdentityHandler._auth(p)
        return {**IdentityHandler._account(claims["sub"]), "roles": IdentityHandler._roles(claims["sub"]), "scopes": claims.get("scp", [])}

    @staticmethod
    def get_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._auth(p, account_id=p["accountId"])
        return IdentityHandler._account(p["accountId"])

    @staticmethod
    def list_admin_accounts(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._admin_authorize(p, "identity.admin")
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(p.get("_path", "")).query)
        status = query.get("status", [None])[0]
        search = query.get("q", [""])[0].casefold()
        accounts = [{**account, "roles": IdentityHandler._roles(account["id"])} for account in IdentityHandler.store.items.values()]
        if status:
            accounts = [a for a in accounts if a.get("status") == status]
        if search:
            accounts = [a for a in accounts if search in a.get("displayName", "").casefold() or search in (a.get("email") or "").casefold()]
        return page_result(accounts, query)

    @staticmethod
    def list_admin_roles(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._admin_authorize_any(p, ("identity.admin", "identity.roles.manage"))
        definitions = sorted(IdentityHandler._role_definitions().values(), key=lambda item: item["code"])
        return {"items": definitions, "permissions": ADMIN_PERMISSION_CATALOG}

    @staticmethod
    def create_admin_role(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._admin_authorize(p, "identity.roles.manage")
        body = p["_body"]
        require(body, "code", "name")
        code = re.sub(r"[^A-Z0-9_]+", "_", str(body["code"]).strip().upper()).strip("_")
        if not code or code in IdentityHandler._role_definitions():
            raise ValueError("role code is empty or already exists")
        scopes = sorted(set(body.get("scopes", [])))
        if any(scope not in ADMIN_PERMISSION_CODES for scope in scopes):
            raise ValueError("role contains an unknown administrative permission")
        role = {"code": code, "name": str(body["name"]).strip(), "description": body.get("description", ""),
                "scopes": scopes, "system": False, "createdAt": now(), "updatedAt": now()}
        IdentityHandler._role_definitions()[code] = role
        IdentityHandler._audit("identity.role-definition.created.v1", role)
        return {**role, "_status": 201}

    @staticmethod
    def update_admin_role(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._admin_authorize(p, "identity.roles.manage")
        code = str(p["roleCode"]).upper()
        role = IdentityHandler._role_definition(code)
        if not role:
            raise KeyError(code)
        if role.get("system"):
            raise ValueError("built-in role definitions cannot be edited")
        body = p["_body"]
        if "name" in body:
            require(body, "name")
            role["name"] = str(body["name"]).strip()
        if "description" in body:
            role["description"] = body["description"]
        if "scopes" in body:
            scopes = sorted(set(body["scopes"]))
            if any(scope not in ADMIN_PERMISSION_CODES for scope in scopes):
                raise ValueError("role contains an unknown administrative permission")
            role["scopes"] = scopes
        role["updatedAt"] = now()
        IdentityHandler._audit("identity.role-definition.updated.v1", role)
        return role

    @staticmethod
    def update_admin_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._admin_authorize(p, "identity.admin")
        account = IdentityHandler._account(p["accountId"])
        body = p["_body"]
        if "email" in body:
            email = body.get("email") or None
            if email and (existing := IdentityHandler._account_for_email(email)) and existing["id"] != account["id"]:
                raise ValueError("email already exists")
            account["email"] = email
        for field in ("displayName", "participationType", "status"):
            if field in body:
                if field == "participationType" and body[field] not in ("OPERATOR", "SWL"):
                    raise ValueError("participationType must be OPERATOR or SWL")
                if field == "status" and body[field] not in ("ACTIVE", "DEACTIVATED"):
                    raise ValueError("status must be ACTIVE or DEACTIVATED")
                account[field] = body[field]
        if body.get("password"):
            IdentityHandler._set_password(account["id"], body["password"])
            for session in IdentityHandler._bucket("sessions").values():
                if session["accountId"] == account["id"]:
                    session["revokedAt"] = now()
        account["updatedAt"] = now()
        IdentityHandler._audit("identity.account.admin-updated.v1", {"accountId": account["id"], "fields": sorted(body.keys())}, account["id"])
        if "roles" in body or "roleCodes" in body:
            IdentityHandler._replace_roles(account["id"], body.get("roles") or [{"code": code} for code in body.get("roleCodes", [])], p)
        return {**account, "roles": IdentityHandler._roles(account["id"])}

    @staticmethod
    def _replace_roles(account_id: str, assignments: list[dict[str, Any]], p: dict[str, str]) -> list[dict[str, Any]]:
        claims = IdentityHandler._admin_authorize(p, "identity.roles.assign")
        normalized: list[dict[str, Any]] = []
        for assignment in assignments:
            code = str(assignment.get("code") or assignment.get("role") or "").upper()
            definition = IdentityHandler._role_definition(code)
            if not definition:
                raise ValueError(f"unknown role: {code}")
            if code == "GLOBAL_OPERATOR" and claims and "*" not in set(claims.get("scp", [])):
                raise PermissionError("only a global administrator can assign the global administrator role")
            normalized.append({"code": code, "programmeSlug": assignment.get("programmeSlug"),
                               "jurisdiction": assignment.get("jurisdiction"), "entityType": assignment.get("entityType")})
        current = IdentityHandler._roles(account_id)
        current_global = any(item.get("role") == "GLOBAL_OPERATOR" for item in current)
        next_global = any(item["code"] == "GLOBAL_OPERATOR" for item in normalized)
        global_count = sum(1 for account in IdentityHandler.store.items.values() if any(item.get("role") == "GLOBAL_OPERATOR" for item in IdentityHandler._roles(account["id"])) )
        if current_global and not next_global and global_count <= 1:
            raise ValueError("the last global administrator cannot lose the global administrator role")
        changed_at = now()
        for role in current:
            role["validTo"] = changed_at
        result = []
        for assignment in normalized:
            role = {"id": new_id(), "accountId": account_id, "role": assignment["code"],
                    "programmeSlug": assignment.get("programmeSlug"), "jurisdiction": assignment.get("jurisdiction"),
                    "entityType": assignment.get("entityType"), "scopes": IdentityHandler._role_definition(assignment["code"])["scopes"],
                    "createdAt": changed_at, "validTo": None}
            IdentityHandler._bucket("roles")[role["id"]] = role
            result.append(role)
        IdentityHandler._audit("identity.roles.replaced.v1", {"accountId": account_id, "roles": result}, account_id)
        return result

    @staticmethod
    def list_security_events(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._auth(p, scopes=("identity.admin",))
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(p.get("_path", "")).query)
        events = sorted(IdentityHandler._bucket("securityEvents").values(), key=lambda e: e.get("occurredAt", ""), reverse=True)
        return page_result(events, query)

    @staticmethod
    def add_callsign(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "callsign")
        IdentityHandler._auth(p, account_id=p["accountId"])
        account = IdentityHandler._account(p["accountId"])
        def add() -> dict[str, Any]:
            callsign = IdentityHandler._add_callsign(account, body["callsign"], body.get("status", "UNVERIFIED"), body.get("source", "self-asserted"), body.get("validFrom"), body.get("validTo"))
            return {"account": account, "callsign": callsign, "_status": 201}
        return IdentityHandler.store.once(p.get("Idempotency-Key"), add)

    @staticmethod
    def set_primary(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "callsignId")
        IdentityHandler._auth(p, account_id=p["accountId"])
        account = IdentityHandler._account(p["accountId"])
        if not any(c["id"] == body["callsignId"] and c["status"] != "RETIRED" for c in account["callsigns"]):
            raise ValueError("callsignId is not an active callsign on this account")
        account["primaryCallsignId"] = body["callsignId"]
        account["updatedAt"] = now()
        IdentityHandler.store.event("identity.callsign.primary-changed.v1", "account", account["id"], {"callsignId": body["callsignId"]})
        return account

    @staticmethod
    def add_evidence(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "evidenceType", "source")
        IdentityHandler._auth(p, account_id=p["accountId"])
        account = IdentityHandler._account(p["accountId"])
        callsign = next(c for c in account["callsigns"] if c["id"] == p["callsignId"])
        evidence = {"id": new_id(), "callsignId": callsign["id"], "accountId": account["id"],
                    "evidenceType": body["evidenceType"], "source": body["source"], "checksum": body.get("checksum"),
                    "metadata": body.get("metadata", {}), "submittedAt": now(), "status": "PENDING"}
        IdentityHandler._bucket("callsignEvidence")[evidence["id"]] = evidence
        callsign["evidenceIds"] = callsign.get("evidenceIds", []) + [evidence["id"]]
        IdentityHandler.store.event("identity.callsign.evidence-submitted.v1", "callsign", callsign["id"], evidence)
        return {**evidence, "_status": 201}

    @staticmethod
    def verify_callsign(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._auth(p, scopes=("callsign.verify",))
        account = IdentityHandler._account(p["accountId"])
        callsign = next(c for c in account["callsigns"] if c["id"] == p["callsignId"])
        evidence = [e for e in IdentityHandler._bucket("callsignEvidence").values() if e["callsignId"] == callsign["id"]]
        if not evidence and p.get("_http"):
            raise ValueError("at least one evidence record is required")
        callsign.update({"status": "VERIFIED", "verifiedAt": now(), "verificationSource": p["_body"].get("source", "manual-review"), "updatedAt": now()})
        for item in evidence:
            item["status"] = "ACCEPTED"
            item["reviewedAt"] = now()
        IdentityHandler.store.event("identity.callsign.verified.v1", "callsign", callsign["id"], callsign)
        return callsign

    @staticmethod
    def retire_callsign(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        IdentityHandler._auth(p, account_id=p["accountId"])
        account = IdentityHandler._account(p["accountId"])
        callsign = next(c for c in account["callsigns"] if c["id"] == p["callsignId"])
        if account.get("primaryCallsignId") == callsign["id"]:
            replacement = body.get("newPrimaryCallsignId")
            if not replacement or not any(c["id"] == replacement and c["status"] != "RETIRED" for c in account["callsigns"]):
                raise ValueError("retiring the primary callsign requires an active replacement")
            account["primaryCallsignId"] = replacement
        callsign.update({"status": "RETIRED", "validTo": body.get("validTo", now()), "updatedAt": now()})
        account["updatedAt"] = now()
        IdentityHandler.store.event("identity.callsign.retired.v1", "callsign", callsign["id"], callsign)
        return callsign

    @staticmethod
    def _add_callsign(account: dict[str, Any], value: str, status: str, source: str,
                      valid_from: str | None = None, valid_to: str | None = None) -> dict[str, Any]:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("callsign cannot be empty")
        if any(c["value"] == normalized and c["status"] != "RETIRED" for c in account["callsigns"]):
            raise ValueError("callsign already exists on account")
        callsign = {"id": new_id(), "value": normalized, "status": status, "source": source,
                    "verificationSource": source if status == "VERIFIED" else None,
                    "verifiedAt": now() if status == "VERIFIED" else None, "validFrom": valid_from,
                    "validTo": valid_to, "evidenceIds": [], "createdAt": now(), "updatedAt": now()}
        account["callsigns"].append(callsign)
        if account["primaryCallsignId"] is None and account["participationType"] == "OPERATOR":
            account["primaryCallsignId"] = callsign["id"]
        account["updatedAt"] = now()
        IdentityHandler.store.event("identity.callsign.added.v1", "callsign", callsign["id"], {"accountId": account["id"], **callsign})
        return callsign

    @staticmethod
    def assign_role(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "role")
        claims = IdentityHandler._auth(p, scopes=("identity.roles.assign",))
        code = str(body["role"]).upper()
        definition = IdentityHandler._role_definition(code)
        if not definition:
            raise ValueError(f"unknown role: {code}")
        if code == "GLOBAL_OPERATOR" and claims and "*" not in set(claims.get("scp", [])):
            raise PermissionError("only a global operator can assign global operator role")
        role = {"id": new_id(), "accountId": p["accountId"], "role": code,
                "programmeSlug": body.get("programmeSlug"), "jurisdiction": body.get("jurisdiction"),
                "entityType": body.get("entityType"), "scopes": definition["scopes"],
                "createdAt": now(), "validTo": None}
        IdentityHandler._bucket("roles")[role["id"]] = role
        IdentityHandler._audit("identity.role.assigned.v1", role, p["accountId"])
        return {**role, "_status": 201}

    @staticmethod
    def list_roles(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._auth(p, account_id=p["accountId"])
        return {"items": IdentityHandler._roles(p["accountId"])}

    @staticmethod
    def oidc_mapping(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "programmeSlug", "issuer", "clientId")
        IdentityHandler._auth(p, scopes=("identity.oidc.configure",))
        mapping = {"id": new_id(), "programmeSlug": body["programmeSlug"], "issuer": body["issuer"],
                   "clientId": body["clientId"], "scopes": body.get("scopes", ["openid", "profile", "email"]),
                   "enabled": body.get("enabled", True), "createdAt": now(), "updatedAt": now()}
        IdentityHandler._bucket("oidcMappings")[mapping["id"]] = mapping
        IdentityHandler._audit("identity.oidc.mapping.updated.v1", mapping)
        return {**mapping, "_status": 201}

    @staticmethod
    def issue_service_token(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "service", "scopes")
        IdentityHandler._auth(p, scopes=("identity.service.issue",))
        token = sign_token({"sub": f"service:{body['service']}", "jti": new_id(), "scp": body["scopes"],
                            "iat": epoch(), "exp": epoch() + 300, "tokenType": "service"}, "service")
        IdentityHandler._audit("identity.service-token.issued.v1", {"service": body["service"], "scopes": body["scopes"]})
        return {"accessToken": token, "tokenType": "Bearer", "expiresIn": 300}

    @staticmethod
    def export_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        IdentityHandler._auth(p, account_id=p["accountId"])
        account = IdentityHandler._account(p["accountId"])
        return {"account": account, "roles": IdentityHandler._roles(account["id"]),
                "callsignEvidence": [e for e in IdentityHandler._bucket("callsignEvidence").values() if e["accountId"] == account["id"]],
                "securityEvents": [e for e in IdentityHandler._bucket("securityEvents").values() if e["payload"].get("accountId") == account["id"]]}

    @staticmethod
    def deactivate_account(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        IdentityHandler._auth(p, account_id=p["accountId"])
        account = IdentityHandler._account(p["accountId"])
        account["status"] = "DEACTIVATED"
        if body.get("anonymize", True):
            account.update({"displayName": "Deactivated account", "email": None})
        for session in IdentityHandler._bucket("sessions").values():
            if session["accountId"] == account["id"]:
                session["revokedAt"] = now()
        account["updatedAt"] = now()
        IdentityHandler._audit("identity.account.deactivated.v1", {"accountId": account["id"], "anonymized": body.get("anonymize", True)}, account["id"])
        return account


def bootstrap_admin() -> None:
    """Create one operator-owned global admin from deployment-provided secrets.

    The password is read only from the process environment and is never written
    to source, logs, events or the account export. Existing accounts are not
    reset; the bootstrap is safe to run on every startup.
    """
    email = os.environ.get("MYOTA_BOOTSTRAP_ADMIN_EMAIL", "").strip().casefold()
    password = os.environ.get("MYOTA_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or not password:
        return
    account = IdentityHandler._account_for_email(email)
    if not account:
        account_id = new_id()
        account = {"id": account_id, "displayName": "Global Administrator", "email": email,
                   "participationType": "OPERATOR", "status": "ACTIVE", "callsigns": [],
                   "primaryCallsignId": None, "createdAt": now(), "updatedAt": now()}
        IdentityHandler.store.items[account_id] = account
        IdentityHandler._set_password(account_id, password, enforce_length=False)
        IdentityHandler.store.event("identity.account.created.v1", "account", account_id, {"account": account, "source": "bootstrap"})
    elif not IdentityHandler._credentials(account["id"]).get("passwordHash"):
        IdentityHandler._set_password(account["id"], password, enforce_length=False)
    if not any(role.get("role") == "GLOBAL_OPERATOR" and role.get("accountId") == account["id"] for role in IdentityHandler._roles(account["id"])):
        role = {"id": new_id(), "accountId": account["id"], "role": "GLOBAL_OPERATOR", "programmeSlug": None,
                "jurisdiction": None, "entityType": None,
                "scopes": ["identity.admin", "identity.roles.assign", "identity.roles.manage", "identity.oidc.configure", "identity.service.issue",
                           "callsign.verify", "geodata.review", "geodata.import", "activity.admin", "activity.read", "*"],
                "createdAt": now(), "validTo": None}
        IdentityHandler._bucket("roles")[role["id"]] = role
        IdentityHandler._audit("identity.bootstrap-admin.created.v1", {"accountId": account["id"], "email": email}, account["id"])


IdentityHandler.routes = {
    ("POST", "/v1/identity/accounts"): IdentityHandler.create_account,
    ("POST", "/v1/identity/auth/register"): IdentityHandler.register,
    ("POST", "/v1/identity/auth/login"): IdentityHandler.login,
    ("POST", "/v1/identity/auth/refresh"): IdentityHandler.refresh,
    ("POST", "/v1/identity/auth/logout"): IdentityHandler.logout,
    ("POST", "/v1/identity/auth/recovery/request"): IdentityHandler.recovery_request,
    ("POST", "/v1/identity/auth/recovery/reset"): IdentityHandler.recovery_reset,
    ("POST", "/v1/identity/auth/service-token"): IdentityHandler.issue_service_token,
    ("GET", "/v1/identity/me"): IdentityHandler.current_account,
    ("GET", "/v1/identity/accounts/{accountId}"): IdentityHandler.get_account,
    ("GET", "/v1/identity/admin/accounts"): IdentityHandler.list_admin_accounts,
    ("POST", "/v1/identity/admin/accounts/{accountId}/update"): IdentityHandler.update_admin_account,
    ("GET", "/v1/identity/admin/roles"): IdentityHandler.list_admin_roles,
    ("POST", "/v1/identity/admin/roles"): IdentityHandler.create_admin_role,
    ("POST", "/v1/identity/admin/roles/{roleCode}/update"): IdentityHandler.update_admin_role,
    ("GET", "/v1/identity/admin/security-events"): IdentityHandler.list_security_events,
    ("GET", "/v1/identity/accounts/{accountId}/export"): IdentityHandler.export_account,
    ("POST", "/v1/identity/accounts/{accountId}/deactivate"): IdentityHandler.deactivate_account,
    ("POST", "/v1/identity/accounts/{accountId}/callsigns"): IdentityHandler.add_callsign,
    ("POST", "/v1/identity/accounts/{accountId}/primary-callsign"): IdentityHandler.set_primary,
    ("POST", "/v1/identity/accounts/{accountId}/callsigns/{callsignId}/evidence"): IdentityHandler.add_evidence,
    ("POST", "/v1/identity/accounts/{accountId}/callsigns/{callsignId}/verify"): IdentityHandler.verify_callsign,
    ("POST", "/v1/identity/accounts/{accountId}/callsigns/{callsignId}/retire"): IdentityHandler.retire_callsign,
    ("GET", "/v1/identity/accounts/{accountId}/roles"): IdentityHandler.list_roles,
    ("POST", "/v1/identity/accounts/{accountId}/roles"): IdentityHandler.assign_role,
    ("POST", "/v1/identity/oidc/providers"): IdentityHandler.oidc_mapping,
}


def seed() -> None:
    IdentityHandler.store.hydrate()
    IdentityHandler._role_definitions()
    if IdentityHandler.store.items:
        return
    account = {"id": "00000000-0000-4000-8000-000000000001", "displayName": "Demo Operator", "email": "demo@example.test",
              "participationType": "OPERATOR", "status": "ACTIVE", "callsigns": [], "primaryCallsignId": None,
              "createdAt": now(), "updatedAt": now()}
    IdentityHandler.store.items[account["id"]] = account
    IdentityHandler._add_callsign(account, "EA7DEMO", "VERIFIED", "demo-seed")
    IdentityHandler._add_callsign(account, "EA7ALT", "UNVERIFIED", "demo-seed")
    IdentityHandler._set_password(account["id"], "DemoOperator!ChangeMe2026")
    role = {"id": "00000000-0000-4000-8000-000000000901", "accountId": account["id"], "role": "GLOBAL_OPERATOR",
            "programmeSlug": None, "jurisdiction": None, "entityType": None,
            "scopes": ["callsign.verify", "identity.roles.assign", "identity.oidc.configure", "identity.service.issue"],
            "createdAt": now(), "validTo": None}
    IdentityHandler._bucket("roles")[role["id"]] = role


if __name__ == "__main__":
    seed()
    bootstrap_admin()
    server = ThreadingHTTPServer(("0.0.0.0", 8001), IdentityHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        IdentityHandler.store.persist()
        IdentityHandler.store.close()
        server.server_close()
