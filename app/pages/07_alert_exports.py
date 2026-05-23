"""Ready alert exports."""

from __future__ import annotations

from datetime import UTC, datetime

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
    write_session,
)
from src.reporting.alert_formatter import format_alert_markdown
from src.reporting.exports import export_ready_alerts, promote_to_alerts

configure_page("Alert Exports")
st.title("Alert Exports")
refresh_button()

SQL = """
SELECT
    id,
    anomaly_id,
    tier,
    origin,
    destination,
    airline_code,
    cabin,
    fare_native,
    native_currency,
    fare_display,
    display_currency,
    baseline_price,
    absolute_saving,
    percent_saving,
    booking_link,
    valid_window,
    urgency_flag,
    verification_notes,
    visibility,
    status,
    created_at
FROM alerts
WHERE status = 'READY'
ORDER BY created_at ASC, id ASC
"""

df = cached_query(database_url(), SQL)
render_last_refreshed(latest_timestamp(df, ["created_at"]))

col1, col2 = st.columns(2)
if col1.button("Promote verified anomalies", width="stretch"):
    with write_session() as session:
        promoted = promote_to_alerts(session)
    st.cache_data.clear()
    st.success(f"Promoted {promoted} alert(s).")
    st.rerun()

if col2.button("Export to CSV", width="stretch"):
    with write_session() as session:
        result = export_ready_alerts(session, generated_at=datetime.now(UTC))
    st.cache_data.clear()
    st.success(f"Exported {result.row_count} alert(s) to {result.path}.")
    if result.path.exists():
        st.download_button(
            "Download CSV",
            data=result.path.read_bytes(),
            file_name=result.path.name,
            mime="text/csv",
        )

if df.empty:
    empty_state(
        "No READY alerts are waiting to export.",
        "Run `python scripts/run_verifier.py`, then `python scripts/export_alerts.py` or use the promote button here.",
    )
else:
    filtered = apply_common_filters(df, tier=True, status=True, date_column="created_at")
    dataframe(filtered)

    st.subheader("Markdown Copy Blocks")
    for _, row in filtered.iterrows():
        label = f"{row['tier']} {row['origin']}->{row['destination']} {row['airline_code']} {row['cabin']}"
        if st.button(f"Copy Markdown block: alert {row['id']}", key=f"md-{row['id']}"):
            st.session_state["alert_markdown"] = format_alert_markdown(row.to_dict())
            st.session_state["alert_markdown_label"] = label
    if "alert_markdown" in st.session_state:
        st.caption(st.session_state.get("alert_markdown_label", "Selected alert"))
        st.code(st.session_state["alert_markdown"], language="markdown")
