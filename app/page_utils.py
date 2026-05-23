"""Shared Streamlit helpers for the Wave1 internal dashboard."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import load_settings
from src.db_helpers import get_engine

READ_TTL_SECONDS = 60


def configure_page(title: str) -> None:
    """Apply common Streamlit page settings."""
    st.set_page_config(page_title=f"{title} - Wave1 Ops", layout="wide")


def database_url() -> str:
    """Return the configured application database URL."""
    return load_settings().database_url


@st.cache_data(ttl=READ_TTL_SECONDS, show_spinner=False)
def cached_query(database_url_value: str, sql: str) -> pd.DataFrame:
    """Run a cached read-only query and return a DataFrame."""
    engine = get_engine(load_settings())
    try:
        with Session(engine) as session:
            return pd.read_sql_query(text(sql), session.connection())
    finally:
        engine.dispose()


@st.cache_data(ttl=READ_TTL_SECONDS, show_spinner=False)
def cached_query_params(database_url_value: str, sql: str, **params: Any) -> pd.DataFrame:
    """Run a cached parameterised read-only query and return a DataFrame."""
    engine = get_engine(load_settings())
    try:
        with Session(engine) as session:
            return pd.read_sql_query(text(sql), session.connection(), params=params)
    finally:
        engine.dispose()


@contextmanager
def write_session() -> Iterator[Session]:
    """Open one transactional SQLAlchemy session for a Streamlit write action."""
    engine = get_engine(load_settings())
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def refresh_button() -> None:
    """Render a sidebar refresh button that clears cached read data."""
    if st.sidebar.button("Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()


def render_last_refreshed(value: Any) -> None:
    """Render the required UTC last-refreshed line."""
    if value is None or pd.isna(value):
        st.caption("Last refreshed: No data yet")
        return
    timestamp = pd.to_datetime(value, utc=True)
    st.caption(f"Last refreshed: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")


def latest_timestamp(df: pd.DataFrame, columns: Iterable[str]) -> Any:
    """Return the latest timestamp across candidate columns in a DataFrame."""
    values = []
    for column in columns:
        if column in df.columns and not df[column].dropna().empty:
            values.append(pd.to_datetime(df[column], utc=True, errors="coerce").max())
    values = [value for value in values if pd.notna(value)]
    return max(values) if values else None


def empty_state(message: str, hint: str) -> None:
    """Show a practical empty state."""
    st.info(f"No data yet. {message}")
    st.caption(hint)


def sidebar_multiselect_filter(
    df: pd.DataFrame,
    column: str,
    label: str | None = None,
) -> pd.DataFrame:
    """Apply a sidebar multiselect filter when a column exists."""
    if column not in df.columns or df.empty:
        return df
    values = sorted(value for value in df[column].dropna().unique().tolist())
    if not values:
        return df
    selected = st.sidebar.multiselect(label or column, values)
    if selected:
        return df[df[column].isin(selected)]
    return df


def sidebar_date_range_filter(
    df: pd.DataFrame,
    column: str,
    label: str = "Date range",
) -> pd.DataFrame:
    """Apply a sidebar date range filter for timestamp/date columns."""
    if column not in df.columns or df.empty:
        return df
    timestamps = pd.to_datetime(df[column], utc=True, errors="coerce")
    valid = timestamps.dropna()
    if valid.empty:
        return df
    start = valid.min().date()
    end = valid.max().date()
    selected = st.sidebar.date_input(label, value=(start, end))
    if not isinstance(selected, tuple) or len(selected) != 2:
        return df
    start_date, end_date = selected
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        return df
    mask = (timestamps.dt.date >= start_date) & (timestamps.dt.date <= end_date)
    return df[mask]


def apply_common_filters(
    df: pd.DataFrame,
    *,
    route: bool = True,
    origin: bool = True,
    destination: bool = True,
    airline: bool = True,
    cabin: bool = True,
    booking_window: bool = True,
    tier: bool = False,
    status: bool = False,
    date_column: str | None = None,
) -> pd.DataFrame:
    """Apply common Wave1 sidebar filters to a DataFrame."""
    filtered = df
    if route:
        filtered = sidebar_multiselect_filter(filtered, "route_id", "Route")
    if origin:
        filtered = sidebar_multiselect_filter(filtered, "origin", "Origin")
    if destination:
        filtered = sidebar_multiselect_filter(filtered, "destination", "Destination")
    if airline:
        filtered = sidebar_multiselect_filter(filtered, "airline_code", "Airline")
    if cabin:
        filtered = sidebar_multiselect_filter(filtered, "cabin", "Cabin")
    if booking_window:
        filtered = sidebar_multiselect_filter(
            filtered,
            "booking_window_days",
            "Booking window",
        )
    if tier:
        filtered = sidebar_multiselect_filter(filtered, "tier", "Tier")
    if status:
        filtered = sidebar_multiselect_filter(filtered, "status", "Status")
    if date_column:
        filtered = sidebar_date_range_filter(filtered, date_column)
    return filtered


def dataframe(df: pd.DataFrame) -> None:
    """Render a standard full-width DataFrame."""
    st.dataframe(df, width="stretch", hide_index=True)
