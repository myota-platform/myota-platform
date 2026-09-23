# Proposed MyOTA repositories

The following split is justified and intentionally small:

| Repository | Owns | Initial source here |
|---|---|---|
| `myota-contracts` | OpenAPI, event schemas, compatibility rules, generated client release | `contracts/` |
| `myota-identity-service` | accounts, callsigns, auth claims, OIDC mappings | `services/identity.py`, core migrations |
| `myota-programme-service` | programmes, entity types, rules, awards, themes | `services/programmes.py`, core migrations |
| `myota-geodata-service` | PostGIS, import adapters, provenance, conflation, review | `services/geodata.py`, geo migrations |
| `myota-activity-service` | activations, QSOs, award calculations | `services/activity.py`, core migrations |
| `myota-web` | universal programme UI and generated API client | `web/` |
| `myota-deploy` | Helm charts, environments, migrations, observability | `deploy/`, `compose.yaml` |
| `myota-docs` | architecture, ADRs, operator and migration docs | `docs/` |

The bootstrap repository is a temporary integration workspace; it is not a reason to create many more repositories. Once the MyOTA organization is available, each row can be created from the corresponding paths and wired together by pinned contract versions.

