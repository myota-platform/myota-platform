"""Bounded, read-only SeaweedFS exporter and S3 health inspection."""

from __future__ import annotations

import logging
import math
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

from prometheus_client.parser import text_string_to_metric_families

LOG = logging.getLogger("myota.operations.storage")
BUCKET_METRICS = {
    "SeaweedFS_s3_bucket_object_count": "objects",
    "SeaweedFS_s3_bucket_size_bytes": "logicalBytes",
    "SeaweedFS_s3_bucket_physical_size_bytes": "physicalBytes",
    "SeaweedFS_s3_bucket_read_only": "readOnly",
}
RESOURCE_TYPES = {
    "all": "totalBytes",
    "used": "usedBytes",
    "avail": "availableBytes",
}


def parse_storage_metrics(text: str, maximum: int = 100) -> dict[str, Any]:
    buckets: dict[str, dict] = {}
    volumes: dict[str, dict] = {}
    requests: dict[tuple[str, str], float] = {}
    active_uploads, active_bytes, version = None, None, None
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if not math.isfinite(sample.value):
                continue
            name, labels, value = sample.name, sample.labels, sample.value
            if name in BUCKET_METRICS and labels.get("bucket"):
                bucket = buckets.setdefault(
                    labels["bucket"],
                    {
                        "name": labels["bucket"],
                        "objects": None,
                        "logicalBytes": None,
                        "physicalBytes": None,
                        "readOnly": None,
                    },
                )
                field = BUCKET_METRICS[name]
                bucket[field] = bool(value) if field == "readOnly" else value
            elif name == "SeaweedFS_volumeServer_resource":
                field = RESOURCE_TYPES.get(labels.get("type", ""))
                if field:
                    volume = volumes.setdefault(
                        labels.get("name", "unknown"),
                        {
                            "name": labels.get("name", "unknown"),
                            "totalBytes": None,
                            "usedBytes": None,
                            "availableBytes": None,
                        },
                    )
                    volume[field] = value
            elif name == "SeaweedFS_s3_request_total":
                key = (labels.get("type", "unknown"), labels.get("code", ""))
                requests[key] = requests.get(key, 0) + value
            elif name == "SeaweedFS_s3_in_flight_upload_count":
                active_uploads = (active_uploads or 0) + value
            elif name == "SeaweedFS_s3_in_flight_upload_bytes":
                active_bytes = (active_bytes or 0) + value
            elif name == "SeaweedFS_build_info":
                version = labels.get("version")
    listed = [buckets[name] for name in sorted(buckets)[:maximum]]

    def total(field: str) -> float | None:
        values = [item[field] for item in listed]
        return (
            sum(values)
            if values and all(value is not None for value in values)
            else None
        )

    return {
        "version": version,
        "buckets": listed,
        "bucketsTruncated": len(buckets) > maximum,
        "volumes": [volumes[name] for name in sorted(volumes)],
        "requests": [
            {"operation": key[0], "code": key[1], "count": count}
            for key, count in sorted(requests.items())
        ],
        "summary": {
            "reportedBuckets": len(listed),
            "objects": total("objects"),
            "logicalBytes": total("logicalBytes"),
            "physicalBytes": total("physicalBytes"),
            "activeUploads": active_uploads,
            "activeUploadBytes": active_bytes,
        },
    }


def storage_snapshot() -> dict[str, Any]:
    result = parse_storage_metrics("")
    errors = []
    s3_healthy, metrics_healthy = False, False
    health_url = os.environ.get(
        "OPERATIONS_STORAGE_HEALTH_URL", "http://seaweedfs:8333/status"
    )
    metrics_url = os.environ.get(
        "OPERATIONS_STORAGE_METRICS_URL", "http://seaweedfs:9324/metrics"
    )
    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            s3_healthy = response.status == 200
        if not s3_healthy:
            errors.append("S3 health endpoint is not healthy")
    except Exception as error:
        LOG.warning("S3 health probe failed (%s)", type(error).__name__)
        errors.append("S3 health endpoint unavailable")
    try:
        limit = 2 * 1024 * 1024
        with urllib.request.urlopen(metrics_url, timeout=5) as response:
            content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Exporter response exceeds inspection limit")
        maximum = max(1, int(os.environ.get("OPERATIONS_MAX_BUCKETS", "100")))
        result = parse_storage_metrics(content.decode("utf-8"), maximum)
        metrics_healthy = bool(result["version"])
        if not metrics_healthy:
            errors.append("SeaweedFS build metric missing from exporter")
        if result["bucketsTruncated"]:
            errors.append("Bucket inspection limit reached")
    except Exception as error:
        LOG.warning(
            "Storage metrics inspection failed (%s)", type(error).__name__
        )
        errors.append("Storage exporter unavailable or response invalid")
    return {
        **result,
        "status": "HEALTHY"
        if s3_healthy and metrics_healthy and not errors
        else "PARTIAL"
        if s3_healthy or metrics_healthy
        else "UNAVAILABLE",
        "s3Healthy": s3_healthy,
        "metricsHealthy": metrics_healthy,
        "errors": errors,
        "sampledAt": datetime.now(timezone.utc).isoformat(),
    }
