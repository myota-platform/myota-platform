#!/usr/bin/env python3
"""Record the current digest behind each production :latest image tag."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "deploy/helm/myota/values-image-digests.yaml"
IMAGES = {
    "identity": "ghcr.io/myota-platform/myota-identity-service:latest",
    "programmes": "ghcr.io/myota-platform/myota-programme-service:latest",
    "geodata": "ghcr.io/myota-platform/myota-geodata-service:latest",
    "activity": "ghcr.io/myota-platform/myota-activity-service:latest",
    "gateway": "ghcr.io/myota-platform/myota-gateway:latest",
    "adminWeb": "ghcr.io/myota-platform/myota-admin-web:latest",
    "platform": "ghcr.io/myota-platform/myota-service:latest",
}


def main() -> None:
    contents = VALUES.read_text(encoding="utf-8")
    for key, image in IMAGES.items():
        digest = subprocess.check_output(
            ["crane", "digest", image], text=True, stderr=subprocess.STDOUT
        ).strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise SystemExit(
                f"Unexpected digest returned for {image}: {digest!r}"
            )
        pattern = re.compile(rf"(?m)^(    {re.escape(key)}:\s*)\"[^\"]*\"$")
        contents, count = pattern.subn(rf'\g<1>"{digest}"', contents)
        if count != 1:
            raise SystemExit(
                f"Expected exactly one imageRollout.digests.{key} entry; found {count}"
            )
        print(f"{key}: {digest}")
    VALUES.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()
