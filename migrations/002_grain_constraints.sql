-- 002_grain_constraints.sql
-- Grain-consistency constraints for Wave1 schema.
-- Run once after 001_init.sql.
--
-- Adds composite FK chains so observations, baselines, and detected
-- anomalies can never be paired across different watchlist grains.

-- 1. Composite UNIQUE on watchlist as FK target for grain consistency.
--    watch_id is already PK; the composite is required by PostgreSQL FK syntax.
ALTER TABLE watchlist
    ADD CONSTRAINT uq_watchlist_grain
    UNIQUE (watch_id, route_id, airline_code, cabin, booking_window_days);

-- 2. Promote baselines.route_id from unvalidated TEXT to a proper FK.
ALTER TABLE baselines
    ADD CONSTRAINT fk_baselines_route_id
    FOREIGN KEY (route_id) REFERENCES routes (route_id);

-- 3. Composite FK: baselines -> watchlist grain.
--    Denormalised fields on every baseline must match its watchlist row.
ALTER TABLE baselines
    ADD CONSTRAINT fk_baselines_watchlist_grain
    FOREIGN KEY (watch_id, route_id, airline_code, cabin, booking_window_days)
    REFERENCES watchlist (watch_id, route_id, airline_code, cabin, booking_window_days);

-- 4. Composite FK: price_observations -> watchlist grain.
--    Denormalised fields on every observation must match its watchlist row.
ALTER TABLE price_observations
    ADD CONSTRAINT fk_price_observations_watchlist_grain
    FOREIGN KEY (watch_id, route_id, airline_code, cabin, booking_window_days)
    REFERENCES watchlist (watch_id, route_id, airline_code, cabin, booking_window_days);

-- 5a. Composite unique on price_observations so detected_anomalies can
--     reference (id, watch_id) as a FK target.
ALTER TABLE price_observations
    ADD CONSTRAINT uq_price_observations_id_watch
    UNIQUE (id, watch_id);

-- 5b. Composite unique on baselines for the same reason.
ALTER TABLE baselines
    ADD CONSTRAINT uq_baselines_id_watch
    UNIQUE (id, watch_id);

-- 6a. Composite FK: detected_anomalies -> price_observations grain.
--     Ensures anomaly.watch_id == observation.watch_id.
ALTER TABLE detected_anomalies
    ADD CONSTRAINT fk_detected_anomalies_observation_grain
    FOREIGN KEY (price_observation_id, watch_id)
    REFERENCES price_observations (id, watch_id);

-- 6b. Composite FK: detected_anomalies -> baselines grain.
--     Ensures anomaly.watch_id == baseline.watch_id.
--     Together with 6a: observation and baseline must share the same watch.
ALTER TABLE detected_anomalies
    ADD CONSTRAINT fk_detected_anomalies_baseline_grain
    FOREIGN KEY (baseline_id, watch_id)
    REFERENCES baselines (id, watch_id);
