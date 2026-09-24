from __future__ import annotations

import os
import sys
from http.server import ThreadingHTTPServer

from activity import ActivityHandler
from geodata import GeoHandler, seed as seed_geodata
from identity import IdentityHandler, seed as seed_identity
from programmes import ProgrammeHandler, seed as seed_programmes

CONFIG = {
    "identity": (8001, IdentityHandler, seed_identity),
    "programmes": (8002, ProgrammeHandler, seed_programmes),
    "geodata": (8003, GeoHandler, seed_geodata),
    "activity": (8004, ActivityHandler, lambda: None),
}

service = os.environ.get("SERVICE", "").lower()
if service not in CONFIG:
    print("SERVICE must be one of: " + ", ".join(CONFIG), file=sys.stderr)
    raise SystemExit(2)
port, handler, seed = CONFIG[service]
seed()
handler.store.persist()
print(f"{service}-service listening on :{port}")
server = ThreadingHTTPServer(("0.0.0.0", port), handler)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    handler.store.persist()
    handler.store.close()
    server.server_close()
