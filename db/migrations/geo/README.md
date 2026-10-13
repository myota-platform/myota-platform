# Geodata baseline mirror

'001_geodata_baseline.sql' is a synchronized deployment copy of the current
Geodata schema baseline from
'myota-geodata-service/migrations/001_geodata_baseline.sql'. The service
repository is authoritative. Do not edit this mirror independently. The
baseline includes the current PostGIS schema, QGIS views, role setup, and
grants; it contains no application rows.
