-- 005_alerts_dedup_constraint.sql
-- Add deduplication unique constraint on alerts.anomaly_id.
-- Run once after 004_qa_checks_external_flag.sql.
--
-- promote_to_alerts uses ON CONFLICT ON CONSTRAINT to skip re-inserting
-- the same anomaly across concurrent or repeated export runs.

ALTER TABLE alerts
    ADD CONSTRAINT uq_alerts_anomaly_id UNIQUE (anomaly_id);
