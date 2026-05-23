"""Wave1 active watchlist."""

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

configure_page("Watchlist")
st.title("Watchlist")
refresh_button()

SQL = """
SELECT
    w.route_id,
    r.origin,
    r.destination,
    w.airline_code,
    a.airline_name,
    a.carrier_type,
    r.route_priority,
    string_agg(DISTINCT w.booking_window_days::text, ', ' ORDER BY w.booking_window_days::text)
        AS booking_windows_present,
    string_agg(DISTINCT w.cabin, ', ' ORDER BY w.cabin) AS cabins_present,
    r.strategic_tag,
    'PENDING' AS live_schedule_validation,
    max(w.updated_at) AS last_refreshed
FROM watchlist w
JOIN routes r ON r.route_id = w.route_id
JOIN airlines a ON a.airline_code = w.airline_code
WHERE w.is_active
GROUP BY
    w.route_id, r.origin, r.destination, w.airline_code, a.airline_name,
    a.carrier_type, r.route_priority, r.strategic_tag
ORDER BY r.route_priority, w.route_id, w.airline_code
"""

df = cached_query(database_url(), SQL)
render_last_refreshed(latest_timestamp(df, ["last_refreshed"]))

if df.empty:
    empty_state(
        "The active watchlist has no rows.",
        "Run `python scripts/load_seed_data.py` after loading the schema.",
    )
else:
    filtered = apply_common_filters(df, cabin=False, booking_window=False)
    dataframe(filtered.drop(columns=["last_refreshed"], errors="ignore"))
