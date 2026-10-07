from __future__ import annotations

import mimetypes
import os
import sys
import threading
import http.client
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from activity import ActivityHandler
from geodata import GeoHandler
from identity import IdentityHandler, bootstrap_admin, seed as seed_identity
from programmes import ProgrammeHandler, seed as seed_programmes
from operations import OperationsHandler
from metrics import METRICS
from otel import telemetry_for


ROOT = Path(__file__).resolve().parent.parent
SERVICES = {
    "/v1/identity/": ("identity", 8001, IdentityHandler),
    "/v1/entity-types": ("programmes", 8002, ProgrammeHandler),
    "/v1/programmes": ("programmes", 8002, ProgrammeHandler),
    "/v1/geodata/": ("geodata", 8003, GeoHandler),
    "/v1/operations/": ("operations", 8005, OperationsHandler),
    "/v1/activations": ("activity", 8004, ActivityHandler),
    "/v1/awards": ("activity", 8004, ActivityHandler),
    "/v1/qso-ingestions": ("activity", 8004, ActivityHandler),
    "/v1/adif/": ("activity", 8004, ActivityHandler),
    "/v1/qsos": ("activity", 8004, ActivityHandler),
    "/v1/statistics": ("activity", 8004, ActivityHandler),
    "/v1/public/": ("activity", 8004, ActivityHandler),
    "/v1/notifications": ("activity", 8004, ActivityHandler),
}


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_OPTIONS(self) -> None:
        self._begin_request()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, Idempotency-Key, If-Match, X-Request-ID, X-Correlation-ID",
        )
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        )
        self.end_headers()

    def do_GET(self) -> None:
        self._begin_request()
        if self.path.split("?", 1)[0] == "/metrics":
            body = METRICS.render().encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/healthz":
            self._json(200, b'{"status":"ok","service":"gateway"}')
            return
        if self.path == "/" or self.path.startswith("/assets/"):
            self._static()
            return
        self._proxy()

    def do_POST(self) -> None:
        self._begin_request()
        self._proxy()

    def do_PUT(self) -> None:
        self._begin_request()
        self._proxy()

    def do_PATCH(self) -> None:
        self._begin_request()
        self._proxy()

    def do_DELETE(self) -> None:
        self._begin_request()
        self._proxy()

    def _static(self) -> None:
        relative = (
            "index.html"
            if self.path == "/"
            else self.path.removeprefix("/assets/")
        )
        path = ROOT / "web" / relative
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", mimetypes.guess_type(str(path))[0] or "text/plain"
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self) -> None:
        target = next(
            (
                (name, port, handler)
                for prefix, (name, port, handler) in SERVICES.items()
                if self.path.startswith(prefix)
            ),
            None,
        )
        if not target:
            self._json(404, b'{"error":"route_not_found"}')
            return
        name, port, _ = target
        base_url = os.environ.get(
            f"MYOTA_{name.upper()}_URL", f"http://127.0.0.1:{port}"
        )
        headers = {
            "Content-Type": self.headers.get(
                "Content-Type", "application/json"
            ),
            "Authorization": self.headers.get("Authorization", ""),
            "Idempotency-Key": self.headers.get("Idempotency-Key", ""),
            "X-Request-ID": self.headers.get("X-Request-ID", ""),
            "X-Correlation-ID": self.headers.get("X-Correlation-ID", ""),
        }
        try:
            if self.command == "POST":
                # Stream large multipart bodies through the development gateway
                # instead of materializing a second 1 GB copy in its process.
                parsed = urlsplit(base_url)
                connection_type = (
                    http.client.HTTPSConnection
                    if parsed.scheme == "https"
                    else http.client.HTTPConnection
                )
                connection = connection_type(
                    parsed.netloc,
                    timeout=float(
                        os.environ.get(
                            "MYOTA_PROXY_UPLOAD_TIMEOUT_SECONDS", "3600"
                        )
                    ),
                )
                connection.putrequest(
                    self.command, f"{parsed.path.rstrip('/')}{self.path}"
                )
                for key, value in headers.items():
                    if value:
                        connection.putheader(key, value)
                length = int(self.headers.get("Content-Length", "0"))
                connection.putheader("Content-Length", str(length))
                connection.endheaders()
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(8 * 1024 * 1024, remaining))
                    if not chunk:
                        raise ConnectionError(
                            "client upload ended before Content-Length"
                        )
                    connection.send(chunk)
                    remaining -= len(chunk)
                response = connection.getresponse()
                self._json(
                    response.status, response.read(), response.getheaders()
                )
                connection.close()
            else:
                body = (
                    self.rfile.read(
                        int(self.headers.get("Content-Length", "0"))
                    )
                    if self.command in {"PUT", "PATCH", "DELETE"}
                    else None
                )
                request = urllib.request.Request(
                    f"{base_url}{self.path}",
                    data=body,
                    method=self.command,
                    headers=headers,
                )
                with urllib.request.urlopen(
                    request,
                    timeout=float(
                        os.environ.get("MYOTA_PROXY_TIMEOUT_SECONDS", "60")
                    ),
                ) as response:
                    self._json(
                        response.status,
                        response.read(),
                        response.headers.items(),
                    )
        except urllib.error.HTTPError as exc:
            self._json(exc.code, exc.read(), exc.headers.items())
        except Exception as exc:
            self._json(
                503,
                (
                    '{"error":"service_unavailable","message":"%s"}' % str(exc)
                ).encode(),
            )

    def _json(
        self, status: int, data: bytes, upstream_headers: object = ()
    ) -> None:
        METRICS.inc(
            "myota_gateway_requests_total",
            {
                "method": self.command,
                "route": self.path.split("?", 1)[0],
                "status": status,
            },
        )
        request_telemetry = getattr(self, "_otel_request", None)
        if request_telemetry:
            request_telemetry.finish(status, self.path.split("?", 1)[0])
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, Idempotency-Key, X-Request-ID, X-Correlation-ID",
        )
        if hasattr(upstream_headers, "__iter__"):
            for name, value in upstream_headers:
                if name.lower() in {
                    "deprecation",
                    "sunset",
                    "api-version",
                    "etag",
                }:
                    self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _begin_request(self) -> None:
        self._otel_request = telemetry_for("myota-gateway").start_request(
            self.command, self.path.split("?", 1)[0]
        )


def start(port: int, handler: type[BaseHTTPRequestHandler]) -> None:
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


def main() -> None:
    seed_identity()
    bootstrap_admin()
    seed_programmes()
    for port, handler in (
        (8001, IdentityHandler),
        (8002, ProgrammeHandler),
        (8003, GeoHandler),
        (8004, ActivityHandler),
    ):
        threading.Thread(
            target=start, args=(port, handler), daemon=True
        ).start()
    print("MyOTA dev gateway: http://127.0.0.1:8080")
    # Bind all interfaces in containers; this is also safe for local development
    # because the gateway is intended to be the only exposed process.
    ThreadingHTTPServer(
        (os.environ.get("MYOTA_BIND_HOST", "0.0.0.0"), 8080), GatewayHandler
    ).serve_forever()


if __name__ == "__main__":
    main()
