#!/usr/bin/env python3
"""Generate the compact routing catalog consumed by the deploy-owned relay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts/event-registry.json"


def runtime_catalog(registry: dict) -> dict:
    events = {
        item["eventType"]: {
            "subject": item["subject"],
            "owner": item["owner"],
            "producers": registry["producerNamesByOwner"][item["owner"]],
            "dataClassification": item.get("dataClassification"),
        }
        for item in registry["events"]
    }
    legacy_routes = {}
    target_work_routes = {}
    for work in registry["work"]:
        target_work_routes[work["workType"]] = {
            "subject": work["subject"],
            "stream": work["stream"],
            "durable": work["durable"],
            "producers": registry["producerNamesByOwner"][work["owner"]],
        }
        subject = work.get("legacySubject")
        if not subject:
            continue
        for event_type in work.get("sourceEventTypes", []):
            if event_type in legacy_routes:
                raise ValueError(f"duplicate legacy route for {event_type}")
            legacy_routes[event_type] = {
                "subject": subject,
                "workType": work["workType"],
                "producers": registry["producerNamesByOwner"][work["owner"]],
            }
    return {
        "registryVersion": registry["registryVersion"],
        "events": events,
        "legacyWorkRoutes": legacy_routes,
        "targetWorkRoutes": target_work_routes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy-root", type=Path, required=True)
    parser.add_argument("--platform-root", type=Path)
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    content = json.dumps(runtime_catalog(registry), indent=2) + "\n"
    destinations = [args.deploy_root / "services" / "event_registry.json"]
    if args.platform_root:
        destinations.append(
            args.platform_root / "services" / "event_registry.json"
        )
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        print(f"generated {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
