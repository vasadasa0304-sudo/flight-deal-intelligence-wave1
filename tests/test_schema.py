"""Schema validation tests for the Wave1 PostgreSQL migration."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from src.db_helpers import run_migrations


EXPECTED_TABLES = {
    "airports",
    "airlines",
    "routes",
    "route_carriers",
    "watchlist",
    "price_observations",
    "fx_rates",
    "baselines",
    "detected_anomalies",
    "qa_checks",
    "alerts",
    "api_request_logs",
    "scheduler_runs",
}


@pytest.fixture(scope="session")
def pg_schema_engine() -> Iterator[tuple[Engine, str]]:
    """Create an isolated PostgreSQL schema for migration tests."""
    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL or DATABASE_URL to run PostgreSQL schema tests.")

    admin_engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 2})
    schema_name = f"test_wave1_{uuid.uuid4().hex}"

    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'create schema "{schema_name}"')
    except OperationalError as exc:
        admin_engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable for schema tests: {exc}")
    except SQLAlchemyError:
        admin_engine.dispose()
        raise

    test_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 2, "options": f"-csearch_path={schema_name},public"},
    )
    try:
        run_migrations(test_engine, Path("migrations/001_init.sql"))
        yield test_engine, schema_name
    finally:
        test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'drop schema if exists "{schema_name}" cascade')
        admin_engine.dispose()


def test_all_13_tables_exist_after_migration(pg_schema_engine: tuple[Engine, str]) -> None:
    """All required production tables must exist after running the migration."""
    engine, schema_name = pg_schema_engine
    table_names = set(inspect(engine).get_table_names(schema=schema_name))
    assert EXPECTED_TABLES <= table_names


def test_price_observations_raw_response_is_jsonb(pg_schema_engine: tuple[Engine, str]) -> None:
    """Raw provider payloads must be stored as JSONB, not text."""
    engine, schema_name = pg_schema_engine
    columns = inspect(engine).get_columns("price_observations", schema=schema_name)
    raw_response = next(column for column in columns if column["name"] == "raw_response")
    assert isinstance(raw_response["type"], JSONB)


def test_watchlist_active_rows_enforce_mvp_cabins(pg_schema_engine: tuple[Engine, str]) -> None:
    """Active Wave1 rows are limited to ECONOMY/BUSINESS; inactive Phase 2 rows are allowed."""
    engine, _schema_name = pg_schema_engine
    _seed_reference_rows(engine)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            insert into watchlist (
                route_id,
                airline_code,
                cabin,
                booking_window_days,
                currency,
                poll_frequency_minutes,
                route_priority,
                strategic_tag,
                is_active
            )
            values ('IST-DXB', 'TK', 'FIRST', 60, 'USD', 120, 'STANDARD', 'STANDARD', false)
            on conflict (route_id, airline_code, cabin, booking_window_days) do nothing
            """
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                insert into watchlist (
                    route_id,
                    airline_code,
                    cabin,
                    booking_window_days,
                    currency,
                    poll_frequency_minutes,
                    route_priority,
                    strategic_tag,
                    is_active
                )
                values ('IST-DXB', 'TK', 'PREMIUM_ECONOMY', 14, 'USD', 120, 'STANDARD', 'STANDARD', true)
                """
            )


def test_airline_code_columns_are_varchar_3(pg_schema_engine: tuple[Engine, str]) -> None:
    """Every airline_code column must use the same VARCHAR(3) width."""
    engine, schema_name = pg_schema_engine
    inspector = inspect(engine)
    checked_tables = []

    for table_name in EXPECTED_TABLES:
        for column in inspector.get_columns(table_name, schema=schema_name):
            if column["name"] == "airline_code":
                checked_tables.append(table_name)
                assert getattr(column["type"], "length", None) == 3

    assert sorted(checked_tables) == [
        "airlines",
        "alerts",
        "baselines",
        "price_observations",
        "route_carriers",
        "watchlist",
    ]


def test_price_observations_request_bucket_unique_constraint_exists(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    """The append-only observation dedupe key must be enforced by a unique constraint."""
    engine, schema_name = pg_schema_engine
    constraints = inspect(engine).get_unique_constraints("price_observations", schema=schema_name)
    assert any(
        constraint["name"] == "uq_price_observations_request_bucket"
        and constraint["column_names"] == ["request_hash", "polling_bucket_hour"]
        for constraint in constraints
    )


def test_duplicate_price_observation_request_bucket_is_rejected(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    """Duplicate request_hash + polling_bucket_hour observations must be rejected."""
    engine, _schema_name = pg_schema_engine
    watch_id = _seed_reference_rows(engine)
    request_hash = f"schema-test-{uuid.uuid4().hex}"

    with engine.begin() as connection:
        connection.exec_driver_sql(
            _price_observation_insert_sql(),
            {"watch_id": watch_id, "request_hash": request_hash},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                _price_observation_insert_sql(),
                {"watch_id": watch_id, "request_hash": request_hash},
            )


def _seed_reference_rows(engine: Engine) -> int:
    """Insert the minimal reference rows needed by schema constraint tests."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            insert into airports (airport_code, city, country, region, timezone, is_wave1_hub)
            values
                ('IST', 'Istanbul', 'Turkey', 'Middle East + Turkey', 'Europe/Istanbul', true),
                ('DXB', 'Dubai', 'United Arab Emirates', 'Middle East + Turkey', 'Asia/Dubai', true)
            on conflict (airport_code) do nothing
            """
        )
        connection.exec_driver_sql(
            """
            insert into airlines (airline_code, airline_name, carrier_type, primary_hub, is_wave1_airline)
            values ('TK', 'Turkish Airlines', 'FSC', 'IST', true)
            on conflict (airline_code) do nothing
            """
        )
        connection.exec_driver_sql(
            """
            insert into routes (
                route_id,
                origin,
                destination,
                route_type,
                route_priority,
                strategic_tag,
                source_document_note
            )
            values ('IST-DXB', 'IST', 'DXB', 'INTERNATIONAL', 'STANDARD', 'STANDARD', 'test fixture')
            on conflict (route_id) do nothing
            """
        )
        result = connection.exec_driver_sql(
            """
            insert into watchlist (
                route_id,
                airline_code,
                cabin,
                booking_window_days,
                currency,
                poll_frequency_minutes,
                route_priority,
                strategic_tag
            )
            values ('IST-DXB', 'TK', 'ECONOMY', 14, 'USD', 120, 'STANDARD', 'STANDARD')
            on conflict (route_id, airline_code, cabin, booking_window_days) do update
                set updated_at = now()
            returning watch_id
            """
        )
        return int(result.scalar_one())


def _price_observation_insert_sql() -> str:
    """Return a parameterized insert for duplicate-key tests."""
    return """
        insert into price_observations (
            watch_id,
            route_id,
            origin,
            destination,
            airline_code,
            cabin,
            booking_window_days,
            departure_date,
            native_currency,
            native_price,
            display_currency,
            display_price,
            source,
            request_hash,
            polling_bucket_hour,
            observed_at,
            raw_response
        )
        values (
            %(watch_id)s,
            'IST-DXB',
            'IST',
            'DXB',
            'TK',
            'ECONOMY',
            14,
            date '2026-06-01',
            'USD',
            100.00,
            'USD',
            100.00,
            'AMADEUS',
            %(request_hash)s,
            timestamptz '2026-05-12 10:00:00+00',
            timestamptz '2026-05-12 10:15:00+00',
            '{}'::jsonb
        )
        """
