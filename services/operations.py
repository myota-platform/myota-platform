"""Authenticated, read-only broker inspection with durable sampled history."""

from __future__ import annotations

import asyncio
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
from jetstream_observability import _value, collect_stream_metrics
from metrics import METRICS
from storage_observability import storage_snapshot

LOG = logging.getLogger("myota.operations")
POLL_SECONDS = max(10, int(os.environ.get("OPERATIONS_POLL_SECONDS", "30")))
HISTORY_DAYS = max(1, int(os.environ.get("OPERATIONS_HISTORY_DAYS", "7")))
SNAPSHOT_TABLES = {
    "jetstream": "operations_jetstream_snapshot",
    "object-storage": "operations_storage_snapshot",
}


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


async def broker_snapshot(nc: Any) -> dict[str, Any]:
    js = nc.jetstream()
    infos = await js.streams_info()
    maximum = max(1, int(os.environ.get("OPERATIONS_MAX_STREAMS", "20")))
    streams, errors = [], []
    for info in infos[:maximum]:
        name = str(_value(_value(info, "config", {}), "name", "unknown"))
        state = _value(info, "state", {})
        config = _value(info, "config", {})
        stream = {
            "name": name,
            "subjects": _value(config, "subjects", []),
            "messages": int(_value(state, "messages", 0)),
            "bytes": int(_value(state, "bytes", 0)),
            "firstSequence": int(_value(state, "first_seq", 0)),
            "lastSequence": int(_value(state, "last_seq", 0)),
            "storage": str(
                getattr(
                    _value(config, "storage", ""),
                    "value",
                    _value(config, "storage", ""),
                )
            ),
            "retention": str(
                getattr(
                    _value(config, "retention", ""),
                    "value",
                    _value(config, "retention", ""),
                )
            ),
            "consumerCount": int(_value(state, "consumer_count", 0)),
            "consumers": [],
        }
        try:
            consumers = await js.consumers_info(name)
            metrics = await collect_stream_metrics(js, nc, name)
            limit = max(
                1,
                int(
                    os.environ.get(
                        "MYOTA_JETSTREAM_METRICS_MAX_CONSUMERS", "100"
                    )
                ),
            )
            stream["consumersTruncated"] = len(consumers) > limit
            for consumer in consumers[:limit]:
                consumer_name = str(_value(consumer, "name", "unknown"))
                consumer_config = _value(consumer, "config", {})
                ack = _value(consumer, "ack_floor", {})
                delivered = _value(consumer, "delivered", {})
                age_available = (
                    metrics.get(
                        (
                            "myota_jetstream_consumer_oldest_message_age_available",
                            name,
                            consumer_name,
                        )
                    )
                    == 1
                )
                stream["consumers"].append(
                    {
                        "name": consumer_name,
                        "durable": _value(
                            consumer_config, "durable_name", None
                        ),
                        "filterSubjects": _value(
                            consumer_config, "filter_subjects", None
                        )
                        or [_value(consumer_config, "filter_subject", ">")],
                        "pending": int(_value(consumer, "num_pending", 0)),
                        "ackPending": int(
                            _value(consumer, "num_ack_pending", 0)
                        ),
                        "redelivered": int(
                            _value(consumer, "num_redelivered", 0)
                        ),
                        "waiting": int(_value(consumer, "num_waiting", 0)),
                        "ackPolicy": str(
                            getattr(
                                _value(consumer_config, "ack_policy", ""),
                                "value",
                                _value(consumer_config, "ack_policy", ""),
                            )
                        ),
                        "ackWaitSeconds": _value(
                            consumer_config, "ack_wait", 0
                        ),
                        "maxAckPending": _value(
                            consumer_config, "max_ack_pending", 0
                        ),
                        "maxDeliver": _value(
                            consumer_config, "max_deliver", 0
                        ),
                        "deliveredSequence": int(
                            _value(delivered, "stream_seq", 0)
                        ),
                        "ackFloorSequence": int(_value(ack, "stream_seq", 0)),
                        "oldestMessageAgeSeconds": metrics.get(
                            (
                                "myota_jetstream_consumer_oldest_message_age_seconds",
                                name,
                                consumer_name,
                            )
                        )
                        if age_available
                        else None,
                    }
                )
        except Exception:
            errors.append(f"Consumer metadata unavailable for {name}")
        streams.append(stream)
    return {
        "status": "PARTIAL"
        if errors
        or len(infos) > maximum
        or any(item.get("consumersTruncated") for item in streams)
        else "HEALTHY",
        "streams": streams,
        "streamsTruncated": len(infos) > maximum,
        "errors": errors,
        "pollSeconds": POLL_SECONDS,
        "historyRetentionDays": HISTORY_DAYS,
        "sampledAt": datetime.now(timezone.utc).isoformat(),
    }


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
    def latest(_, params):
        return OperationsHandler.latest_sample("jetstream", params)

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
    def history(_, params):
        return OperationsHandler.history_samples("jetstream", params)

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
    ("GET", "/v1/operations/jetstream"): OperationsHandler.latest,
    ("GET", "/v1/operations/jetstream/snapshots"): OperationsHandler.history,
}


def record_snapshot(snapshot: dict[str, Any], kind: str = "jetstream") -> None:
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


async def poll_broker(stop: threading.Event) -> None:
    from nats.aio.client import Client as NATS

    while not stop.is_set():
        nc = NATS()
        try:
            await nc.connect(
                os.environ.get("NATS_URL", "nats://nats:4222"),
                name="myota-operations-readonly",
                connect_timeout=3,
                max_reconnect_attempts=0,
            )
            snapshot = await asyncio.wait_for(broker_snapshot(nc), timeout=20)
        except Exception:
            LOG.warning("Broker inspection failed", exc_info=True)
            snapshot = {
                "status": "UNAVAILABLE",
                "streams": [],
                "errors": [
                    "Broker inspection unavailable; see operations logs"
                ],
                "pollSeconds": POLL_SECONDS,
                "historyRetentionDays": HISTORY_DAYS,
            }
        finally:
            if nc.is_connected:
                await nc.close()
        try:
            await asyncio.to_thread(record_snapshot, snapshot)
        except Exception:
            LOG.exception("Unable to persist broker status history")
        await asyncio.to_thread(stop.wait, POLL_SECONDS)


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
    worker = threading.Thread(
        target=lambda: asyncio.run(poll_broker(stop)),
        name="operations-sampler",
        daemon=True,
    )
    worker.start()
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
        worker.join(timeout=25)
        storage_worker.join(timeout=15)
        OperationsHandler.store.close()


if __name__ == "__main__":
    main()
