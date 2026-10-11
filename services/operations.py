"""Authenticated Grafana identity and bounded database telemetry."""

from __future__ import annotations

from myota_logging import configure_logging, inject_trace_context

import json
import logging
import os
import threading
import unicodedata
import urllib.error
import urllib.request
from typing import Any

from common import (
    BoundedThreadingHTTPServer,
    JsonHandler,
    Store,
    verify_token,
)
from postgres_observability import poll_postgres

LOG = logging.getLogger("myota.operations")


def grafana_identity(account: dict[str, Any]) -> dict[str, str]:
    roles = {
        role.get("role") if isinstance(role, dict) else role
        for role in account.get("roles") or []
    }
    granted = set(account.get("scopes") or [])
    if not roles.intersection({"GLOBAL_OPERATOR", "GLOBAL_ADMIN"}) and not (
        granted.intersection({"*", "observability.view", "operations.read"})
    ):
        raise PermissionError("Platform observability permission is required")
    return {
        "username": "myota:" + account["id"],
        "displayName": account.get("displayName") or account["id"],
        "email": account.get("email") or "",
        "role": "Editor"
        if roles.intersection({"GLOBAL_OPERATOR", "GLOBAL_ADMIN"})
        else "Viewer",
    }


def current_identity(params: dict[str, Any]) -> dict[str, Any]:
    authorize(params)
    identity_url = os.environ.get("MYOTA_IDENTITY_URL", "http://identity:8001")
    headers = {"Authorization": params["Authorization"]}
    inject_trace_context(headers)
    request = urllib.request.Request(
        identity_url.rstrip("/") + "/v1/identity/me",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise PermissionError(
                "Administrator session is no longer valid"
            ) from None
        raise RuntimeError("Identity service unavailable") from None
    except (OSError, ValueError):
        raise RuntimeError("Identity service unavailable") from None


def authorize(params: dict[str, Any]) -> None:
    authorization = params.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise PermissionError("Sign in as a platform administrator")
    claims = verify_token(authorization[7:], "access")
    roles = claims.get("roles") or []
    global_admin = any(
        (role.get("role") if isinstance(role, dict) else role)
        in {"GLOBAL_OPERATOR", "GLOBAL_ADMIN"}
        for role in roles
    )
    if not global_admin and not set(claims.get("scp") or []).intersection(
        {"*", "observability.view", "operations.read"}
    ):
        raise PermissionError("Platform observability permission is required")


class OperationsStore(Store):
    def _ensure_pool(self):
        if self._pool is None:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                self.dsn,
                min_size=1,
                max_size=4,
                timeout=5,
                kwargs={"connect_timeout": 5},
            )
        return self._pool


class OperationsHandler(JsonHandler):
    service = "operations-service"
    store = OperationsStore("operations", "CORE_DATABASE_URL")

    def _send(self, status, payload):
        self._grafana_headers = {}
        if status == 200 and getattr(self, "current_route", None) == (
            "GET",
            "/v1/operations/observability-session",
        ):
            for field, suffix in (
                ("username", "User"),
                ("displayName", "Name"),
                ("email", "Email"),
                ("role", "Role"),
            ):
                value = (
                    str(payload[field]).replace("\r", " ").replace("\n", " ")
                )
                self._grafana_headers["X-MyOTA-Grafana-" + suffix] = (
                    unicodedata.normalize("NFKD", value)
                    .encode("ascii", "ignore")
                    .decode()
                )
        super()._send(status, payload)

    def end_headers(self):
        for name, value in getattr(self, "_grafana_headers", {}).items():
            self.send_header(name, value)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    @staticmethod
    def observability_session(_, params):
        return grafana_identity(current_identity(params))


OperationsHandler.routes = {
    (
        "GET",
        "/v1/operations/observability-session",
    ): OperationsHandler.observability_session,
}


def main():
    if not OperationsHandler.store.durable:
        raise RuntimeError("CORE_DATABASE_URL is required")
    configure_logging("myota-operations", component="api-and-sampler")
    stop = threading.Event()
    postgres_worker = threading.Thread(
        target=poll_postgres,
        args=(stop,),
        name="postgres-sampler",
        daemon=True,
    )
    postgres_worker.start()
    try:
        BoundedThreadingHTTPServer(
            ("0.0.0.0", 8005), OperationsHandler
        ).serve_forever()
    finally:
        stop.set()
        postgres_worker.join(timeout=15)
        OperationsHandler.store.close()


if __name__ == "__main__":
    main()
