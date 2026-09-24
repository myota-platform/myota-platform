"""Small typed, stdlib-only client generated from the v1 contract surface.

The CI contract job can replace this module with the project's chosen OpenAPI
generator; keeping the checked-in client makes local service integration usable
without a generator runtime.
"""
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen
import json


@dataclass(frozen=True)
class ApiError(Exception):
    status: int
    body: dict[str, Any]


class MyOTAClient:
    def __init__(self, base_url: str, timeout: float = 10) -> None:
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def request(self, method: str, path: str, body: dict[str, Any] | None = None,
                idempotency_key: str | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json", "X-Request-ID": "client-generated"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with urlopen(Request(self.base_url + path, data=payload, headers=headers, method=method), timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except Exception as exc:
            if hasattr(exc, "read"):
                body_data = json.loads(exc.read() or b"{}")
                raise ApiError(exc.code, body_data) from exc
            raise
