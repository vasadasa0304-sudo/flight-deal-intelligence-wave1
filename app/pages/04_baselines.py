"""Current Wave1 baseline snapshots."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.page_utils import (
    apply_common_filters,
    cached_query,
    configure_page,
    database_url,
    empty_state,
    latest_timestamp,
    refresh_button,
    render_last_refreshed,
)

configure_page("Baselines")
st.title("Baselines")
refresh_button()

SQL = """
WITH ranked AS (
    SELECT
        b.*,
        row_number() OVER (
            PARTITION BY b.watch_id
            ORDER BY b.baseline_date DESC, b.created_at DESC, b.id DESC
        ) AS rn
    FROM baselines b
)
SELECT
    route_id,
    origin,
    destination,
    airline_code,
    cabin,
    booking_window_days,
    native_currency,
    baseline_date,
    median_price_native AS median,
    p25_price_native AS p25,
    p75_price_native AS p75,
    iqr_price_native AS iqr,
    observation_count,
    baseline_health,
    created_at
FROM ranked
WHERE rn = 1
ORDER BY baseline_health, route_id, airline_code, cabin, booking_window_days
"""

df = cached_query(database_url(), SQL)
render_last_refreshed(latest_timestamp(df, ["created_at", "baseline_date"]))

if df.empty:
    empty_state(
        "No baseline snapshots exist yet.",
        "Run `python scripts/build_baselines.py` after observations are available.",
    )
else:
    filtered = apply_common_filters(df, date_column="baseline_date")

    def color_health(value: object) -> str:
        if value == "GOOD":
            return "background-color: #d1fadf"
        if value == "THIN":
            return "background-color: #fef3c7"
        if value in {"MISSING", "OUTLIER_RISK"}:
            return "background-color: #fee2e2"
        return ""

    styled = filtered.drop(columns=["created_at"], errors="ignore").style.map(
        color_health,
        subset=pd.IndexSlice[:, ["baseline_health"]],
    )
    st.dataframe(styled, width="stretch", hide_index=True)
