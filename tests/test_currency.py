"""Tests for Wave1 currency helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.detection.thresholds import classify_by_threshold
from src.utils.currency import (
    convert_amount,
    is_special_handling,
    native_or_display,
)


def test_convert_amount_with_known_rate_row(pg_schema_engine: tuple[Engine, str]) -> None:
    engine, _schema_name = pg_schema_engine
    _clear_fx_rates(engine)
    _insert_fx_rate(engine, date(2026, 5, 16), "EUR", "USD", Decimal("1.10000000"))

    with Session(engine) as session:
        result = convert_amount(
            Decimal("200.00"),
            "EUR",
            "USD",
            date(2026, 5, 16),
            session,
        )

    assert result == (Decimal("220.00"), Decimal("1.10000000"))


def test_convert_amount_falls_back_to_rate_within_7_days(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    engine, _schema_name = pg_schema_engine
    _clear_fx_rates(engine)
    _insert_fx_rate(engine, date(2026, 5, 10), "EUR", "USD", Decimal("1.20000000"))

    with Session(engine) as session:
        result = convert_amount(
            Decimal("200.00"),
            "EUR",
            "USD",
            date(2026, 5, 16),
            session,
        )

    assert result == (Decimal("240.00"), Decimal("1.20000000"))


def test_convert_amount_returns_none_when_no_rate_within_7_days(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    engine, _schema_name = pg_schema_engine
    _clear_fx_rates(engine)
    _insert_fx_rate(engine, date(2026, 5, 8), "EUR", "USD", Decimal("1.20000000"))

    with Session(engine) as session:
        result = convert_amount(
            Decimal("200.00"),
            "EUR",
            "USD",
            date(2026, 5, 16),
            session,
        )

    assert result is None


def test_is_special_handling_returns_true_for_egp_try_sar() -> None:
    assert is_special_handling("EGP")
    assert is_special_handling("try")
    assert is_special_handling("SAR")
    assert not is_special_handling("AED")


def test_fx_movement_alone_does_not_create_false_deal() -> None:
    baseline_native = Decimal("200")
    current_native = Decimal("200")

    assert native_or_display("EUR", "EUR") == "NATIVE"
    absolute_saving = baseline_native - current_native
    percent_below_baseline = (absolute_saving / baseline_native) * Decimal("100")

    assert classify_by_threshold(percent_below_baseline, absolute_saving) is None


def _insert_fx_rate(
    engine: Engine,
    rate_date: date,
    from_currency: str,
    to_currency: str,
    rate: Decimal,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO fx_rates (rate_date, from_currency, to_currency, rate, source)
                VALUES (:rate_date, :from_currency, :to_currency, :rate, 'FRANKFURTER')
                """
            ),
            {
                "rate_date": rate_date,
                "from_currency": from_currency,
                "to_currency": to_currency,
                "rate": rate,
            },
        )


def _clear_fx_rates(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE TABLE fx_rates")
