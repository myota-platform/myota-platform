from __future__ import annotations

import mimetypes
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from activity import ActivityHandler
from geodata import GeoHandler
from identity import IdentityHandler, seed as seed_identity
from programmes import ProgrammeHandler, seed as seed_programmes
from geodata import seed as seed_geodata


ROOT = Path(__file__).resolve().parent.parent
SERVICES = {
    "/v1/identity/": ("identity", 8001, IdentityHandler),
    "/v1/programmes": ("programmes", 8002, ProgrammeHandler),
    "/v1/geodata/": ("geodata", 8003, GeoHandler),
    "/v1/activations": ("activity", 8004, ActivityHandler),
}


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Idempotency-Key")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/assets/"):
            self._static()
            return
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def _static(self) -> None:
        relative = "index.html" if self.path == "/" else self.path.removeprefix("/assets/")
        path = ROOT / "web" / relative
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self) -> None:
        target = next(((name, port, handler) for prefix, (name, port, handler) in SERVICES.items() if self.path.startswith(prefix)), None)
        if not target:
            self._json(404, b'{"error":"route_not_found"}')
            return
        name, port, _ = target
        base_url = os.environ.get(f"MYOTA_{name.upper()}_URL", f"http://127.0.0.1:{port}")
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))) if self.command == "POST" else None
        request = urllib.request.Request(f"{base_url}{self.path}", data=body, method=self.command,
                                         headers={"Content-Type": self.headers.get("Content-Type", "application/json"),
                                                  "Idempotency-Key": self.headers.get("Idempotency-Key", "")})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                self._json(response.status, response.read())
        except urllib.error.HTTPError as exc:
            self._json(exc.code, exc.read())
        except Exception as exc:
            self._json(503, ('{"error":"service_unavailable","message":"%s"}' % str(exc)).encode())

    def _json(self, status: int, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


def start(port: int, handler: type[BaseHTTPRequestHandler]) -> None:
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


def main() -> None:
    seed_identity()
    seed_programmes()
    seed_geodata()
    for port, handler in ((8001, IdentityHandler), (8002, ProgrammeHandler), (8003, GeoHandler), (8004, ActivityHandler)):
        threading.Thread(target=start, args=(port, handler), daemon=True).start()
    print("MyOTA dev gateway: http://127.0.0.1:8080")
    # Bind all interfaces in containers; this is also safe for local development
    # because the gateway is intended to be the only exposed process.
    ThreadingHTTPServer((os.environ.get("MYOTA_BIND_HOST", "0.0.0.0"), 8080), GatewayHandler).serve_forever()


if __name__ == "__main__":
    main()
