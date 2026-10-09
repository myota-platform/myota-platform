# JetStream topology provisioning

**Status:** Phase 1 implementation in progress. Do not provision the target
topology in a live environment until the matching evidence gates and measured
capacity values in the NATS migration plan are closed.

`services/jetstream_topology.py` is the side-effect-free ADR-0008 topology
definition. `services/provision_jetstream.py` is the single create-only
provisioner. It creates the three target streams and ten work durables, validates
all configured limits and correctness-sensitive consumer delivery settings, and fails on drift. It
never edits or deletes an existing stream or consumer. In particular, it cannot
convert the current shared `MYOTA_EVENTS` stream from Interest to Limits; that
stream also contains legacy Geodata work and requires a separately reviewed
drain/migration procedure.

Finite age, byte, message, and per-message limits have no code defaults for the
two work streams. They must be set from measured production traffic, maximum
accepted work duration, storage budget, and recovery objectives. The fact stream
uses the selected 30-day bounded window. The script fails before connecting if
`NATS_TOPOLOGY_APPLY` is not exactly `1` or any capacity value is absent or
non-positive. Today the compose broker has no configured authenticated user, so
this provisioner is not least-privilege-ready for production. Do not pass
credentials through ad hoc command-line arguments or enable it on the deployed
host before NATS authentication and per-role permissions are designed.

For an isolated broker only, create a disposable environment with the required
measured test values and explicitly run the `nats-topology` Compose profile. Do
not run it against the host's deployed broker until the plan's Phase 1 and
rollout gates are approved and an isolated/production-like evidence record is
attached. Existing mismatched topology is an error to investigate, not a reason
to enable automatic updates.

The current relay still provisions legacy durables and changes retention. Phase
2 must remove that mutation and require a pre-provisioned target before this
one-shot tool can be used in a cutover. Operations remains read-only.
