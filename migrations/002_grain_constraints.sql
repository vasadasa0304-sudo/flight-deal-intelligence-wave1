-- 002_grain_constraints.sql
-- Add grain-consistency constraints to prevent observations, baselines,
-- and detected anomalies from referencing mismatched watchlist rows.
--
-- Problem: price_observations and baselines each carry denormalised copies
-- of (route_id, airline_code, cabin, booking_window_days) alongside a
-- watch_id FK, but nothing in the schema proved these matched.
-- detected_anomalies referenced price_observation_id, baseline_id, and
-- watch_id via three independent FKs, allowing cross-grain pairings.
--
-- Fix strategy:
--   1. Add a composite UNIQUE on watchlist so the grain tuple can serve as
--      a FK target (watch_id alone is PK; the composite is needed for FK
--      syntax; the redundancy is intentional).
--   2. Add FK from baselines.route_id to routes (was unvalidated TEXT).
--   3. Add composite FKs from price_observations and baselines to the
--      watchlist grain tuple, banning mismatched denormalised fields.
--   4. Add UNIQUE(id, watch_id) on price_observations and baselines so
--      detected_anomalies can use them as composite FK targets.
--   5. Add composite FKs on detected_anomalies so
--      price_observation.watch_id == baseline.watch_id == anomaly.watch_id.

-- 1. Composite unique on watchlist — FK target for grain checks.
alter table watchlist
    add constraint uq_watchlist_grain
    unique (watch_id, route_id, airline_code, cabin, booking_window_days);

-- 2. Promote baselines.route_id from bare TEXT to a validated FK.
alter table baselines
    add constraint fk_baselines_route_id
    foreign key (route_id) references routes (route_id);

-- 3a. Composite FK: baselines -> watchlist grain.
--     Ensures every baseline's denormalised fields match its watch row.
alter table baselines
    add constraint fk_baselines_watchlist_grain
    foreign key (watch_id, route_id, airline_code, cabin, booking_window_days)
    references watchlist (watch_id, route_id, airline_code, cabin, booking_window_days);

-- 3b. Composite FK: price_observations -> watchlist grain.
--     Ensures every observation's denormalised fields match its watch row.
alter table price_observations
    add constraint fk_price_observations_watchlist_grain
    foreign key (watch_id, route_id, airline_code, cabin, booking_window_days)
    references watchlist (watch_id, route_id, airline_code, cabin, booking_window_days);

-- 4a. Composite unique on price_observations — FK target for anomaly check.
alter table price_observations
    add constraint uq_price_observations_id_watch
    unique (id, watch_id);

-- 4b. Composite unique on baselines — FK target for anomaly check.
alter table baselines
    add constraint uq_baselines_id_watch
    unique (id, watch_id);

-- 5a. Composite FK: detected_anomalies -> price_observations grain.
--     Ensures anomaly.watch_id == the observation's watch_id.
alter table detected_anomalies
    add constraint fk_detected_anomalies_observation_grain
    foreign key (price_observation_id, watch_id)
    references price_observations (id, watch_id);

-- 5b. Composite FK: detected_anomalies -> baselines grain.
--     Ensures anomaly.watch_id == the baseline's watch_id.
--     Together with 5a this means observation and baseline share the same watch.
alter table detected_anomalies
    add constraint fk_detected_anomalies_baseline_grain
    foreign key (baseline_id, watch_id)
    references baselines (id, watch_id);
