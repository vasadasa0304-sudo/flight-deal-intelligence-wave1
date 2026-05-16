-- 003_detector_dedup_constraint.sql
-- Add deduplication unique constraint on detected_anomalies.
-- Run once after 002_grain_constraints.sql.
--
-- The anomaly detector uses ON CONFLICT ON CONSTRAINT to skip re-inserting
-- the same (observation, baseline, threshold_set) triple across concurrent
-- or repeated detector runs.

ALTER TABLE detected_anomalies
    ADD CONSTRAINT uq_detected_anomalies_obs_baseline_threshold
    UNIQUE (price_observation_id, baseline_id, threshold_set);
