"""Authenticated operational visibility with durable storage history."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from common import (
    BoundedThreadingHTTPServer,
    JsonHandler,
    Store,
    json_default,
    verify_token,
)
from metrics import METRICS
from storage_observability import storage_snapshot

LOG = logging.getLogger("myota.operations")
POLL_SECONDS = max(10, int(os.environ.get("OPERATIONS_POLL_SECONDS", "30")))
HISTORY_DAYS = max(1, int(os.environ.get("OPERATIONS_HISTORY_DAYS", "7")))
SNAPSHOT_TABLES = {"object-storage": "operations_storage_snapshot"}


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
    request = urllib.request.Request(
        identity_url.rstrip("/") + "/v1/identity/me",
        headers={"Authorization": params["Authorization"]},
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

    @staticmethod
    def storage_latest(_, params):
        return OperationsHandler.latest_sample("object-storage", params)

    @staticmethod
    def latest_sample(kind, params):
        authorize(params)
        table = SNAPSHOT_TABLES[kind]
        with OperationsHandler.store.transaction() as connection:
            row = connection.execute(
                f"SELECT id,captured_at,payload FROM {table} "
                "ORDER BY captured_at DESC,id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {
                "_status": 503,
                "status": "UNAVAILABLE",
                "streams": [],
                "errors": ["No operational sample has been recorded yet"],
            }
        return {
            **row[2],
            "id": str(row[0]),
            "capturedAt": row[1],
            "stale": (datetime.now(timezone.utc) - row[1]).total_seconds()
            > POLL_SECONDS * 3,
        }

    @staticmethod
    def storage_history(_, params):
        return OperationsHandler.history_samples("object-storage", params)

    @staticmethod
    def history_samples(kind, params):
        authorize(params)
        table = SNAPSHOT_TABLES[kind]
        query = parse_qs(urlparse(params.get("_path", "")).query)
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
            size = max(1, min(50, int(query.get("pageSize", ["20"])[0])))
        except ValueError as error:
            raise ValueError("page and pageSize must be integers") from error
        with OperationsHandler.store.transaction() as connection:
            total = connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT id,captured_at,payload FROM {table} "
                "ORDER BY captured_at DESC,id DESC LIMIT %s OFFSET %s",
                (size, (page - 1) * size),
            ).fetchall()
        return {
            "items": [
                {**row[2], "id": str(row[0]), "capturedAt": row[1]}
                for row in rows
            ],
            "total": total,
            "page": page,
            "pageSize": size,
            "nextPage": page + 1 if page * size < total else None,
        }


OperationsHandler.routes = {
    (
        "GET",
        "/v1/operations/observability-session",
    ): OperationsHandler.observability_session,
    ("GET", "/v1/operations/object-storage"): OperationsHandler.storage_latest,
    (
        "GET",
        "/v1/operations/object-storage/snapshots",
    ): OperationsHandler.storage_history,
}


def record_snapshot(
    snapshot: dict[str, Any], kind: str = "object-storage"
) -> None:
    table = SNAPSHOT_TABLES[kind]
    with OperationsHandler.store.transaction() as connection:
        connection.execute(
            f"INSERT INTO {table}(capture_slot,status,payload) "
            "VALUES (%s,%s,%s::jsonb) ON CONFLICT (capture_slot) DO NOTHING",
            (
                int(time.time() // POLL_SECONDS),
                snapshot["status"],
                json.dumps(snapshot, default=json_default),
            ),
        )
        connection.execute(
            f"DELETE FROM {table} WHERE captured_at < "
            "now() - make_interval(days => %s)",
            (HISTORY_DAYS,),
        )
    METRICS.set_gauge(
        f"myota_operations_{kind.replace('-', '_')}_up",
        snapshot["status"] == "HEALTHY",
    )
    METRICS.set_gauge(
        f"myota_operations_{kind.replace('-', '_')}_last_sample_timestamp_seconds",
        time.time(),
    )


def poll_storage(stop: threading.Event) -> None:
    while not stop.is_set():
        snapshot = {
            **storage_snapshot(),
            "pollSeconds": POLL_SECONDS,
            "historyRetentionDays": HISTORY_DAYS,
        }
        try:
            record_snapshot(snapshot, "object-storage")
        except Exception:
            LOG.exception("Unable to persist storage status history")
        stop.wait(POLL_SECONDS)


def main():
    if not OperationsHandler.store.durable:
        raise RuntimeError("CORE_DATABASE_URL is required")
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    storage_worker = threading.Thread(
        target=poll_storage, args=(stop,), name="storage-sampler", daemon=True
    )
    storage_worker.start()
    try:
        BoundedThreadingHTTPServer(
            ("0.0.0.0", 8005), OperationsHandler
        ).serve_forever()
    finally:
        stop.set()
        storage_worker.join(timeout=15)
        OperationsHandler.store.close()


if __name__ == "__main__":
    main()
