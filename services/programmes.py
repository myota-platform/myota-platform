from __future__ import annotations

from http.server import ThreadingHTTPServer
from typing import Any

from common import JsonHandler, Store, new_id, now, page_result, require, verify_token


class ProgrammeHandler(JsonHandler):
    service = "programme-service"
    store = Store("programmes", "CORE_DATABASE_URL")

    @staticmethod
    def _authorize_admin(p: dict[str, str], slug: str | None = None) -> None:
        if not p.get("_http"):
            return
        authorization = p.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise PermissionError("Bearer authentication is required")
        claims = verify_token(authorization[7:])
        scopes = set(claims.get("scp", []))
        if "*" in scopes or "programme.admin" in scopes:
            return
        if slug and f"programme:{slug}:programme_admin" in scopes:
            return
        raise PermissionError("programme administration scope is required")

    @staticmethod
    def list_programmes(_: JsonHandler, __: dict[str, str]) -> dict[str, Any]:
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(__.get("_path", "")).query)
        return page_result(list(ProgrammeHandler.store.items.values()), query)

    @staticmethod
    def get_programme(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        return ProgrammeHandler.store.items[p["slug"]]

    @staticmethod
    def create_programme(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "slug", "name", "entityTypes", "rules")
        slug = body["slug"].lower()
        ProgrammeHandler._authorize_admin(p, slug)
        if slug in ProgrammeHandler.store.items:
            raise ValueError("programme slug already exists")
        programme = {"id": new_id(), "slug": slug, "name": body["name"], "description": body.get("description", ""),
                     "entityTypes": body["entityTypes"], "rules": body["rules"],
                     "policyVersion": int(body.get("policyVersion", 1)),
                     "theme": body.get("theme", {"primary": "#0f766e", "accent": "#f59e0b"}),
                     "oidc": body.get("oidc"), "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}
        ProgrammeHandler.store.items[slug] = programme
        ProgrammeHandler.store.event("programme.created.v1", "programme", programme["id"], programme)
        return {**programme, "_status": 201}

    @staticmethod
    def update_programme(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        programme = ProgrammeHandler.store.items[p["slug"]]
        body = p["_body"]
        for field in ("name", "description", "entityTypes", "rules", "theme", "oidc"):
            if field in body:
                programme[field] = body[field]
        if any(field in body for field in ("entityTypes", "rules")):
            programme["policyVersion"] = programme.get("policyVersion", 1) + 1
        programme["updatedAt"] = now()
        ProgrammeHandler.store.event("programme.updated.v1", "programme", programme["id"], programme)
        return programme

    @staticmethod
    def archive_programme(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        programme = ProgrammeHandler.store.items[p["slug"]]
        programme["status"], programme["updatedAt"] = "ARCHIVED", now()
        ProgrammeHandler.store.event("programme.archived.v1", "programme", programme["id"], {"slug": p["slug"]})
        return programme

    @staticmethod
    def get_policy(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        programme = ProgrammeHandler.store.items[p["slug"]]
        return {"programmeSlug": programme["slug"], "version": programme.get("policyVersion", 1),
                "rules": programme["rules"], "entityTypes": programme["entityTypes"], "updatedAt": programme["updatedAt"]}


ProgrammeHandler.routes = {
    ("GET", "/v1/programmes"): ProgrammeHandler.list_programmes,
    ("GET", "/v1/programmes/{slug}"): ProgrammeHandler.get_programme,
    ("POST", "/v1/programmes"): ProgrammeHandler.create_programme,
    ("POST", "/v1/programmes/{slug}/update"): ProgrammeHandler.update_programme,
    ("POST", "/v1/programmes/{slug}/archive"): ProgrammeHandler.archive_programme,
    ("GET", "/v1/programmes/{slug}/policy"): ProgrammeHandler.get_policy,
}


def seed() -> None:
    ProgrammeHandler.store.hydrate()
    if ProgrammeHandler.store.items:
        return
    ProgrammeHandler.store.items["mpota"] = {
        "id": "00000000-0000-4000-8000-000000000101", "slug": "mpota", "name": "Municipal Parks on the Air",
        "description": "Synthetic sample configuration for a municipal-park programme; replace with programme-owner policy before production.",
        "entityTypes": [{"code": "MUNICIPAL_PARK", "label": "Municipal park", "geometry": "MULTIPOLYGON"}],
        "policyVersion": 1,
        "rules": {"minimumQsos": {"activation": 10, "hunter": 1}, "excludeOverlappingProgrammes": True,
                  "activationValidityDays": 365, "publicAccessRequired": True},
        "theme": {"primary": "#0f766e", "accent": "#f59e0b", "surface": "#f0fdfa"},
        "oidc": None, "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}
    ProgrammeHandler.store.items["regional-ota"] = {
        "id": "00000000-0000-4000-8000-000000000102", "slug": "regional-ota", "name": "Regional Outdoor Activation",
        "description": "Synthetic second configuration proving that the UI is not MPOTA-specific.",
        "entityTypes": [{"code": "NATURE_RESERVE", "label": "Nature reserve", "geometry": "MULTIPOLYGON"}],
        "policyVersion": 1,
        "rules": {"minimumQsos": {"activation": 5, "hunter": 1}, "excludeOverlappingProgrammes": False,
                  "activationValidityDays": 730, "publicAccessRequired": False},
        "theme": {"primary": "#1d4ed8", "accent": "#fb7185", "surface": "#eff6ff"},
        "oidc": {"enabled": False}, "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}


if __name__ == "__main__":
    seed()
    ThreadingHTTPServer(("0.0.0.0", 8002), ProgrammeHandler).serve_forever()
