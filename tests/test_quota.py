"""Tests for Wave1 API quota and cost controls."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.clients.quota import (
    QUOTA_HARD_LIMIT,
    QUOTA_OK,
    QUOTA_THROTTLE_95,
    QUOTA_WARN_80,
    get_provider_usage,
    quota_status,
)

_PROVIDER = "TEST_PROVIDER"
_DATE = date(2026, 5, 17)
_START_AT = datetime(_DATE.year, _DATE.month, _DATE.day, 0, 0, 0, tzinfo=UTC)


@pytest.fixture()
def quota_engine(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    engine, _schema = pg_schema_engine
    _clear_rows(engine)
    try:
        yield engine
    finally:
        _clear_rows(engine)


# --------------------------------------------------------------------------- #
# get_provider_usage
# --------------------------------------------------------------------------- #


def test_get_provider_usage_returns_zero_counts_when_no_logs(
    quota_engine: Engine,
) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=1000, daily_call_hard_limit=2000)

    with Session(quota_engine) as session:
        usage = get_provider_usage(session, _PROVIDER, _DATE)

    assert usage["calls_today"] == 0
    assert usage["successful"] == 0
    assert usage["failed"] == 0
    assert usage["errors_429"] == 0
    assert usage["estimated_cost_usd"] == Decimal("0")


def test_get_provider_usage_counts_successful_and_failed(
    quota_engine: Engine,
) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=1000, daily_call_hard_limit=2000)
    _insert_logs(
        quota_engine, _PROVIDER, count=3,
        success=True, requested_at=_START_AT + timedelta(hours=1),
    )
    _insert_logs(
        quota_engine, _PROVIDER, count=1,
        success=False, status_code=429, requested_at=_START_AT + timedelta(hours=2),
    )

    with Session(quota_engine) as session:
        usage = get_provider_usage(session, _PROVIDER, _DATE)

    assert usage["calls_today"] == 4
    assert usage["successful"] == 3
    assert usage["failed"] == 1
    assert usage["errors_429"] == 1


def test_get_provider_usage_excludes_logs_from_other_dates(
    quota_engine: Engine,
) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=1000, daily_call_hard_limit=2000)
    yesterday = _START_AT - timedelta(hours=1)
    _insert_logs(quota_engine, _PROVIDER, count=50, success=True, requested_at=yesterday)

    with Session(quota_engine) as session:
        usage = get_provider_usage(session, _PROVIDER, _DATE)

    assert usage["calls_today"] == 0


def test_get_provider_usage_raises_for_unknown_provider(
    quota_engine: Engine,
) -> None:
    with Session(quota_engine) as session:
        with pytest.raises(ValueError, match="No provider budget configured"):
            get_provider_usage(session, "UNKNOWN_PROVIDER", _DATE)


# --------------------------------------------------------------------------- #
# quota_status — call-count bands
# --------------------------------------------------------------------------- #


def test_quota_status_ok_with_no_calls(quota_engine: Engine) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=800, daily_call_hard_limit=1000)

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_OK


def test_quota_status_warn_80_at_exactly_80_percent(quota_engine: Engine) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=80, daily_call_hard_limit=100)
    _insert_logs(quota_engine, _PROVIDER, count=80)

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_WARN_80


def test_quota_status_throttle_95_at_exactly_95_percent(quota_engine: Engine) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=80, daily_call_hard_limit=100)
    _insert_logs(quota_engine, _PROVIDER, count=95)

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_THROTTLE_95


def test_quota_status_hard_limit_at_exactly_100_percent(quota_engine: Engine) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=80, daily_call_hard_limit=100)
    _insert_logs(quota_engine, _PROVIDER, count=100)

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_HARD_LIMIT


def test_quota_status_hard_limit_above_100_percent(quota_engine: Engine) -> None:
    _seed_budget(quota_engine, _PROVIDER, daily_call_soft_limit=80, daily_call_hard_limit=100)
    _insert_logs(quota_engine, _PROVIDER, count=105)

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_HARD_LIMIT


# --------------------------------------------------------------------------- #
# quota_status — cost-limit path
# --------------------------------------------------------------------------- #


def test_quota_status_cost_triggers_warn_80(quota_engine: Engine) -> None:
    """Cost at 80% of hard limit while call count is low → WARN_80."""
    _seed_budget(
        quota_engine, _PROVIDER,
        daily_call_soft_limit=800, daily_call_hard_limit=1000,
        cost_soft_limit_usd=Decimal("8.00"), cost_hard_limit_usd=Decimal("10.00"),
    )
    # 10 calls (1% of 1000) but $0.80 each → total $8.00 = 80% of hard limit
    _insert_logs(quota_engine, _PROVIDER, count=10, cost_usd=Decimal("0.80"))

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_WARN_80


def test_quota_status_cost_triggers_hard_limit(quota_engine: Engine) -> None:
    """Cost at 100% of hard limit → HARD_LIMIT regardless of call count."""
    _seed_budget(
        quota_engine, _PROVIDER,
        daily_call_soft_limit=800, daily_call_hard_limit=1000,
        cost_soft_limit_usd=Decimal("8.00"), cost_hard_limit_usd=Decimal("10.00"),
    )
    # 5 calls (0.5% of 1000) but $2.00 each → total $10.00 = exactly the hard limit
    _insert_logs(quota_engine, _PROVIDER, count=5, cost_usd=Decimal("2.00"))

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_HARD_LIMIT


def test_quota_status_returns_max_of_call_and_cost_status(quota_engine: Engine) -> None:
    """Call band is WARN_80, cost band is HARD_LIMIT → result is HARD_LIMIT."""
    _seed_budget(
        quota_engine, _PROVIDER,
        daily_call_soft_limit=80, daily_call_hard_limit=100,
        cost_soft_limit_usd=Decimal("8.00"), cost_hard_limit_usd=Decimal("10.00"),
    )
    # 82 calls → WARN_80 on call path; one extra log carries $10.10 cost → HARD_LIMIT on cost path
    _insert_logs(quota_engine, _PROVIDER, count=82)
    _insert_logs(quota_engine, _PROVIDER, count=1, cost_usd=Decimal("10.10"))

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_HARD_LIMIT


def test_quota_status_null_cost_limits_never_block(quota_engine: Engine) -> None:
    """NULL cost limits → cost path always returns OK, even with huge spend."""
    _seed_budget(
        quota_engine, _PROVIDER,
        daily_call_soft_limit=800, daily_call_hard_limit=1000,
        cost_soft_limit_usd=None, cost_hard_limit_usd=None,
    )
    _insert_logs(quota_engine, _PROVIDER, count=10, cost_usd=Decimal("9999.00"))

    with Session(quota_engine) as session:
        assert quota_status(session, _PROVIDER) == QUOTA_OK


# --------------------------------------------------------------------------- #
# quota_status — missing budget row
# --------------------------------------------------------------------------- #


def test_quota_status_returns_ok_when_no_budget_configured(quota_engine: Engine) -> None:
    """Providers without a budget row are treated as unrestricted (OK)."""
    with Session(quota_engine) as session:
        assert quota_status(session, "UNCONFIGURED_PROVIDER") == QUOTA_OK


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _seed_budget(
    engine: Engine,
    provider: str,
    *,
    daily_call_soft_limit: int,
    daily_call_hard_limit: int,
    cost_soft_limit_usd: Decimal | None = None,
    cost_hard_limit_usd: Decimal | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO provider_budgets (
                    provider, daily_call_soft_limit, daily_call_hard_limit,
                    cost_soft_limit_usd, cost_hard_limit_usd, updated_at
                )
                VALUES (
                    :provider, :daily_call_soft_limit, :daily_call_hard_limit,
                    :cost_soft_limit_usd, :cost_hard_limit_usd, now()
                )
                ON CONFLICT (provider) DO UPDATE SET
                    daily_call_soft_limit = EXCLUDED.daily_call_soft_limit,
                    daily_call_hard_limit = EXCLUDED.daily_call_hard_limit,
                    cost_soft_limit_usd = EXCLUDED.cost_soft_limit_usd,
                    cost_hard_limit_usd = EXCLUDED.cost_hard_limit_usd,
                    updated_at = now()
                """
            ),
            {
                "provider": provider,
                "daily_call_soft_limit": daily_call_soft_limit,
                "daily_call_hard_limit": daily_call_hard_limit,
                "cost_soft_limit_usd": cost_soft_limit_usd,
                "cost_hard_limit_usd": cost_hard_limit_usd,
            },
        )


def _insert_logs(
    engine: Engine,
    provider: str,
    count: int,
    *,
    success: bool = True,
    status_code: int | None = 200,
    cost_usd: Decimal | None = None,
    requested_at: datetime | None = None,
) -> None:
    ts = requested_at or datetime.now(UTC)
    with engine.begin() as connection:
        for _ in range(count):
            connection.execute(
                text(
                    """
                    INSERT INTO api_request_logs (
                        provider, endpoint, method, status_code,
                        success, estimated_cost_usd, requested_at
                    )
                    VALUES (
                        :provider, '/test', 'GET', :status_code,
                        :success, :cost_usd, :requested_at
                    )
                    """
                ),
                {
                    "provider": provider,
                    "status_code": status_code,
                    "success": success,
                    "cost_usd": cost_usd,
                    "requested_at": ts,
                },
            )


def _clear_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE TABLE api_request_logs, provider_budgets RESTART IDENTITY CASCADE"
        )
