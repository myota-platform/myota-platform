#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${1:?usage: restore.sh CORE_DUMP GEO_DUMP}"
: "${2:?usage: restore.sh CORE_DUMP GEO_DUMP}"
pg_restore --clean --if-exists --exit-on-error --dbname="${PGDATABASE:-myota_core}" "$1"
PGDATABASE="${GEO_DATABASE:-myota_geo}" pg_restore --clean --if-exists --exit-on-error --dbname="${GEO_DATABASE:-myota_geo}" "$2"
