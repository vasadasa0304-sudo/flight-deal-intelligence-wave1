"""Wave1 operations overview."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.page_utils import cached_query, configure_page, database_url, render_last_refreshed

configure_page("Overview")
st.title("Overview")
st.caption("Current Wave1 operating totals from PostgreSQL.")

SQL = """
WITH bounds AS (
    SELECT date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS today_start
),
overview AS (
    SELECT
        (SELECT count(*) FROM routes WHERE is_active) AS active_routes,
        (SELECT count(*) FROM watchlist WHERE is_active) AS active_watchlist_rows,
        (
            SELECT count(*)
            FROM price_observations, bounds
            WHERE observed_at >= bounds.today_start
        ) AS observations_today,
        (
            SELECT count(*)
            FROM detected_anomalies, bounds
            WHERE detected_at >= bounds.today_start
        ) AS anomalies_detected_today,
        (
            SELECT count(*)
            FROM qa_checks, bounds
            WHERE checked_at >= bounds.today_start
              AND result = 'CONFIRMED'
        ) AS alerts_confirmed_today,
        (
            SELECT count(*)
            FROM qa_checks, bounds
            WHERE checked_at >= bounds.today_start
              AND result = 'REJECTED'
        ) AS alerts_rejected_today,
        (
            SELECT count(*)
            FROM api_request_logs, bounds
            WHERE requested_at >= bounds.today_start
        ) AS api_calls_today,
        (
            SELECT count(*)
            FROM api_request_logs, bounds
            WHERE requested_at >= bounds.today_start
              AND status_code = 429
        ) AS quota_warnings,
        GREATEST(
            COALESCE((SELECT max(updated_at) FROM watchlist), TIMESTAMPTZ 'epoch'),
            COALESCE((SELECT max(observed_at) FROM price_observations), TIMESTAMPTZ 'epoch'),
            COALESCE((SELECT max(detected_at) FROM detected_anomalies), TIMESTAMPTZ 'epoch'),
            COALESCE((SELECT max(checked_at) FROM qa_checks), TIMESTAMPTZ 'epoch'),
            COALESCE((SELECT max(created_at) FROM alerts), TIMESTAMPTZ 'epoch'),
            COALESCE((SELECT max(requested_at) FROM api_request_logs), TIMESTAMPTZ 'epoch')
        ) AS last_refreshed
)
SELECT *
FROM overview
"""

df = cached_query(database_url(), SQL)
row = df.iloc[0] if not df.empty else pd.Series(dtype=object)
last_refreshed = None if df.empty or pd.to_datetime(row["last_refreshed"], utc=True).year == 1970 else row["last_refreshed"]
render_last_refreshed(last_refreshed)

metrics = [
    ("Active Wave1 routes", row.get("active_routes", 0)),
    ("Active watchlist rows", row.get("active_watchlist_rows", 0)),
    ("Observations today", row.get("observations_today", 0)),
    ("Anomalies detected today", row.get("anomalies_detected_today", 0)),
    ("Alerts confirmed today", row.get("alerts_confirmed_today", 0)),
    ("Alerts rejected today", row.get("alerts_rejected_today", 0)),
    ("API calls today", row.get("api_calls_today", 0)),
    ("Quota warnings", row.get("quota_warnings", 0)),
]

for offset in range(0, len(metrics), 4):
    columns = st.columns(4)
    for column, (label, value) in zip(columns, metrics[offset : offset + 4], strict=False):
        column.metric(label, int(value or 0))
