-- Read-only storage samples owned by the operations service in myota_core.
CREATE TABLE IF NOT EXISTS operations_storage_snapshot (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_slot bigint NOT NULL UNIQUE,
  captured_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL CHECK (status IN ('HEALTHY','PARTIAL','UNAVAILABLE')),
  payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_storage_snapshot_history_idx
  ON operations_storage_snapshot(captured_at DESC,id DESC);
