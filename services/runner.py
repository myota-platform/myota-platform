from __future__ import annotations

import os
import sys
from http.server import ThreadingHTTPServer
from common import BoundedThreadingHTTPServer

service = os.environ.get("SERVICE", "").lower()
if service == "identity":
    from identity import IdentityHandler, bootstrap_admin, seed as seed_service

    port, handler, seed = 8001, IdentityHandler, seed_service
elif service == "programmes":
    from programmes import ProgrammeHandler, seed as seed_service

    port, handler, seed = 8002, ProgrammeHandler, seed_service
elif service == "geodata":
    from geodata import GeoHandler

    port, handler, seed = 8003, GeoHandler, GeoHandler.store.hydrate
elif service == "activity":
    from activity import ActivityHandler

    port, handler, seed = 8004, ActivityHandler, lambda: None
else:
    print(
        "SERVICE must be one of: identity, programmes, geodata, activity",
        file=sys.stderr,
    )
    raise SystemExit(2)
seed()
if service == "geodata":
    # Requeue imports abandoned by the previous geodata instance only after
    # durable geodata state has been hydrated.
    handler.recover_import_runs()
if service == "identity":
    bootstrap_admin()
handler.store.persist()
print(f"{service}-service listening on :{port}")
server_class = (
    BoundedThreadingHTTPServer
    if service == "activity"
    else ThreadingHTTPServer
)
server = server_class(("0.0.0.0", port), handler)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    handler.store.persist()
    handler.store.close()
    server.server_close()
