"""Detected Wave1 anomalies."""

from __future__ import annotations

import streamlit as st

from app.page_utils import (
    apply_common_filters,
    cached_query,
    configure_page,
    dataframe,
    database_url,
    empty_state,
    latest_timestamp,
    refresh_button,
    render_last_refreshed,
)

configure_page("Anomalies")
st.title("Anomalies")
refresh_button()

ANOMALIES_SQL = """
SELECT
    da.id,
    da.price_observation_id,
    da.baseline_id,
    da.watch_id,
    po.route_id,
    po.origin,
    po.destination,
    po.airline_code,
    po.cabin,
    po.booking_window_days,
    da.tier,
    da.current_price,
    da.baseline_price,
    da.currency,
    da.absolute_saving,
    da.percent_saving,
    da.confidence_score,
    da.status,
    da.detection_reason,
    da.detected_at
FROM detected_anomalies da
JOIN price_observations po ON po.id = da.price_observation_id
ORDER BY da.detected_at DESC, da.id DESC
LIMIT 500
"""

DETAIL_SQL = """
SELECT 'observation' AS record_type, row_to_json(po)::jsonb AS payload
FROM price_observations po
WHERE po.id = {observation_id}
UNION ALL
SELECT 'baseline' AS record_type, row_to_json(b)::jsonb AS payload
FROM baselines b
WHERE b.id = {baseline_id}
"""

df = cached_query(database_url(), ANOMALIES_SQL)
render_last_refreshed(latest_timestamp(df, ["detected_at"]))

if df.empty:
    empty_state(
        "No anomalies have been detected yet.",
        "Run `python scripts/run_detector.py` after baselines and observations are available.",
    )
else:
    filtered = apply_common_filters(df, tier=True, status=True, date_column="detected_at")
    if filtered.empty:
        st.info("No anomalies match the selected filters.")
        st.stop()
    dataframe(filtered)

    st.subheader("Related Records")
    selected_id = st.selectbox(
        "Anomaly",
        filtered["id"].tolist(),
        format_func=lambda value: f"Anomaly {value}",
    )
    selected = filtered[filtered["id"] == selected_id].iloc[0]
    detail_df = cached_query(
        database_url(),
        DETAIL_SQL.format(
            observation_id=int(selected["price_observation_id"]),
            baseline_id=int(selected["baseline_id"]),
        ),
    )
    for _, row in detail_df.iterrows():
        with st.expander(str(row["record_type"]).title(), expanded=True):
            st.json(row["payload"])
