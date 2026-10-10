# JetStream topology provisioning

**Status:** Phase 1 implementation is in progress. Do not provision the target
topology in a live environment until the migration plan's evidence gates and
measured capacity values are closed.

`services/jetstream_topology.py` is the side-effect-free ADR-0008 topology
definition. `services/provision_jetstream.py` is the single create-only
provisioner. It defines three target streams and ten work durables, validates
all configured limits and correctness-sensitive consumer delivery settings,
and fails on drift. It never edits or deletes an existing stream or consumer.
The registry-to-topology contract check verifies that all ten work subjects and
durables match
[the contracts registry](https://github.com/myota-platform/myota-contracts/blob/main/contracts/event-registry.json).
The topology tests verify explicit capacity requirements, the apply gate, and
consumer drift rejection. Do not run this provisioner against the current
shared MYOTA_EVENTS stream: it has a different subject/retention configuration,
also contains legacy Geodata work, and requires a separately reviewed
drain/migration procedure.

The selected policy is Limits retention for bounded facts and WorkQueue
retention for Activity and Geodata commands. Streams use file storage,
DiscardNew, one replica on the current single-server cluster, finite per-message
limits, and explicit work durable filters. The 30-day fact window is selected;
byte, message, age and per-message limits for the target streams have no code
defaults. The values in the joint review are provisional and must be replaced
with measured representative traffic, maximum accepted-work duration, storage
reserve, and recovery objectives before production activation. The script
requires NATS_TOPOLOGY_APPLY=1 and positive capacity values before connecting.

The deployed broker is unauthenticated and has no TLS, consistent with the
accepted cluster-internal trust decision. The NATS service is ClusterIP-only on
port 4222. The `myota` namespace has no NetworkPolicy, so any pod with network
reachability is trusted to connect. NATS auth/TLS and runtime broker credentials
are not required while this boundary holds. Do not expose NATS outside the
cluster; revisit the decision before changing service exposure or admitting
untrusted workloads.

For an isolated broker only, use the disposable Compose profile with explicit
test limits. The isolated create/idempotency/drift test passed, and focused
topology tests plus Ruff checks passed. These checks do not qualify off-node
backup/restore or production capacity.

The current relay still provisions legacy durables and changes retention. Do
not remove that behavior until a controlled Helm/Fleet readiness barrier has
validated a migration-safe compatibility topology and current consumers can
connect. The [Phase 1 review](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/evidence/phase1-joint-review-2026-10-10.md),
[recovery runbook](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/jetstream-recovery.md),
and [migration plan](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/nats-event-migration-plan.md)
record the remaining gates. Operations remains a metadata-only observer.
