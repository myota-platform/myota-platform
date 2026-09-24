#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 -d "$PGDATABASE" -f /migrations/migrations/core/001_core.sql
if [ "$(psql -Atqc "SELECT 1 FROM pg_database WHERE datname = 'myota_geo'")" != "1" ]; then
  createdb myota_geo
fi
PGDATABASE=myota_geo psql -v ON_ERROR_STOP=1 -d myota_geo -f /migrations/migrations/geo/001_geodata.sql
PGDATABASE=myota_geo psql -v ON_ERROR_STOP=1 -d myota_geo -f /migrations/migrations/geo/002_qgis_views.sql
