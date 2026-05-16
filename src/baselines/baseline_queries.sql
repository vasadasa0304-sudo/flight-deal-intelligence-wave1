-- Wave1 30-day rolling median baseline stats.
-- Registered table: obs (price_observations columns for the window).
-- Called from baseline_job.py via duckdb.connect().

SELECT
    watch_id,
    route_id,
    origin,
    destination,
    airline_code,
    cabin,
    booking_window_days,
    native_currency,
    median(native_price)                                            AS median_price_native,
    min(native_price)                                               AS min_price_native,
    max(native_price)                                               AS max_price_native,
    quantile_cont(native_price, 0.25::DOUBLE)                      AS p25_price_native,
    quantile_cont(native_price, 0.75::DOUBLE)                      AS p75_price_native,
    quantile_cont(native_price, 0.75::DOUBLE)
        - quantile_cont(native_price, 0.25::DOUBLE)                AS iqr_price_native,
    count(*)                                                        AS observation_count
FROM obs
GROUP BY
    watch_id,
    route_id,
    origin,
    destination,
    airline_code,
    cabin,
    booking_window_days,
    native_currency
