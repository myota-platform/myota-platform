# Migration from `ea7klk/mpota`

The existing project is retained as the product/charter source and is not modified. Its planned park reference list maps into MyOTA as:

| Existing concept | MyOTA target |
|---|---|
| MPOTA programme | `programme.slug = mpota` sample fixture |
| municipal park | programme entity type `MUNICIPAL_PARK` |
| park reference | `geodata_entity` plus external `source_reference` |
| proposal | candidate → proposed entity review |
| approver country/continent scope | identity/authorization policy scoped by programme + jurisdiction |
| activation log / ADIF | activity activation and QSO ingestion |
| translation catalog | programme theme/content configuration and frontend locale bundles |

Recommended migration order is export/normalize source records, load them into `myota_geo` as candidates with provenance, reconcile duplicates against authoritative imports, then run a review campaign. No source record should be silently promoted to `APPROVED` solely because it existed in the old application.

