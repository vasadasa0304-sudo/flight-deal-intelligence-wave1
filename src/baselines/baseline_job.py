"""30-day rolling median baseline placeholders."""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def compute_rolling_median_baselines(observations: pd.DataFrame) -> pd.DataFrame:
    """Compute placeholder 30-day median baselines from an observations frame."""
    if observations.empty:
        logger.info("No observations available for baseline computation.")
        return pd.DataFrame()

    required_columns = {
        "route_key",
        "cabin",
        "booking_window_days",
        "observed_at",
        "currency",
        "total_amount",
    }
    missing_columns = required_columns - set(observations.columns)
    if missing_columns:
        raise ValueError(f"Missing baseline columns: {sorted(missing_columns)}")

    logger.info("Computing placeholder rolling median baselines.")
    query = """
        select
            route_key,
            cabin,
            booking_window_days,
            currency,
            median(total_amount) as median_amount,
            count(*) as observation_count
        from observations
        group by route_key, cabin, booking_window_days, currency
    """
    return duckdb.sql(query).df()

