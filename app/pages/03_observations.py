"""Latest append-only fare observations."""

from __future__ import annotations

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from page_utils import (
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

configure_page("Observations")
st.title("Observations")
refresh_button()

SQL = """
SELECT
    id,
    watch_id,
    route_id,
    origin,
    destination,
    airline_code,
    cabin,
    booking_window_days,
    departure_date,
    native_currency,
    native_price,
    display_currency,
    display_price,
    source,
    polling_bucket_hour,
    observed_at,
    created_at
FROM price_observations
ORDER BY observed_at DESC, id DESC
LIMIT 500
"""

df = cached_query(database_url(), SQL)
render_last_refreshed(latest_timestamp(df, ["observed_at", "created_at"]))

if df.empty:
    empty_state(
        "No fare observations have been collected yet.",
        "Run `python scripts/run_scheduler.py --once` after seed data is loaded.",
    )
else:
    filtered = apply_common_filters(df, date_column="observed_at")
    dataframe(filtered)
