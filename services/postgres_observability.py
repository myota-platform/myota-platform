"""Bounded, read-only PostgreSQL and PostGIS metric sampler.

Only fixed database names and catalog/statistics queries are used. The sampler
never reads application tables, query text, bind values, or geometry.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

import psycopg

from metrics import METRICS

LOG = logging.getLogger("myota.operations.postgres")
POLL_SECONDS = max(15, int(os.environ.get("OPERATIONS_PG_POLL_SECONDS", "30")))
DATABASES = (
    ("core", "OPERATIONS_PG_CORE_HOST", "myota-core-postgres", "myota_core"),
    (
        "activity",
        "OPERATIONS_PG_ACTIVITY_HOST",
        "myota-activity-postgres",
        "myota_activity",
    ),
    ("geo", "OPERATIONS_PG_GEO_HOST", "myota-geo-postgis", "myota_geo"),
)


@dataclass(frozen=True)
class DatabaseSample:
    connections: int
    max_connections: int
    database_size_bytes: int
    commits: int
    rollbacks: int
    blocks_read: int
    deadlocks: int
    postgis_version: str | None = None


def _sample(
    database: str, host_env: str, default_host: str, dbname: str
) -> DatabaseSample:
    password_name = f"MYOTA_PG_{database.upper()}_MONITOR_PASSWORD"
    password = os.environ.get(password_name)
    if not password:
        raise RuntimeError("monitor credential is not configured")
    host = os.environ.get(host_env, default_host)
    with psycopg.connect(
        host=host,
        port=5432,
        dbname=dbname,
        user="myota_observability",
        password=password,
        connect_timeout=3,
        application_name="myota-operations-db-observability",
        options="-c default_transaction_read_only=on",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT numbackends, xact_commit, xact_rollback, "
                "blks_read, deadlocks FROM pg_stat_database "
                "WHERE datname = current_database()"
            )
            stats = cursor.fetchone()
            if stats is None:
                raise RuntimeError("database statistics row is unavailable")
            cursor.execute(
                "SELECT current_setting('max_connections')::integer"
            )
            max_connections = cursor.fetchone()[0]
            cursor.execute("SELECT pg_database_size(current_database())")
            size_bytes = cursor.fetchone()[0]
            postgis_version = None
            if database == "geo":
                cursor.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'postgis'"
                )
                row = cursor.fetchone()
                postgis_version = row[0] if row else None
    return DatabaseSample(
        connections=int(stats[0]),
        commits=int(stats[1]),
        rollbacks=int(stats[2]),
        blocks_read=int(stats[3]),
        deadlocks=int(stats[4]),
        max_connections=int(max_connections),
        database_size_bytes=int(size_bytes),
        postgis_version=postgis_version,
    )


def sample_once() -> None:
    for database, host_env, default_host, dbname in DATABASES:
        labels = {"database": database}
        try:
            sample = _sample(database, host_env, default_host, dbname)
        except Exception:
            METRICS.set_gauge("myota_postgresql_up", 0, labels)
            LOG.warning(
                "PostgreSQL observability sample unavailable",
                extra={"database": database},
            )
            continue
        METRICS.set_gauge("myota_postgresql_up", 1, labels)
        METRICS.set_gauge(
            "myota_postgresql_last_sample_timestamp_seconds",
            time.time(),
            labels,
        )
        METRICS.set_gauge(
            "myota_postgresql_connections",
            sample.connections,
            labels,
        )
        METRICS.set_gauge(
            "myota_postgresql_max_connections",
            sample.max_connections,
            labels,
        )
        METRICS.set_gauge(
            "myota_postgresql_database_size_bytes",
            sample.database_size_bytes,
            labels,
        )
        for name, value in (
            ("commits", sample.commits),
            ("rollbacks", sample.rollbacks),
            ("blocks_read", sample.blocks_read),
            ("deadlocks", sample.deadlocks),
        ):
            METRICS.set_counter(
                f"myota_postgresql_{name}_total", value, labels
            )
        if database == "geo":
            postgis_labels = {"database": database}
            if sample.postgis_version:
                postgis_labels["version"] = sample.postgis_version
            METRICS.set_gauge(
                "myota_postgis_extension_present",
                1 if sample.postgis_version else 0,
                postgis_labels,
            )


def poll_postgres(stop: threading.Event) -> None:
    while not stop.is_set():
        sample_once()
        stop.wait(POLL_SECONDS)
