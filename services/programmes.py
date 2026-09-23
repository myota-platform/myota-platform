from __future__ import annotations

from http.server import ThreadingHTTPServer
from typing import Any

from common import JsonHandler, Store, new_id, now, require


class ProgrammeHandler(JsonHandler):
    service = "programme-service"
    store = Store()

    @staticmethod
    def list_programmes(_: JsonHandler, __: dict[str, str]) -> dict[str, Any]:
        return {"items": list(ProgrammeHandler.store.items.values())}

    @staticmethod
    def get_programme(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        return ProgrammeHandler.store.items[p["slug"]]

    @staticmethod
    def create_programme(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        body = p["_body"]
        require(body, "slug", "name", "entityTypes", "rules")
        slug = body["slug"].lower()
        if slug in ProgrammeHandler.store.items:
            raise ValueError("programme slug already exists")
        programme = {"id": new_id(), "slug": slug, "name": body["name"], "description": body.get("description", ""),
                     "entityTypes": body["entityTypes"], "rules": body["rules"],
                     "theme": body.get("theme", {"primary": "#0f766e", "accent": "#f59e0b"}),
                     "oidc": body.get("oidc"), "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}
        ProgrammeHandler.store.items[slug] = programme
        ProgrammeHandler.store.event("programme.created.v1", "programme", programme["id"], programme)
        return {**programme, "_status": 201}


ProgrammeHandler.routes = {
    ("GET", "/v1/programmes"): ProgrammeHandler.list_programmes,
    ("GET", "/v1/programmes/{slug}"): ProgrammeHandler.get_programme,
    ("POST", "/v1/programmes"): ProgrammeHandler.create_programme,
}


def seed() -> None:
    ProgrammeHandler.store.items["mpota"] = {
        "id": "00000000-0000-4000-8000-000000000101", "slug": "mpota", "name": "Municipal Parks on the Air",
        "description": "Synthetic sample configuration for a municipal-park programme; replace with programme-owner policy before production.",
        "entityTypes": [{"code": "MUNICIPAL_PARK", "label": "Municipal park", "geometry": "MULTIPOLYGON"}],
        "rules": {"minimumQsos": {"activation": 10, "hunter": 1}, "excludeOverlappingProgrammes": True,
                  "activationValidityDays": 365, "publicAccessRequired": True},
        "theme": {"primary": "#0f766e", "accent": "#f59e0b", "surface": "#f0fdfa"},
        "oidc": None, "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}
    ProgrammeHandler.store.items["regional-ota"] = {
        "id": "00000000-0000-4000-8000-000000000102", "slug": "regional-ota", "name": "Regional Outdoor Activation",
        "description": "Synthetic second configuration proving that the UI is not MPOTA-specific.",
        "entityTypes": [{"code": "NATURE_RESERVE", "label": "Nature reserve", "geometry": "MULTIPOLYGON"}],
        "rules": {"minimumQsos": {"activation": 5, "hunter": 1}, "excludeOverlappingProgrammes": False,
                  "activationValidityDays": 730, "publicAccessRequired": False},
        "theme": {"primary": "#1d4ed8", "accent": "#fb7185", "surface": "#eff6ff"},
        "oidc": {"enabled": False}, "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}


if __name__ == "__main__":
    seed()
    ThreadingHTTPServer(("0.0.0.0", 8002), ProgrammeHandler).serve_forever()
