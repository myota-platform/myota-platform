"""Inspect and explicitly redrive database-owned outbox dead letters."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from uuid import UUID

import psycopg


DATABASE_URL = os.environ.get("OUTBOX_DATABASE_URL")


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("OUTBOX_DATABASE_URL is required")
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def list_dead_letters(limit: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT event_id, event_type, attempts, error, dead_lettered_at,
                      resolved_at
                 FROM dead_letter_event
                ORDER BY dead_lettered_at DESC, event_id
                LIMIT %s""",
            (limit,),
        ).fetchall()
    return [
        {
            "eventId": str(row[0]),
            "eventType": row[1],
            "attempts": row[2],
            "error": (row[3] or "")[:500],
            "deadLetteredAt": row[4].isoformat(),
            "resolvedAt": row[5].isoformat() if row[5] else None,
        }
        for row in rows
    ]


def redrive(event_id: str, actor: str, reason: str) -> dict[str, Any]:
    try:
        normalized_id = str(UUID(event_id))
    except ValueError as exc:
        raise ValueError("event-id must be a UUID") from exc
    actor = actor.strip()
    reason = reason.strip()
    if not actor or len(actor) > 120:
        raise ValueError("actor must contain 1 to 120 characters")
    if not reason or len(reason) > 500:
        raise ValueError("reason must contain 1 to 500 characters")

    with _connect() as connection:
        row = connection.execute(
            """SELECT e.event_type, e.attempts, d.error, e.published_at
                 FROM outbox_event AS e
                 JOIN dead_letter_event AS d USING (event_id)
                WHERE e.event_id = %s AND d.resolved_at IS NULL
                FOR UPDATE OF e, d""",
            (normalized_id,),
        ).fetchone()
        if row is None:
            raise ValueError(
                "no unresolved dead letter with a retained outbox row was found"
            )
        if row[1] is None or row[3] is None:
            raise ValueError(
                "dead-letter source outbox row is not in a completed state"
            )
        connection.execute(
            """INSERT INTO outbox_redrive_audit(
                   event_id, actor, reason, previous_attempts, previous_error
               ) VALUES (%s, %s, %s, %s, %s)""",
            (normalized_id, actor, reason, row[1], row[2]),
        )
        connection.execute(
            """UPDATE outbox_event
                  SET published_at = NULL, available_at = now(), attempts = 0,
                      last_error = NULL
                WHERE event_id = %s""",
            (normalized_id,),
        )
    return {"eventId": normalized_id, "eventType": row[0], "actor": actor}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    listing = subparsers.add_parser(
        "list", help="list redacted dead-letter metadata"
    )
    listing.add_argument("--limit", type=int, default=100)
    replay = subparsers.add_parser(
        "redrive", help="requeue a retained event from its owning database"
    )
    replay.add_argument("event_id")
    replay.add_argument("--actor", required=True)
    replay.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            if not 1 <= args.limit <= 1000:
                raise ValueError("limit must be between 1 and 1000")
            result = list_dead_letters(args.limit)
        else:
            result = redrive(args.event_id, args.actor, args.reason)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        print(f"outbox admin failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
