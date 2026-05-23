"""API usage and quota monitoring."""

from __future__ import annotations

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from page_utils import (
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
    arl.provider,
    count(*) AS calls_today,
    round(
        100.0 * count(*) FILTER (WHERE arl.success)
        / NULLIF(count(*), 0),
        2
    ) AS success_rate,
    count(*) FILTER (WHERE arl.status_code = 429) AS count_429,
    COALESCE(sum(arl.estimated_cost_usd), 0) AS estimated_cost,
    pb.daily_call_hard_limit AS quota_hard_limit,
    CASE
        WHEN pb.daily_call_hard_limit IS NOT NULL
        THEN GREATEST(0, pb.daily_call_hard_limit - count(*))
        ELSE NULL
    END AS quota_remaining,
    max(arl.requested_at) AS last_refreshed
FROM api_request_logs arl
CROSS JOIN today
LEFT JOIN provider_budgets pb ON pb.provider = arl.provider
WHERE arl.requested_at >= today.start_at
GROUP BY arl.provider, pb.daily_call_hard_limit
ORDER BY arl.provider
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
