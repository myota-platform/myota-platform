# Geodata migration mirror

These files mirror the canonical migration source in
`myota-geodata-service/migrations/`. They are kept in the platform repository
so the runnable vertical slice has a complete PostGIS bootstrap without
depending on a service checkout.

Do not edit this mirror independently. Update the geodata service migration
source first, synchronize the complete ordered set, and verify byte-for-byte
equality. The location-enrichment migration adds reverse-geocoded entity
fields and must remain synchronized with the service repository. The
manual-location precedence migration also persists which fields are
administrator-controlled and exposes them through the QGIS review views.
Shared core infrastructure is defined by
`../core/001_core.sql` and must not be duplicated here.
