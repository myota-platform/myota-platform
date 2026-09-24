# Graphical PostGIS editing workflow

QGIS is the recommended graphical tool for geodata operators. Connect it to the `myota_geo` database using the `myota_geo_qgis_readonly` role for inspection or `myota_geo_qgis_editor` for staging edits, then load:

- `qgis_entity_review_queue` for candidate/proposed/rejected records;
- `qgis_approved_entities` for the public reference layer.

Use QGIS for geometry inspection, repair, source-layer comparison and conflation review. The editor role can insert or update `geodata_edit_staging`, but cannot delete platform entities or change lifecycle status. Use the geodata API for lifecycle transitions, proposals, approver scopes and audit events. A QGIS edit is not an approval; the API remains authoritative for `APPROVED` status. Source records marked `STALE` or `REVIEW_REQUIRED` remain visible in the review queue.

For a small deployment, the same PostGIS cluster can host both databases. For larger imports, run QGIS and importer workers against the geodata database/replica while API reads use a read-only pool.
