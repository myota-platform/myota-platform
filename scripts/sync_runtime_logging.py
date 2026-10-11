#!/usr/bin/env python3
"""Copy the canonical shared logger into standalone service build contexts."""

from __future__ import annotations

import argparse
from pathlib import Path


TARGETS = (
    "myota-identity-service/myota_logging.py",
    "myota-programme-service/myota_logging.py",
    "myota-activity-service/myota_logging.py",
    "myota-geodata-service/myota_logging.py",
    "myota-operations-service/myota_logging.py",
    "myota-deploy/services/myota_logging.py",
    "myota-platform/services/myota_logging.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "workspace_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="directory containing all MyOTA repositories",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check targets without writing files",
    )
    args = parser.parse_args()
    root = args.workspace_root.resolve()
    source = root / "myota-platform/runtime/myota_logging.py"
    content = source.read_bytes()
    drift: list[str] = []
    for relative in TARGETS:
        target = root / relative
        if args.check:
            if not target.is_file() or target.read_bytes() != content:
                drift.append(relative)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"synchronized {relative}")
    if drift:
        print("shared logging mirror drift: " + ", ".join(drift))
        return 1
    if args.check:
        print(f"shared logging audit passed: {len(TARGETS)} mirrors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
