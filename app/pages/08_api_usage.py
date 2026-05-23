"""API usage and quota monitoring."""

from __future__ import annotations

import streamlit as st

from app.page_utils import (
    cached_query,
    configure_page,
    dataframe,
    database_url,
    empty_state,
    latest_timestamp,
    refresh_button,
    render_last_refreshed,
    sidebar_date_range_filter,
)

configure_page("API Usage")
st.title("API Usage")
refresh_button()

SQL = """
WITH today AS (
    SELECT date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS start_at
)
SELECT
    provider,
    count(*) AS calls_today,
    round(
        100.0 * count(*) FILTER (WHERE success)
        / NULLIF(count(*), 0),
        2
    ) AS success_rate,
    count(*) FILTER (WHERE status_code = 429) AS count_429,
    COALESCE(sum(estimated_cost_usd), 0) AS estimated_cost,
    'Pending Prompt 16' AS quota_remaining,
    max(requested_at) AS last_refreshed
FROM api_request_logs, today
WHERE requested_at >= today.start_at
GROUP BY provider
ORDER BY provider
"""

df = cached_query(database_url(), SQL)
render_last_refreshed(latest_timestamp(df, ["last_refreshed"]))

if df.empty:
    empty_state(
        "No provider calls have been logged yet.",
        "API logs are populated by Amadeus, Duffel, and FX client calls.",
    )
else:
    filtered = sidebar_date_range_filter(df, "last_refreshed")
    dataframe(filtered.drop(columns=["last_refreshed"], errors="ignore"))
