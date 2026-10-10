# JetStream topology provisioning

**Status:** Phase 1 contract/topology work is complete. Production activation
remains disabled until the Phase 2 compatibility and rollout gates pass.

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
limits, and explicit work durable filters. The 30-day fact window and 1/1/3
GiB stream byte caps with a 3 GiB reserve on the current 8 GiB PVC are accepted
conservative initial limits. The observed database sample covers fewer than 10
days and includes load-test traffic; this evidence limit is accepted for the
single-node deployment. Do not raise limits without a representative 30-day
serialized-traffic and outage-backlog review. The script has no numeric defaults
and requires NATS_TOPOLOGY_APPLY=1 and positive capacity values before connecting.

The deployed broker is unauthenticated and has no TLS, consistent with the
accepted cluster-internal trust decision. The NATS service is ClusterIP-only on
port 4222. The `myota` namespace has no NetworkPolicy, so any pod with network
reachability is trusted to connect. NATS auth/TLS and runtime broker credentials
are not required while this boundary holds. Do not expose NATS outside the
cluster; revisit the decision before changing service exposure or admitting
untrusted workloads.

For an isolated broker only, use the disposable Compose profile with explicit
test limits. The disposable K3s test verified creation, idempotency, drift
rejection, local PVC restore, replay, and `DiscardNew` pressure rejection. The
temporary namespace and its storage were removed afterward. Off-node recovery
is explicitly deferred; PostgreSQL remains the source for reconciliation and
work redrive. This qualification is limited to a single-node environment.

The current relay still provisions legacy durables and changes retention. The
chart now includes an opt-in `pre-upgrade` provisioner hook; Helm waits for
create-only provisioning and exact drift validation before updating workloads.
It is disabled by default and refuses to render unless the operator confirms
the documented migration gate. Do not enable it against the current mixed
Interest-retained stream. Relay mutation remains a later cutover task. The
[Phase 1 review](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/evidence/phase1-joint-review-2026-10-10.md),
[recovery runbook](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/jetstream-recovery.md),
and [migration plan](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/nats-event-migration-plan.md)
record the remaining gates. Operations remains a metadata-only observer.
