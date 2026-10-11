"""Periodic identity retention worker."""

from __future__ import annotations

import logging
import os
import time

from identity import IdentityHandler
from myota_logging import configure_logging, log_event


interval = int(os.environ.get("MYOTA_IDENTITY_MAINTENANCE_SECONDS", "3600"))
configure_logging("myota-identity", "identity-maintenance")
IdentityHandler.store.hydrate()
try:
    while True:
        log_event(logging.getLogger(__name__), logging.INFO, "job.started", component="identity-maintenance", job_type="identity-retention")
        removed = IdentityHandler.cleanup_expired()
        IdentityHandler.store.persist()
        log_event(logging.getLogger(__name__), logging.INFO, "job.completed", component="identity-maintenance", job_type="identity-retention", removed_count=removed if isinstance(removed, int) else 0)
        time.sleep(interval)
except KeyboardInterrupt:
    pass
finally:
    IdentityHandler.store.persist()
    IdentityHandler.store.close()
