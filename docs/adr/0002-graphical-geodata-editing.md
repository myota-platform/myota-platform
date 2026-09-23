# ADR-0002: QGIS plus browser review workflow

Use QGIS as the graphical PostGIS editing/admin tool for trusted bulk correction and inspection, connected to `myota_geo` through a restricted editor role. Use the universal web frontend for community proposals and approver review so normal users never receive direct database credentials.

QGIS is especially suitable for geometry validation, layer comparison, conflation inspection and controlled edits. Web review is the safe default for lifecycle transitions, audit events and programme-aware permissions. Direct QGIS edits must go through a staging/edit schema or a database trigger that records audit metadata; production approval transitions remain API-owned.

