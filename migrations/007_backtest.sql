-- Backtest mirror tables.
-- bt_baselines and bt_detected_anomalies share the production column shape
-- without cross-referencing production rows (no FK to baselines/detected_anomalies).
-- bt_synthetic_observations holds injected fares for Pass-2 synthetic mode.
-- All three tables are TRUNCATED at the start of each backtest run.

CREATE TABLE IF NOT EXISTS bt_baselines (
    id                  bigserial    PRIMARY KEY,
    watch_id            bigint       NOT NULL,
    route_id            text         NOT NULL,
    origin              char(3)      NOT NULL,
    destination         char(3)      NOT NULL,
    airline_code        varchar(3)   NOT NULL,
    cabin               text         NOT NULL,
    booking_window_days integer      NOT NULL,
    native_currency     char(3)      NOT NULL,
    baseline_date       date         NOT NULL,
    window_start_date   date         NOT NULL,
    window_end_date     date         NOT NULL,
    median_price_native numeric(12, 2) NOT NULL,
    min_price_native    numeric(12, 2) NOT NULL,
    max_price_native    numeric(12, 2) NOT NULL,
    p25_price_native    numeric(12, 2) NOT NULL,
    p75_price_native    numeric(12, 2) NOT NULL,
    iqr_price_native    numeric(12, 2) NOT NULL,
    observation_count   integer      NOT NULL,
    baseline_health     text         NOT NULL,
    created_at          timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT bt_ck_baselines_health CHECK (
        baseline_health IN ('GOOD', 'THIN', 'MISSING', 'OUTLIER_RISK')
    ),
    CONSTRAINT bt_uq_baselines_watch_date UNIQUE (watch_id, baseline_date)
);

-- No UNIQUE constraint: tables are truncated before each run so dedup is unnecessary.
CREATE TABLE IF NOT EXISTS bt_detected_anomalies (
    id                   bigserial    PRIMARY KEY,
    price_observation_id bigint       NOT NULL,
    baseline_id          bigint       NOT NULL,
    watch_id             bigint       NOT NULL,
    tier                 text         NOT NULL,
    current_price        numeric(12, 2) NOT NULL,
    baseline_price       numeric(12, 2) NOT NULL,
    currency             char(3)      NOT NULL,
    absolute_saving      numeric(12, 2) NOT NULL,
    percent_saving       numeric(6, 2)  NOT NULL,
    confidence_score     numeric(4, 3)  NOT NULL,
    detection_reason     text,
    threshold_set        text         NOT NULL,
    status               text         NOT NULL DEFAULT 'DETECTED',
    is_synthetic         boolean      NOT NULL DEFAULT false,
    detected_at          timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT bt_ck_anomalies_tier CHECK (
        tier IN ('DEAL', 'FLASH_DEAL', 'PHANTOM_FARE')
    ),
    CONSTRAINT bt_ck_anomalies_confidence CHECK (
        confidence_score BETWEEN 0 AND 1
    ),
    CONSTRAINT bt_ck_anomalies_threshold_set CHECK (
        threshold_set IN ('SOW', 'LCC_EXPERIMENTAL')
    ),
    CONSTRAINT bt_ck_anomalies_status CHECK (
        status IN ('DETECTED', 'VERIFIED', 'REJECTED', 'EXPORTED', 'ESCALATED')
    )
);

CREATE TABLE IF NOT EXISTS bt_synthetic_observations (
    id                  bigserial    PRIMARY KEY,
    watch_id            bigint       NOT NULL,
    route_id            text         NOT NULL,
    origin              char(3)      NOT NULL,
    destination         char(3)      NOT NULL,
    airline_code        varchar(3)   NOT NULL,
    cabin               text         NOT NULL,
    booking_window_days integer      NOT NULL,
    departure_date      date         NOT NULL,
    native_currency     char(3)      NOT NULL,
    native_price        numeric(12, 2) NOT NULL,
    display_currency    char(3)      NOT NULL,
    display_price       numeric(12, 2) NOT NULL,
    source              text         NOT NULL DEFAULT 'SYNTHETIC',
    observed_at         timestamptz  NOT NULL,
    raw_response        jsonb        NOT NULL DEFAULT '{}',
    created_at          timestamptz  NOT NULL DEFAULT now(),
    injected_tier       text         NOT NULL,
    injected_saving_pct numeric(6, 2) NOT NULL,
    CONSTRAINT bt_ck_synthetic_tier CHECK (
        injected_tier IN ('DEAL', 'FLASH_DEAL', 'PHANTOM_FARE')
    ),
    CONSTRAINT bt_ck_synthetic_price CHECK (native_price >= 0)
);
