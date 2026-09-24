from __future__ import annotations

from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

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
    def _content_bucket() -> dict[str, dict[str, Any]]:
        return ProgrammeHandler.store.data.setdefault("content", {})

    @staticmethod
    def _policy_bucket() -> dict[str, dict[str, Any]]:
        return ProgrammeHandler.store.data.setdefault("policyDrafts", {})

    @staticmethod
    def list_content(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        query = parse_qs(urlparse(p.get("_path", "")).query)
        items = [item for item in ProgrammeHandler._content_bucket().values() if item["programmeSlug"] == p["slug"]]
        if query.get("locale"):
            items = [item for item in items if item["locale"] == query["locale"][0]]
        if query.get("status"):
            items = [item for item in items if item["status"] == query["status"][0]]
        return page_result(sorted(items, key=lambda item: (item["key"], item["locale"])), query)

    @staticmethod
    def save_content(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        body = p["_body"]
        content_id = body.get("contentId") or new_id()
        content = ProgrammeHandler._content_bucket().get(content_id)
        if content and content["programmeSlug"] != p["slug"]:
            raise ValueError("content does not belong to programme")
        require(body, "key", "locale", "value")
        if content and content["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
            raise ValueError("only draft content can be edited")
        record = {**(content or {"id": content_id, "programmeSlug": p["slug"], "status": "DRAFT",
                                 "reviewHistory": [], "createdAt": now()}),
                  "key": body["key"], "locale": body["locale"], "value": body["value"],
                  "fallbackLocale": body.get("fallbackLocale"), "updatedAt": now()}
        ProgrammeHandler._content_bucket()[content_id] = record
        ProgrammeHandler.store.event("programme.content.saved.v1", "content", content_id, record)
        return {**record, "_status": 201 if not content else 200}

    @staticmethod
    def submit_content(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        content = ProgrammeHandler._content_bucket()[p["contentId"]]
        if content["programmeSlug"] != p["slug"] or content["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
            raise ValueError("only draft content can be submitted")
        content["status"], content["submittedAt"], content["updatedAt"] = "UNDER_REVIEW", now(), now()
        content["reviewHistory"].append({"action": "SUBMITTED", "occurredAt": content["submittedAt"]})
        ProgrammeHandler.store.event("programme.content.submitted.v1", "content", content["id"], content)
        return content

    @staticmethod
    def review_content(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        body = p["_body"]
        require(body, "decision", "reviewerId")
        if body["decision"] not in ("APPROVED", "CHANGES_REQUESTED"):
            raise ValueError("decision must be APPROVED or CHANGES_REQUESTED")
        content = ProgrammeHandler._content_bucket()[p["contentId"]]
        if content["programmeSlug"] != p["slug"] or content["status"] != "UNDER_REVIEW":
            raise ValueError("only content under review can be decided")
        content["status"], content["reviewedAt"], content["updatedAt"] = body["decision"], now(), now()
        content["reviewHistory"].append({"action": body["decision"], "reviewerId": body["reviewerId"],
                                         "note": body.get("note"), "occurredAt": content["reviewedAt"]})
        ProgrammeHandler.store.event("programme.content.reviewed.v1", "content", content["id"], content)
        return content

    @staticmethod
    def publish_content(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        body = p["_body"]
        require(body, "effectiveFrom", "publisherId")
        content = ProgrammeHandler._content_bucket()[p["contentId"]]
        if content["programmeSlug"] != p["slug"] or content["status"] != "APPROVED":
            raise ValueError("only approved content can be published")
        content["status"], content["effectiveFrom"], content["publishedAt"], content["publisherId"] = "PUBLISHED", body["effectiveFrom"], now(), body["publisherId"]
        content["updatedAt"] = now()
        content["reviewHistory"].append({"action": "PUBLISHED", "publisherId": body["publisherId"],
                                         "effectiveFrom": body["effectiveFrom"], "occurredAt": content["publishedAt"]})
        ProgrammeHandler.store.event("programme.content.published.v1", "content", content["id"], content)
        return content

    @staticmethod
    def content_coverage(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        programme = ProgrammeHandler.store.items[p["slug"]]
        items = [item for item in ProgrammeHandler._content_bucket().values() if item["programmeSlug"] == p["slug"]]
        keys = sorted({item["key"] for item in items})
        locales = programme.get("locales") or sorted({item["locale"] for item in items}) or ["en"]
        by_locale = []
        for locale in locales:
            published = {item["key"] for item in items if item["locale"] == locale and item["status"] == "PUBLISHED"}
            by_locale.append({"locale": locale, "published": len(published), "total": len(keys),
                              "coveragePercent": round((len(published) / len(keys)) * 100) if keys else 0,
                              "missingKeys": [key for key in keys if key not in published]})
        return {"programmeSlug": p["slug"], "locales": by_locale, "totalKeys": len(keys)}

    @staticmethod
    def list_policy_drafts(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        query = parse_qs(urlparse(p.get("_path", "")).query)
        items = [item for item in ProgrammeHandler._policy_bucket().values() if item["programmeSlug"] == p["slug"]]
        if query.get("type"):
            items = [item for item in items if item["type"] == query["type"][0]]
        return page_result(sorted(items, key=lambda item: item["updatedAt"], reverse=True), query)

    @staticmethod
    def save_policy_draft(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        body = p["_body"]
        require(body, "type", "name", "schema")
        if body["type"] not in ("RULES", "AWARD") or not isinstance(body["schema"], dict):
            raise ValueError("type must be RULES or AWARD and schema must be an object")
        draft_id = body.get("draftId") or new_id()
        draft = ProgrammeHandler._policy_bucket().get(draft_id)
        if draft and draft["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
            raise ValueError("only draft policy versions can be edited")
        record = {**(draft or {"id": draft_id, "programmeSlug": p["slug"], "status": "DRAFT", "reviewHistory": [], "createdAt": now()}),
                  "type": body["type"], "name": body["name"], "schema": body["schema"], "effectiveFrom": body.get("effectiveFrom"), "updatedAt": now()}
        ProgrammeHandler._policy_bucket()[draft_id] = record
        ProgrammeHandler.store.event("programme.policy-draft.saved.v1", "policy_draft", draft_id, record)
        return {**record, "_status": 201 if not draft else 200}

    @staticmethod
    def submit_policy_draft(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        draft = ProgrammeHandler._policy_bucket()[p["draftId"]]
        if draft["programmeSlug"] != p["slug"] or draft["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
            raise ValueError("only draft policies can be submitted")
        draft["status"], draft["submittedAt"], draft["updatedAt"] = "UNDER_REVIEW", now(), now()
        draft["reviewHistory"].append({"action": "SUBMITTED", "occurredAt": draft["submittedAt"]})
        return draft

    @staticmethod
    def review_policy_draft(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        body = p["_body"]
        require(body, "decision", "reviewerId")
        if body["decision"] not in ("APPROVED", "CHANGES_REQUESTED"):
            raise ValueError("decision must be APPROVED or CHANGES_REQUESTED")
        draft = ProgrammeHandler._policy_bucket()[p["draftId"]]
        if draft["programmeSlug"] != p["slug"] or draft["status"] != "UNDER_REVIEW":
            raise ValueError("only policies under review can be decided")
        draft["status"], draft["reviewedAt"], draft["updatedAt"] = body["decision"], now(), now()
        draft["reviewHistory"].append({"action": body["decision"], "reviewerId": body["reviewerId"], "note": body.get("note"), "occurredAt": draft["reviewedAt"]})
        return draft

    @staticmethod
    def publish_policy_draft(_: JsonHandler, p: dict[str, str]) -> dict[str, Any]:
        ProgrammeHandler._authorize_admin(p, p["slug"])
        body = p["_body"]
        require(body, "effectiveFrom", "publisherId")
        draft = ProgrammeHandler._policy_bucket()[p["draftId"]]
        if draft["programmeSlug"] != p["slug"] or draft["status"] != "APPROVED":
            raise ValueError("only approved policies can be published")
        programme = ProgrammeHandler.store.items[p["slug"]]
        draft["status"], draft["effectiveFrom"], draft["publishedAt"], draft["publisherId"] = "PUBLISHED", body["effectiveFrom"], now(), body["publisherId"]
        draft["updatedAt"] = now()
        draft["reviewHistory"].append({"action": "PUBLISHED", "publisherId": body["publisherId"], "effectiveFrom": body["effectiveFrom"], "occurredAt": draft["publishedAt"]})
        if draft["type"] == "RULES":
            programme["rules"] = draft["schema"].get("rules", draft["schema"])
            programme["policyVersion"] = programme.get("policyVersion", 1) + 1
        else:
            programme.setdefault("awards", []).append({**draft["schema"], "draftId": draft["id"], "effectiveFrom": draft["effectiveFrom"]})
        programme["updatedAt"] = now()
        ProgrammeHandler.store.event("programme.policy-draft.published.v1", "policy_draft", draft["id"], draft)
        return {"draft": draft, "programme": programme}

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
    ("GET", "/v1/programmes/{slug}/content"): ProgrammeHandler.list_content,
    ("GET", "/v1/programmes/{slug}/content/coverage"): ProgrammeHandler.content_coverage,
    ("POST", "/v1/programmes/{slug}/content"): ProgrammeHandler.save_content,
    ("POST", "/v1/programmes/{slug}/content/{contentId}/submit"): ProgrammeHandler.submit_content,
    ("POST", "/v1/programmes/{slug}/content/{contentId}/review"): ProgrammeHandler.review_content,
    ("POST", "/v1/programmes/{slug}/content/{contentId}/publish"): ProgrammeHandler.publish_content,
    ("GET", "/v1/programmes/{slug}/policy-drafts"): ProgrammeHandler.list_policy_drafts,
    ("POST", "/v1/programmes/{slug}/policy-drafts"): ProgrammeHandler.save_policy_draft,
    ("POST", "/v1/programmes/{slug}/policy-drafts/{draftId}/submit"): ProgrammeHandler.submit_policy_draft,
    ("POST", "/v1/programmes/{slug}/policy-drafts/{draftId}/review"): ProgrammeHandler.review_policy_draft,
    ("POST", "/v1/programmes/{slug}/policy-drafts/{draftId}/publish"): ProgrammeHandler.publish_policy_draft,
}


def seed() -> None:
    ProgrammeHandler.store.hydrate()
    if ProgrammeHandler.store.items:
        # Persistent local databases survive container rebuilds. Backfill the
        # demonstration metadata introduced by the administration workflows
        # without overwriting programme-owned data.
        if "mpota" in ProgrammeHandler.store.items:
            ProgrammeHandler.store.items["mpota"].setdefault("locales", ["en", "es"])
        if "regional-ota" in ProgrammeHandler.store.items:
            ProgrammeHandler.store.items["regional-ota"].setdefault("locales", ["en"])
        content = ProgrammeHandler._content_bucket()
        if "mpota" in ProgrammeHandler.store.items and not any(item.get("programmeSlug") == "mpota" for item in content.values()):
            content["00000000-0000-4000-8000-000000000301"] = {
                "id": "00000000-0000-4000-8000-000000000301", "programmeSlug": "mpota", "key": "programme.welcome",
                "locale": "en", "value": "Welcome to the programme", "fallbackLocale": None, "status": "PUBLISHED",
                "effectiveFrom": now(), "publishedAt": now(), "reviewHistory": [{"action": "PUBLISHED", "publisherId": "demo-admin", "occurredAt": now()}],
                "createdAt": now(), "updatedAt": now()}
            content["00000000-0000-4000-8000-000000000302"] = {
                "id": "00000000-0000-4000-8000-000000000302", "programmeSlug": "mpota", "key": "programme.welcome",
                "locale": "es", "value": "Bienvenido al programa", "fallbackLocale": "en", "status": "DRAFT",
                "reviewHistory": [], "createdAt": now(), "updatedAt": now()}
        return
    ProgrammeHandler.store.items["mpota"] = {
        "id": "00000000-0000-4000-8000-000000000101", "slug": "mpota", "name": "Municipal Parks on the Air",
        "description": "Synthetic sample configuration for a municipal-park programme; replace with programme-owner policy before production.",
        "entityTypes": [{"code": "MUNICIPAL_PARK", "label": "Municipal park", "geometry": "MULTIPOLYGON"}],
        "policyVersion": 1,
        "rules": {"minimumQsos": {"activation": 10, "hunter": 1}, "excludeOverlappingProgrammes": True,
                  "activationValidityDays": 365, "publicAccessRequired": True},
        "locales": ["en", "es"],
        "theme": {"primary": "#0f766e", "accent": "#f59e0b", "surface": "#f0fdfa"},
        "oidc": None, "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}
    ProgrammeHandler.store.items["regional-ota"] = {
        "id": "00000000-0000-4000-8000-000000000102", "slug": "regional-ota", "name": "Regional Outdoor Activation",
        "description": "Synthetic second configuration proving that the UI is not MPOTA-specific.",
        "entityTypes": [{"code": "NATURE_RESERVE", "label": "Nature reserve", "geometry": "MULTIPOLYGON"}],
        "policyVersion": 1,
        "rules": {"minimumQsos": {"activation": 5, "hunter": 1}, "excludeOverlappingProgrammes": False,
                  "activationValidityDays": 730, "publicAccessRequired": False},
        "locales": ["en"],
        "theme": {"primary": "#1d4ed8", "accent": "#fb7185", "surface": "#eff6ff"},
        "oidc": {"enabled": False}, "status": "ACTIVE", "createdAt": now(), "updatedAt": now()}
    ProgrammeHandler._content_bucket()["00000000-0000-4000-8000-000000000301"] = {
        "id": "00000000-0000-4000-8000-000000000301", "programmeSlug": "mpota", "key": "programme.welcome",
        "locale": "en", "value": "Welcome to the programme", "fallbackLocale": None, "status": "PUBLISHED",
        "effectiveFrom": now(), "publishedAt": now(), "reviewHistory": [{"action": "PUBLISHED", "publisherId": "demo-admin", "occurredAt": now()}],
        "createdAt": now(), "updatedAt": now()}
    ProgrammeHandler._content_bucket()["00000000-0000-4000-8000-000000000302"] = {
        "id": "00000000-0000-4000-8000-000000000302", "programmeSlug": "mpota", "key": "programme.welcome",
        "locale": "es", "value": "Bienvenido al programa", "fallbackLocale": "en", "status": "DRAFT",
        "reviewHistory": [], "createdAt": now(), "updatedAt": now()}


if __name__ == "__main__":
    seed()
    ThreadingHTTPServer(("0.0.0.0", 8002), ProgrammeHandler).serve_forever()
