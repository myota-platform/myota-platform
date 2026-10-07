-- Operational samples live in the shared control-plane physical database,
-- never in browser storage or a geodata process cache.
CREATE TABLE IF NOT EXISTS operations_jetstream_snapshot (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_slot bigint NOT NULL UNIQUE,
  captured_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL CHECK (status IN ('HEALTHY','PARTIAL','UNAVAILABLE')),
  payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_jetstream_snapshot_history_idx
  ON operations_jetstream_snapshot(captured_at DESC,id DESC);
