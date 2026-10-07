# MyOTA repository ownership

The organization has twelve repositories. The authoritative
[current repository map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md)
lists all services, frontends, contracts, deployment, documentation, integration
mirrors and the `.github` organization profile. The split is implemented, not
a proposal awaiting organization creation.

`myota-platform` owns integration tests and synchronized runtime, contract and
migration mirrors. Domain source belongs to the service repositories;
`myota-deploy` owns Compose/Helm/Fleet orchestration. Mirror migrations must
match their owning service's ordered files byte for byte and are applied to
`myota_core`, `myota_activity` or `myota_geo` according to ownership.

Geodata workers own preprocessing, promotion and confirmed entity deletion.
The operations service only inspects broker metadata and keeps sampled history
in its own core table. It does not become a shared domain-worker service.
See the [scaling delivery and evidence](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-horizontal-scaling-roadmap.md#latest-delivery-and-evidence--7-october-2026)
for the latest boundaries, verification and open gates.
