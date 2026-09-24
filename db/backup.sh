#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
backup_dir="${1:-./backups}"
mkdir -p "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump --format=custom --file="$backup_dir/myota_core-$stamp.dump" "${PGDATABASE:-myota_core}"
PGDATABASE="${GEO_DATABASE:-myota_geo}" pg_dump --format=custom --file="$backup_dir/myota_geo-$stamp.dump" "${GEO_DATABASE:-myota_geo}"
printf '%s\n' "$backup_dir/myota_core-$stamp.dump" "$backup_dir/myota_geo-$stamp.dump"
