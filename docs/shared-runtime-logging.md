# Shared runtime logging

`runtime/myota_logging.py` is the canonical implementation of the common
structured logging, request ID, trace-context, and redaction helpers used by
standalone service images.

Run `python3 scripts/sync_runtime_logging.py ..` from this repository root to
copy it into the five service build contexts and the Deploy and Platform
runtime trees. Use `--check` to verify exact content parity without writing.
The Contracts workflow runs the same source-to-mirror audit.

Service-specific request handling, authorization, database transactions, and
persistence remain owned by each service repository. The `common.py` files
are intentionally not consolidated: they combine those service-specific
boundaries, and Activity/Geodata/Operations include distinct server, metrics,
upload, and state-store behavior. A future extraction must establish a
versioned compatibility boundary first.
