-- Mirrored from myota-operations-service/migrations/003_retire_jetstream_snapshots.sql.
-- JetStream is observed by NATS Surveyor; Operations no longer stores NATS history.
-- The pre-cutover table was backed up before the Surveyor cutover.
DROP TABLE IF EXISTS operations_jetstream_snapshot;
