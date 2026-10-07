# Local and production operations

## Local

1. Start Colima; Kubernetes is optional for the Compose environment.
2. Run dependency-free tests: `make test`.
3. For the browser slice: `make run`.
4. For the complete durable stack, run `docker-compose --profile observability up -d --build`
   from sibling `myota-deploy`. The participant gateway uses port 8080;
   Vue administration uses 8090 and includes `/jetstream` and `/observability/`.
5. For Kubernetes/Fleet, follow the authoritative
   [operations guide](https://github.com/myota-platform/myota-docs/blob/main/docs/operations.md#rancher-fleet-on-k3s)
   and deployment README. Helm validation/rendering runs in GitHub workflows.

`make test` and `make run` remain integration/test adapters; they are not the
full durable runtime and do not replace independent JetStream consumers or
operations sampling. See the [scaling delivery/evidence checklist](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-horizontal-scaling-roadmap.md#latest-delivery-and-evidence--7-october-2026)
before changing API or worker replica counts.

## Production notes

Back up `myota_core`, `myota_activity` and `myota_geo` independently, along with
SeaweedFS objects. Only geo requires PostGIS. Use Kubernetes Secrets or an
external secret manager, pin image digests and restrict database access to
owning services. Geodata migration 016 requires coordinated API/worker rollout
and rejects old snapshot writers; follow the
[write-fenced rollout/rollback procedure](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-phase1-relational-authority.md#migration-and-rollout).
QGIS access must remain private. Production canary, memory, failure and scaling
qualification gates are still open.
