#!/usr/bin/env python3
"""Audit registered event sources against the authoritative service workspace.

The event registry is owned by myota-contracts. Producer implementations stay
in their service repositories; this workspace audit verifies the registry's
source references and catches event-like literals that have no disposition.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts/event-registry.json"
OWNER_REPOSITORIES = {
    "identity-service": "myota-identity-service",
    "programme-service": "myota-programme-service",
    "activity-service": "myota-activity-service",
    "geodata-service": "myota-geodata-service",
    "operations-service": "myota-operations-service",
}
EVENT_TYPE = re.compile(
    r"^(?:identity|programme|activity|awards|geodata)\."
    r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.v[1-9][0-9]*$"
)


def python_files(repository: Path):
    for path in repository.rglob("*.py"):
        if "tests" not in path.parts and "__pycache__" not in path.parts:
            yield path


@lru_cache(maxsize=None)
def literal_strings(path: Path) -> frozenset[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return frozenset()
    return frozenset(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace-root",
        type=Path,
        required=True,
        help="directory containing the authoritative service checkouts",
    )
    args = parser.parse_args()
    workspace = args.workspace_root.resolve()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    facts = registry["events"]
    work_source_types = {work["workType"] for work in registry["work"]}
    work_source_types.update(
        event_type
        for work in registry["work"]
        for event_type in work.get("sourceEventTypes", [])
    )
    registered = {event["eventType"] for event in facts}
    discovered: set[str] = set()
    errors: list[str] = []

    for event in facts:
        owner = event["owner"]
        expected_repository = OWNER_REPOSITORIES.get(owner)
        sources = event.get("producerSources", [])
        if not expected_repository or not sources:
            errors.append(
                f"{event['eventType']}: missing owner or producerSources"
            )
            continue
        if len(sources) != len(set(sources)):
            errors.append(f"{event['eventType']}: duplicate producerSources")
        matched = False
        for source in sources:
            repository_name, separator, relative_path = source.partition("/")
            if not separator or repository_name != expected_repository:
                errors.append(
                    f"{event['eventType']}: source {source!r} does not match owner {owner}"
                )
                continue
            path = workspace / repository_name / relative_path
            if not path.is_file() or event["eventType"] not in literal_strings(
                path
            ):
                errors.append(
                    f"{event['eventType']}: source literal not found in {source}"
                )
                continue
            matched = True
        if not matched:
            errors.append(f"{event['eventType']}: no verified producer source")

    for owner, repository_name in OWNER_REPOSITORIES.items():
        repository = workspace / repository_name
        if not repository.is_dir():
            errors.append(
                f"missing authoritative repository {repository_name}"
            )
            continue
        for path in python_files(repository):
            for value in literal_strings(path):
                if EVENT_TYPE.fullmatch(value):
                    discovered.add(value)

    undispositioned = discovered - registered - work_source_types
    if undispositioned:
        errors.append(
            "event-like source literals have no registry/work disposition: "
            + ", ".join(sorted(undispositioned))
        )

    if errors:
        print("Event source audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        f"verified {len(facts)} registered fact types across "
        f"{len(OWNER_REPOSITORIES)} authoritative repositories; "
        f"{len(work_source_types)} legacy work source types have registry dispositions; "
        "no undispositioned event-like source literals found"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
