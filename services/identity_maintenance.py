"""Periodic identity retention worker."""
from __future__ import annotations

import os
import time

from identity import IdentityHandler


interval = int(os.environ.get("MYOTA_IDENTITY_MAINTENANCE_SECONDS", "3600"))
IdentityHandler.store.hydrate()
try:
    while True:
        IdentityHandler.cleanup_expired()
        IdentityHandler.store.persist()
        time.sleep(interval)
except KeyboardInterrupt:
    pass
finally:
    IdentityHandler.store.persist()
    IdentityHandler.store.close()
