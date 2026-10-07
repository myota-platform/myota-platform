#!/usr/bin/env bash
set -euo pipefail

# Deployment orchestrates three service-owned databases. Helm supplies the
# same variables from its database secret; these defaults keep local Compose
# straightforward.
: "${CORE_HOST:=core-db}"
: "${ACTIVITY_HOST:=activity-db}"
: "${GEO_HOST:=geo-db}"
: "${CORE_PORT:=5432}"
: "${ACTIVITY_PORT:=$CORE_PORT}"
: "${GEO_PORT:=$CORE_PORT}"
: "${PGUSER:=myota}"
: "${PGPASSWORD:=myota-dev-only}"
: "${CORE_DATABASE:=myota_core}"
: "${ACTIVITY_DATABASE:=myota_activity}"
: "${GEO_DATABASE:=myota_geo}"
: "${MYOTA_SCHEMA_REVISION:=0}"
: "${LEGACY_GEO_HOST:=$CORE_HOST}"
: "${LEGACY_GEO_PORT:=$CORE_PORT}"
: "${LEGACY_GEO_DATABASE:=myota_geo}"
: "${MIGRATION_DATA_COPY_ENABLED:=1}"

# This runner is used from two layouts: directly from the deployment image
# (/app/db/migrations/run.sh), and from Compose with the script mounted at
# /migrations/run.sh and the SQL mounted below /migrations/migrations. Resolve
# the SQL directory from the runner instead of assuming one absolute path.
RUNNER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$RUNNER_DIR/core" && -d "$RUNNER_DIR/geo" ]]; then
  MIGRATION_FILES_DIR="$RUNNER_DIR"
elif [[ -d "$RUNNER_DIR/migrations/core" && -d "$RUNNER_DIR/migrations/geo" ]]; then
  MIGRATION_FILES_DIR="$RUNNER_DIR/migrations"
else
  echo "Migration SQL directory not found beside runner: $RUNNER_DIR" >&2
  exit 1
fi

export PGUSER PGPASSWORD

psql_target() {
  local host="$1" port="$2" database="$3"
  shift 3
  PGHOST="$host" PGPORT="$port" PGDATABASE="$database" \
    PGOPTIONS="${PGOPTIONS:-} -c myota.geodata_writer=row-v1" \
    psql -v ON_ERROR_STOP=1 "$@"
}

pg_dump_target() {
  local host="$1" port="$2" database="$3"
  shift 3
  PGHOST="$host" PGPORT="$port" PGDATABASE="$database" \
    pg_dump --no-owner --no-privileges "$@"
}

wait_for_db() {
  local host="$1" port="$2" database="$3"
  until PGHOST="$host" PGPORT="$port" PGDATABASE="$database" pg_isready -q; do
    sleep 2
  done
}

wait_for_db "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE"
wait_for_db "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE"
wait_for_db "$GEO_HOST" "$GEO_PORT" "$GEO_DATABASE"

# App pods gate their startup on this marker. Clear all markers before running
# any migration so a failed/partial run cannot expose a mixed schema as ready.
for target in \
  "$CORE_HOST $CORE_PORT $CORE_DATABASE" \
  "$ACTIVITY_HOST $ACTIVITY_PORT $ACTIVITY_DATABASE" \
  "$GEO_HOST $GEO_PORT $GEO_DATABASE"; do
  read -r host port database <<< "$target"
  psql_target "$host" "$port" "$database" -c "
    CREATE TABLE IF NOT EXISTS public.myota_deployment_schema_state (
      id text PRIMARY KEY,
      ready boolean NOT NULL DEFAULT false,
      release_revision integer NOT NULL DEFAULT 0,
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE public.myota_deployment_schema_state
      ADD COLUMN IF NOT EXISTS release_revision integer NOT NULL DEFAULT 0;
    INSERT INTO public.myota_deployment_schema_state (id, ready, release_revision)
    VALUES ('deployment', false, $MYOTA_SCHEMA_REVISION)
    ON CONFLICT (id) DO UPDATE
      SET ready = false, release_revision = EXCLUDED.release_revision, updated_at = now();
    DO \$grant\$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'myota_app') THEN
        EXECUTE 'GRANT SELECT ON public.myota_deployment_schema_state TO myota_app';
      END IF;
    END
    \$grant\$;
  "
done

psql_target "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE" \
  -f "$MIGRATION_FILES_DIR/core/001_core.sql"
psql_target "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE" \
  -f "$MIGRATION_FILES_DIR/core/002_operations.sql"

psql_target "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE" \
  -f "$MIGRATION_FILES_DIR/activity/001_activity_relational.sql"
psql_target "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE" \
  -f "$MIGRATION_FILES_DIR/activity/002_activity_entity_deletion.sql"
psql_target "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE" \
  -f "$MIGRATION_FILES_DIR/activity/003_adif_source_retention.sql"
psql_target "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE" \
  -f "$MIGRATION_FILES_DIR/activity/004_adif_failed_source_retention.sql"

for migration in \
  001_geodata.sql \
  002_qgis_views.sql \
  003_production_pipeline.sql \
  004_location_enrichment.sql \
  005_location_manual_precedence.sql \
  006_unscoped_imports.sql \
  007_relational_entity_persistence.sql \
  008_entity_category_assignments.sql \
  009_candidate_lifecycle.sql \
  010_import_preprocessing.sql \
  011_import_recovery.sql \
  012_import_finalization.sql \
  013_import_retention.sql \
  014_resumable_uploads.sql \
  015_jetstream_worker_dispatch.sql \
  016_relational_authority.sql; do
  psql_target "$GEO_HOST" "$GEO_PORT" "$GEO_DATABASE" \
    -f "$MIGRATION_FILES_DIR/geo/$migration"
done

# Preserve local development data during the first split. Activity is copied
# from the existing core database and geodata from the legacy myota_geo
# database only when the corresponding target is empty. Re-running the job is
# safe and does not duplicate rows. The legacy source databases may be removed
# after an operator verifies all domain and operational table counts.
if [ "$MIGRATION_DATA_COPY_ENABLED" = "1" ]; then
  activity_source_tables_exist="$(psql_target "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE" \
    -Atqc "SELECT CASE WHEN to_regclass('public.activity_activation') IS NOT NULL AND to_regclass('public.activity_qso') IS NOT NULL THEN 1 ELSE 0 END")"
  activity_source_has_data=0
  if [ "$activity_source_tables_exist" = "1" ]; then
    activity_source_has_data="$(psql_target "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE" \
      -Atqc "SELECT CASE WHEN EXISTS (SELECT 1 FROM activity_activation LIMIT 1) OR EXISTS (SELECT 1 FROM activity_qso LIMIT 1) THEN 1 ELSE 0 END")"
  fi
  activity_target_has_data="$(psql_target "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE" \
    -Atqc "SELECT CASE WHEN EXISTS (SELECT 1 FROM activity_activation LIMIT 1) OR EXISTS (SELECT 1 FROM activity_qso LIMIT 1) THEN 1 ELSE 0 END")"
  if [ "$activity_source_has_data" = "1" ] && [ "$activity_target_has_data" = "0" ]; then
    echo "Copying existing activity data from $CORE_DATABASE to $ACTIVITY_DATABASE"
    pg_dump_target "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE" \
      --data-only --schema=public -t 'public.activity_*' \
      | PGHOST="$ACTIVITY_HOST" PGPORT="$ACTIVITY_PORT" PGDATABASE="$ACTIVITY_DATABASE" psql -v ON_ERROR_STOP=1
  fi

  legacy_geo_exists="$(psql_target "$LEGACY_GEO_HOST" "$LEGACY_GEO_PORT" "$CORE_DATABASE" \
    -Atqc "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname = '$LEGACY_GEO_DATABASE') THEN 1 ELSE 0 END")"
  if [ "$legacy_geo_exists" = "1" ]; then
    # A preserved legacy database may contain a PostGIS extension while the
    # active core server is intentionally plain PostgreSQL. In that state the
    # catalog is visible but pg_dump cannot load the extension library. Skip
    # the recoverable source rather than failing every later migration run.
    legacy_geo_postgis="$(psql_target "$LEGACY_GEO_HOST" "$LEGACY_GEO_PORT" "$LEGACY_GEO_DATABASE" \
      -Atqc "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN 1 ELSE 0 END" 2>/dev/null || true)"
    if [ "$legacy_geo_postgis" = "1" ]; then
      geo_source_has_data="$(psql_target "$LEGACY_GEO_HOST" "$LEGACY_GEO_PORT" "$LEGACY_GEO_DATABASE" \
        -Atqc "SELECT CASE WHEN EXISTS (SELECT 1 FROM geodata_entity LIMIT 1) OR EXISTS (SELECT 1 FROM import_run LIMIT 1) THEN 1 ELSE 0 END")"
      geo_target_has_data="$(psql_target "$GEO_HOST" "$GEO_PORT" "$GEO_DATABASE" \
        -Atqc "SELECT CASE WHEN EXISTS (SELECT 1 FROM geodata_entity LIMIT 1) OR EXISTS (SELECT 1 FROM import_run LIMIT 1) THEN 1 ELSE 0 END")"
      if [ "$geo_source_has_data" = "1" ] && [ "$geo_target_has_data" = "0" ]; then
        echo "Copying existing geodata from $LEGACY_GEO_DATABASE to $GEO_DATABASE"
        pg_dump_target "$LEGACY_GEO_HOST" "$LEGACY_GEO_PORT" "$LEGACY_GEO_DATABASE" \
          --data-only --schema=public \
          -t public.entity_type \
          -t public.geodata_entity \
          -t public.source_reference \
          -t public.import_run \
          -t public.entity_review \
          -t public.conflation_candidate \
          -t public.source_snapshot_manifest \
          -t public.source_snapshot_record \
          -t public.import_schedule \
          -t public.geodata_entity_attachment \
          -t public.geodata_edit_staging \
          -t public.geodata_entity_category \
          -t public.geodata_import_candidate \
          -t public.geodata_import_processing_queue \
          -t public.service_state \
          -t public.idempotency_record \
          -t public.outbox_event \
          -t public.consumer_checkpoint \
          -t public.consumer_processed_event \
          -t public.dead_letter_event \
          | PGHOST="$GEO_HOST" PGPORT="$GEO_PORT" PGDATABASE="$GEO_DATABASE" psql -v ON_ERROR_STOP=1
      fi
    else
      echo "Legacy geodata database is unavailable with PostGIS; skipping its copy"
    fi
  else
    echo "No legacy geodata database found; skipping its already-completed copy"
  fi
fi

# Mark every database ready only after all schemas and any one-time data copy
# have completed successfully. On any earlier error the marker remains false.
for target in \
  "$CORE_HOST $CORE_PORT $CORE_DATABASE" \
  "$ACTIVITY_HOST $ACTIVITY_PORT $ACTIVITY_DATABASE" \
  "$GEO_HOST $GEO_PORT $GEO_DATABASE"; do
  read -r host port database <<< "$target"
  psql_target "$host" "$port" "$database" -c "
    UPDATE public.myota_deployment_schema_state
       SET ready = true, updated_at = now()
     WHERE id = 'deployment' AND release_revision = $MYOTA_SCHEMA_REVISION;
  "
done

echo "MyOTA database migrations completed: core=$CORE_DATABASE activity=$ACTIVITY_DATABASE geo=$GEO_DATABASE"
