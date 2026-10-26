#!/usr/bin/env bash
set -euo pipefail

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

RUNNER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_FILES_DIR="$RUNNER_DIR"
export PGUSER PGPASSWORD

psql_target() {
  local host="$1" port="$2" database="$3"
  shift 3
  PGHOST="$host" PGPORT="$port" PGDATABASE="$database" \
    PGOPTIONS="${PGOPTIONS:-} -c myota.geodata_writer=row-v1" \
    psql -X -v ON_ERROR_STOP=1 "$@"
}

wait_for_db() {
  local host="$1" port="$2" database="$3"
  until PGHOST="$host" PGPORT="$port" PGDATABASE="$database" pg_isready -q; do
    sleep 2
  done
}

prior_ready() {
  local host="$1" port="$2" database="$3"
  psql_target "$host" "$port" "$database" -Atqc \
    "SELECT ready FROM public.myota_deployment_schema_state WHERE id='deployment'" \
    2>/dev/null || true
}

schema_sentinel_exists() {
  local host="$1" port="$2" database="$3" table="$4"
  psql_target "$host" "$port" "$database" -Atqc \
    "SELECT to_regclass('$table') IS NOT NULL" 2>/dev/null || true
}

unmanaged_relation_count() {
  local host="$1" port="$2" database="$3"
  psql_target "$host" "$port" "$database" -Atqc "
    SELECT count(*)
      FROM pg_class c
      JOIN pg_namespace n ON n.oid=c.relnamespace
      LEFT JOIN pg_depend d
        ON d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e'
     WHERE n.nspname='public'
       AND c.relkind IN ('r','p','v','m','S','f')
       AND c.relname NOT IN ('myota_deployment_schema_state','myota_schema_migration')
       AND d.objid IS NULL"
}

apply_migrations() {
  local host="$1" port="$2" database="$3" domain="$4" was_ready="$5" sentinel="$6"
  local migration_directory="$MIGRATION_FILES_DIR/$domain"
  local migration_files=("$migration_directory"/[0-9][0-9][0-9]_*.sql)
  local migration_file migration_id checksum ledger_exists ledger_row stored_checksum stored_mode relation_count sentinel_found

  if [[ ! -f "${migration_files[0]}" ]]; then
    echo "No numbered SQL migrations found in $migration_directory" >&2
    return 1
  fi

  for migration_file in "${migration_files[@]}"; do
    migration_id="$(basename "$migration_file")"
    checksum="$(sha256sum "$migration_file" | cut -d' ' -f1)"
    ledger_exists="$(psql_target "$host" "$port" "$database" -Atqc \
      "SELECT to_regclass('public.myota_schema_migration') IS NOT NULL")"

    if [[ "$ledger_exists" == "t" && "$migration_id" == *baseline.sql ]]; then
      ledger_row="$(psql_target "$host" "$port" "$database" -At -F '|' -c \
        "SELECT coalesce(checksum,''), application_mode FROM public.myota_schema_migration WHERE migration_id='baseline-v1'")"
      if [[ -n "$ledger_row" ]]; then
        stored_checksum="${ledger_row%%|*}"
        stored_mode="${ledger_row#*|}"
        if [[ "$stored_mode" != "applied" && "$stored_mode" != "adopted" ]]; then
          echo "Unknown baseline mode in $database; refusing to start" >&2
          return 1
        fi
        if [[ -n "$stored_checksum" && "$stored_checksum" != "$checksum" ]]; then
          echo "Baseline checksum mismatch for $database; refusing to change an applied baseline" >&2
          return 1
        fi
        if [[ -z "$stored_checksum" ]]; then
          sentinel_found="$(schema_sentinel_exists "$host" "$port" "$database" "$sentinel")"
          if [[ "$sentinel_found" != "t" ]]; then
            echo "Baseline ledger exists in $database but its expected schema object $sentinel is missing" >&2
            return 1
          fi
          psql_target "$host" "$port" "$database" -c \
            "UPDATE public.myota_schema_migration SET checksum='$checksum' WHERE migration_id='baseline-v1'"
        fi
        echo "Baseline already recorded for $database; skipping"
        continue
      fi
    fi

    if [[ "$migration_id" == *baseline.sql ]]; then
      if [[ "$was_ready" == "t" ]]; then
        sentinel_found="$(schema_sentinel_exists "$host" "$port" "$database" "$sentinel")"
        if [[ "$sentinel_found" != "t" ]]; then
          echo "Previously-ready $database is missing expected schema object $sentinel" >&2
          return 1
        fi
        psql_target "$host" "$port" "$database" -c "
          CREATE TABLE IF NOT EXISTS public.myota_schema_migration (
            migration_id text PRIMARY KEY,
            checksum text,
            application_mode text NOT NULL CHECK (application_mode IN ('applied','adopted')),
            applied_at timestamptz NOT NULL DEFAULT now()
          );
          INSERT INTO public.myota_schema_migration (migration_id, checksum, application_mode)
          VALUES ('baseline-v1', '$checksum', 'adopted')
          ON CONFLICT (migration_id) DO UPDATE SET checksum=EXCLUDED.checksum;"
        echo "Adopted verified, previously-ready $database schema"
      else
        relation_count="$(unmanaged_relation_count "$host" "$port" "$database")"
        if [[ "$relation_count" != "0" ]]; then
          echo "Refusing to apply a fresh baseline to nonempty, unready $database ($relation_count user relations found)" >&2
          return 1
        fi
        psql_target "$host" "$port" "$database" --single-transaction -f "$migration_file"
        psql_target "$host" "$port" "$database" -c \
          "UPDATE public.myota_schema_migration SET checksum='$checksum' WHERE migration_id='baseline-v1'"
        echo "Applied fresh schema baseline to $database"
      fi
    else
      if [[ "$ledger_exists" != "t" ]]; then
        echo "Migration ledger missing before incremental migration $migration_id" >&2
        return 1
      fi
      stored_checksum="$(psql_target "$host" "$port" "$database" -Atqc \
        "SELECT coalesce(checksum,'') FROM public.myota_schema_migration WHERE migration_id='$migration_id'")"
      if [[ -n "$stored_checksum" ]]; then
        if [[ "$stored_checksum" != "$checksum" ]]; then
          echo "Migration checksum mismatch for $database/$migration_id" >&2
          return 1
        fi
        continue
      fi
      if grep -q 'CONCURRENTLY' "$migration_file"; then
        psql_target "$host" "$port" "$database" -f "$migration_file"
      else
        psql_target "$host" "$port" "$database" --single-transaction -f "$migration_file"
      fi
      psql_target "$host" "$port" "$database" -c "
        INSERT INTO public.myota_schema_migration (migration_id, checksum, application_mode)
        VALUES ('$migration_id', '$checksum', 'applied')"
    fi
  done
}

for target in \
  "$CORE_HOST $CORE_PORT $CORE_DATABASE" \
  "$ACTIVITY_HOST $ACTIVITY_PORT $ACTIVITY_DATABASE" \
  "$GEO_HOST $GEO_PORT $GEO_DATABASE"; do
  read -r host port database <<< "$target"
  wait_for_db "$host" "$port" "$database"
done

CORE_WAS_READY="$(prior_ready "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE")"
ACTIVITY_WAS_READY="$(prior_ready "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE")"
GEO_WAS_READY="$(prior_ready "$GEO_HOST" "$GEO_PORT" "$GEO_DATABASE")"

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
    \$grant\$;"
done

apply_migrations "$CORE_HOST" "$CORE_PORT" "$CORE_DATABASE" core "$CORE_WAS_READY" public.account
apply_migrations "$ACTIVITY_HOST" "$ACTIVITY_PORT" "$ACTIVITY_DATABASE" activity "$ACTIVITY_WAS_READY" public.activity_activation
apply_migrations "$GEO_HOST" "$GEO_PORT" "$GEO_DATABASE" geo "$GEO_WAS_READY" public.geodata_entity

for target in \
  "$CORE_HOST $CORE_PORT $CORE_DATABASE" \
  "$ACTIVITY_HOST $ACTIVITY_PORT $ACTIVITY_DATABASE" \
  "$GEO_HOST $GEO_PORT $GEO_DATABASE"; do
  read -r host port database <<< "$target"
  psql_target "$host" "$port" "$database" -c "
    UPDATE public.myota_deployment_schema_state
       SET ready = true, updated_at = now()
     WHERE id = 'deployment' AND release_revision = $MYOTA_SCHEMA_REVISION;"
done

echo "MyOTA database migrations completed: core=$CORE_DATABASE activity=$ACTIVITY_DATABASE geo=$GEO_DATABASE"
