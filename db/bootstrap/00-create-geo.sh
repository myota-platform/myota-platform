#!/usr/bin/env bash
set -euo pipefail

if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -tAc "SELECT 1 FROM pg_database WHERE datname='myota_geo'" | grep -q 1; then
  createdb --username "$POSTGRES_USER" myota_geo
fi
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname myota_geo -f /docker-entrypoint-initdb.d/geo.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname myota_geo -f /docker-entrypoint-initdb.d/geo-views.sql

