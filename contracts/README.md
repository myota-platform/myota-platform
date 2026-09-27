# Contract generation and compatibility

`openapi.yaml` is the versioned source of truth for HTTP contracts. The checked-
in `python/myota_client.py` is a dependency-light client for local integration;
production SDKs should be regenerated in CI with the pinned OpenAPI Generator
version selected by the consuming repository.

Compatibility rules:

- Additive request/response fields are compatible within `/v1`.
- Removing or changing a field requires `/v2` or an explicit deprecation window
  with `Deprecation` and `Sunset` response headers.
- Event names carry their schema version (`*.v1`); consumers reject unknown
  major versions and may accept additive fields.
- Every mutating request supports `Idempotency-Key`; every response carries
  request/correlation IDs.

CI should run an OpenAPI linter, server/client generation, and a breaking-change
diff against the last released contract before publishing a service image.

This contract copy is an integration mirror. The canonical contract and the
proposed route consolidation are maintained in
[myota-contracts](https://github.com/myota-platform/myota-contracts) and the
[REST API consolidation plan](https://github.com/myota-platform/myota-docs/blob/main/docs/api-rest-consolidation-plan.md).
Do not introduce route changes in this mirror independently.
