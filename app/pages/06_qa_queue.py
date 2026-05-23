"""Manual QA queue for detected and escalated anomalies."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.page_utils import (
    apply_common_filters,
    cached_query,
    cached_query_params,
    configure_page,
    dataframe,
    database_url,
    empty_state,
    latest_timestamp,
    refresh_button,
    render_last_refreshed,
    write_session,
)
from src.verification.qa_rules import passes_phantom_two_source_rule

configure_page("QA Queue")
st.title("QA Queue")
refresh_button()

QUEUE_SQL = """
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
WHERE da.status IN ('DETECTED', 'ESCALATED')
ORDER BY da.detected_at ASC, da.id ASC
"""

HISTORY_SQL = """
SELECT observed_at, native_price
FROM price_observations
WHERE watch_id = :watch_id
  AND observed_at >= now() - INTERVAL '30 days'
ORDER BY observed_at ASC
"""

QA_STATE_SQL = """
SELECT
    verification_source,
    result,
    verified_price,
    verified_currency,
    notes,
    checked_at
FROM qa_checks
WHERE anomaly_id = :anomaly_id
ORDER BY checked_at DESC, id DESC
"""


def _parse_decimal(raw_value: str) -> Decimal | None:
    if not raw_value.strip():
        return None
    try:
        return Decimal(raw_value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Verified price must be a valid decimal number.") from exc


def _write_manual_qa(
    *,
    anomaly: dict[str, Any],
    outcome: str,
    verified_price: Decimal | None,
    verified_currency: str | None,
    notes: str | None,
    restrictions: str | None,
    external_source_verified: bool,
) -> str:
    anomaly_id = int(anomaly["id"])
    with write_session() as session:
        session.execute(
            text(
                """
                INSERT INTO qa_checks (
                    anomaly_id, verification_source, verified_price,
                    verified_currency, result, notes, restrictions,
                    external_source_verified, checked_by
                )
                VALUES (
                    :anomaly_id, 'MANUAL', :verified_price,
                    :verified_currency, :result, :notes, :restrictions,
                    :external_source_verified, 'streamlit'
                )
                """
            ),
            {
                "anomaly_id": anomaly_id,
                "verified_price": verified_price,
                "verified_currency": verified_currency,
                "result": outcome,
                "notes": notes,
                "restrictions": restrictions,
                "external_source_verified": external_source_verified,
            },
        )

        if outcome == "REJECTED":
            new_status = "REJECTED"
        elif outcome == "ESCALATED":
            new_status = "ESCALATED"
        elif anomaly["tier"] == "PHANTOM_FARE":
            new_status = "VERIFIED" if passes_phantom_two_source_rule(anomaly_id, session) else "DETECTED"
        else:
            new_status = "VERIFIED"

        session.execute(
            text("UPDATE detected_anomalies SET status = :status WHERE id = :id"),
            {"status": new_status, "id": anomaly_id},
        )
        return new_status


df = cached_query(database_url(), QUEUE_SQL)
render_last_refreshed(latest_timestamp(df, ["detected_at"]))

if df.empty:
    empty_state(
        "The QA queue is empty.",
        "Run `python scripts/run_verifier.py` or submit manual QA after detection creates anomalies.",
    )
else:
    filtered = apply_common_filters(df, tier=True, status=True, date_column="detected_at")
    if filtered.empty:
        st.info("No QA queue rows match the selected filters.")
        st.stop()
    dataframe(filtered)

    selected_id = st.selectbox(
        "Selected anomaly",
        filtered["id"].tolist(),
        format_func=lambda value: f"Anomaly {value}",
    )
    selected = filtered[filtered["id"] == selected_id].iloc[0].to_dict()

    st.subheader("Anomaly Summary")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Tier", selected["tier"])
    summary_cols[1].metric("Current", f"{selected['currency']} {selected['current_price']}")
    summary_cols[2].metric("Saving", f"{selected['percent_saving']}%")
    summary_cols[3].metric("Status", selected["status"])
    st.caption(str(selected.get("detection_reason") or ""))

    history_df = cached_query_params(database_url(), HISTORY_SQL, watch_id=int(selected["watch_id"]))
    st.subheader("30-Day Native Price History")
    if history_df.empty:
        st.info("No recent price history for this watch row yet.")
    else:
        chart_df = history_df.copy()
        chart_df["observed_at"] = pd.to_datetime(chart_df["observed_at"], utc=True)
        st.line_chart(chart_df.set_index("observed_at")["native_price"])

    qa_state = cached_query_params(database_url(), QA_STATE_SQL, anomaly_id=int(selected_id))
    if selected["tier"] == "PHANTOM_FARE":
        st.subheader("Phantom Fare Verification State")
        with write_session() as session:
            rule_passes = passes_phantom_two_source_rule(int(selected_id), session)
        st.write(f"Two-source or approved manual path satisfied: `{rule_passes}`")
        if qa_state.empty:
            st.caption("No QA checks recorded yet.")
        else:
            dataframe(qa_state)

    st.subheader("Verify")
    with st.form(f"qa-form-{selected_id}"):
        outcome = st.selectbox("Outcome", ["CONFIRMED", "REJECTED", "ESCALATED"])
        verified_price_input = st.text_input("Verified price")
        verified_currency = st.text_input("Verified currency", value=str(selected["currency"]))
        notes = st.text_area("Notes")
        restrictions = st.text_area("Restrictions")
        external_source_verified = st.checkbox(
            "External source verified",
            help="Tick only if you confirmed this fare via an external channel (airline site, GDS, etc). Required to satisfy the Phantom Fare manual override path.",
        )
        submitted = st.form_submit_button("Submit QA result")

    if submitted:
        try:
            verified_price = _parse_decimal(verified_price_input)
            new_status = _write_manual_qa(
                anomaly=dict(selected),
                outcome=outcome,
                verified_price=verified_price,
                verified_currency=verified_currency.strip().upper() or None,
                notes=notes.strip() or None,
                restrictions=restrictions.strip() or None,
                external_source_verified=external_source_verified,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.cache_data.clear()
            st.success(f"QA saved. Anomaly status is now {new_status}.")
            st.rerun()
