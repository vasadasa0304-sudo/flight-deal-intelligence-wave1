"""Schema validation tests for the Wave1 PostgreSQL migration.

These tests require a running PostgreSQL instance.

  Local (WSL, no Docker):
    sudo apt-get install -y postgresql && sudo service postgresql start
    sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
    export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres
    .venv/bin/python -m pytest tests/test_schema.py -v

  CI (GitHub Actions):
    Set TEST_DATABASE_URL in the workflow env — see .github/workflows/ci.yml.
    In CI (CI=true), tests FAIL if no DB is available; locally they SKIP.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


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


# ---------------------------------------------------------------------------
# Original 6 schema tests
# ---------------------------------------------------------------------------


def test_all_13_tables_exist_after_migration(pg_schema_engine: tuple[Engine, str]) -> None:
    """All required production tables must exist after running the migration."""
    engine, schema_name = pg_schema_engine
    table_names = set(inspect(engine).get_table_names(schema=schema_name))
    assert EXPECTED_TABLES <= table_names


def test_price_observations_raw_response_is_jsonb(pg_schema_engine: tuple[Engine, str]) -> None:
    """Raw provider payloads must be stored as JSONB, not text."""
    engine, schema_name = pg_schema_engine
    columns = inspect(engine).get_columns("price_observations", schema=schema_name)
    raw_response = next(col for col in columns if col["name"] == "raw_response")
    assert isinstance(raw_response["type"], JSONB)


def test_watchlist_active_rows_enforce_mvp_cabins(pg_schema_engine: tuple[Engine, str]) -> None:
    """Active Wave1 rows are limited to ECONOMY/BUSINESS; inactive Phase 2 rows are allowed."""
    engine, _schema = pg_schema_engine
    _seed_reference_rows(engine)

    # Inactive row with Phase 2 cabin — must succeed.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO watchlist (
                route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag, is_active
            )
            VALUES ('IST-DXB', 'TK', 'FIRST', 60, 'USD', 120, 'STANDARD', 'STANDARD', false)
            ON CONFLICT (route_id, airline_code, cabin, booking_window_days) DO NOTHING
            """
        )

    # Active row with Phase 2 cabin — must fail.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO watchlist (
                    route_id, airline_code, cabin, booking_window_days,
                    currency, poll_frequency_minutes, route_priority, strategic_tag, is_active
                )
                VALUES ('IST-DXB', 'TK', 'PREMIUM_ECONOMY', 14, 'USD', 120, 'STANDARD', 'STANDARD', true)
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
                assert getattr(column["type"], "length", None) == 3, (
                    f"{table_name}.airline_code must be VARCHAR(3)"
                )

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
    """The append-only dedup key must be enforced by a unique constraint."""
    engine, schema_name = pg_schema_engine
    constraints = inspect(engine).get_unique_constraints("price_observations", schema=schema_name)
    assert any(
        c["name"] == "uq_price_observations_request_bucket"
        and c["column_names"] == ["request_hash", "polling_bucket_hour"]
        for c in constraints
    )


def test_duplicate_price_observation_request_bucket_is_rejected(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    """Duplicate (request_hash, polling_bucket_hour) observations must be rejected."""
    engine, _schema = pg_schema_engine
    watch_id = _seed_reference_rows(engine)
    request_hash = f"schema-test-{uuid.uuid4().hex}"

    with engine.begin() as conn:
        conn.exec_driver_sql(_price_observation_insert_sql(), {"watch_id": watch_id, "request_hash": request_hash})

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(_price_observation_insert_sql(), {"watch_id": watch_id, "request_hash": request_hash})


# ---------------------------------------------------------------------------
# Grain-constraint tests (Finding: High severity)
# Verify mismatched observation / baseline / anomaly grains are rejected.
# ---------------------------------------------------------------------------


def test_observation_with_mismatched_route_id_is_rejected(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    """An observation whose route_id does not match its watch_id's route must be rejected."""
    engine, _schema = pg_schema_engine
    watch_id = _seed_reference_rows(engine)

    # Seed a second airport and route so we have a valid but wrong route_id to attempt.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO airports (airport_code, city, country, region, timezone)
            VALUES ('DOH', 'Doha', 'Qatar', 'Middle East + Turkey', 'Asia/Qatar')
            ON CONFLICT (airport_code) DO NOTHING
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO routes (route_id, origin, destination, route_type,
                                route_priority, strategic_tag, source_document_note)
            VALUES ('IST-DOH', 'IST', 'DOH', 'INTERNATIONAL', 'STANDARD', 'STANDARD', 'test fixture')
            ON CONFLICT (route_id) DO NOTHING
            """
        )

    # watch_id refers to IST-DXB; inserting with route_id='IST-DOH' must fail.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO price_observations (
                    watch_id, route_id, origin, destination, airline_code,
                    cabin, booking_window_days, departure_date,
                    native_currency, native_price, display_currency, display_price,
                    source, request_hash, polling_bucket_hour, observed_at, raw_response
                )
                VALUES (
                    %(watch_id)s,
                    'IST-DOH',
                    'IST', 'DOH', 'TK', 'ECONOMY', 14,
                    DATE '2026-06-01',
                    'USD', 100.00, 'USD', 100.00,
                    'AMADEUS', 'grain-mismatch-route-test',
                    TIMESTAMPTZ '2026-05-12 10:00:00+00',
                    TIMESTAMPTZ '2026-05-12 10:15:00+00',
                    '{}'::jsonb
                )
                """,
                {"watch_id": watch_id},
            )


def test_anomaly_with_cross_grain_observation_and_baseline_is_rejected(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    """A detected_anomaly that pairs an observation from watch A with a baseline
    from watch B must be rejected by the composite grain FKs."""
    engine, _schema = pg_schema_engine

    # Two watch rows on the same route but different airlines.
    watch_a = _seed_reference_rows(engine)  # TK ECONOMY 14d on IST-DXB

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO airlines (airline_code, airline_name, carrier_type, is_wave1_airline)
            VALUES ('EK', 'Emirates', 'FSC', true)
            ON CONFLICT (airline_code) DO NOTHING
            """
        )
        result = conn.exec_driver_sql(
            """
            INSERT INTO watchlist (
                route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag
            )
            VALUES ('IST-DXB', 'EK', 'ECONOMY', 14, 'USD', 360, 'STANDARD', 'STANDARD')
            ON CONFLICT (route_id, airline_code, cabin, booking_window_days) DO UPDATE
                SET updated_at = NOW()
            RETURNING watch_id
            """
        )
        watch_b = int(result.scalar_one())

    # Insert one observation on watch A.
    obs_hash = f"grain-cross-obs-{uuid.uuid4().hex}"
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO price_observations (
                watch_id, route_id, origin, destination, airline_code,
                cabin, booking_window_days, departure_date,
                native_currency, native_price, display_currency, display_price,
                source, request_hash, polling_bucket_hour, observed_at, raw_response
            )
            VALUES (
                %(w)s, 'IST-DXB', 'IST', 'DXB', 'TK', 'ECONOMY', 14,
                DATE '2026-06-01',
                'USD', 100.00, 'USD', 100.00,
                'AMADEUS', %(h)s,
                TIMESTAMPTZ '2026-05-12 11:00:00+00',
                TIMESTAMPTZ '2026-05-12 11:05:00+00',
                '{}'::jsonb
            )
            """,
            {"w": watch_a, "h": obs_hash},
        )
        obs_id = int(
            conn.exec_driver_sql(
                "SELECT id FROM price_observations WHERE request_hash = %(h)s", {"h": obs_hash}
            ).scalar_one()
        )

    # Insert one baseline on watch B.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO baselines (
                watch_id, route_id, origin, destination, airline_code,
                cabin, booking_window_days, native_currency,
                baseline_date, window_start_date, window_end_date,
                median_price_native, min_price_native, max_price_native,
                p25_price_native, p75_price_native, iqr_price_native,
                observation_count, baseline_health
            )
            VALUES (
                %(w)s, 'IST-DXB', 'IST', 'DXB', 'EK', 'ECONOMY', 14, 'USD',
                DATE '2026-05-12', DATE '2026-04-12', DATE '2026-05-11',
                200.00, 180.00, 250.00, 190.00, 220.00, 30.00,
                30, 'GOOD'
            )
            """,
            {"w": watch_b},
        )
        baseline_id = int(
            conn.exec_driver_sql(
                "SELECT id FROM baselines WHERE watch_id = %(w)s LIMIT 1", {"w": watch_b}
            ).scalar_one()
        )

    # Try to create an anomaly pairing watch_a observation with watch_b baseline.
    # The composite grain FKs must reject this because the watch_ids differ.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO detected_anomalies (
                    price_observation_id, baseline_id, watch_id,
                    tier, current_price, baseline_price, currency,
                    absolute_saving, percent_saving, confidence_score,
                    threshold_set
                )
                VALUES (
                    %(obs)s, %(base)s,
                    %(watch_a)s,
                    'DEAL', 100.00, 200.00, 'USD',
                    100.00, 50.00, 0.850, 'SOW'
                )
                """,
                {"obs": obs_id, "base": baseline_id, "watch_a": watch_a},
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_reference_rows(engine: Engine) -> int:
    """Insert the minimal reference rows required by schema constraint tests.
    Returns the watch_id of the seeded watchlist row.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO airports (airport_code, city, country, region, timezone, is_wave1_hub)
            VALUES
                ('IST', 'Istanbul', 'Turkey', 'Middle East + Turkey', 'Europe/Istanbul', true),
                ('DXB', 'Dubai', 'United Arab Emirates', 'Middle East + Turkey', 'Asia/Dubai', true)
            ON CONFLICT (airport_code) DO NOTHING
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO airlines (airline_code, airline_name, carrier_type, primary_hub, is_wave1_airline)
            VALUES ('TK', 'Turkish Airlines', 'FSC', 'IST', true)
            ON CONFLICT (airline_code) DO NOTHING
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO routes (
                route_id, origin, destination, route_type,
                route_priority, strategic_tag, source_document_note
            )
            VALUES ('IST-DXB', 'IST', 'DXB', 'INTERNATIONAL', 'STANDARD', 'STANDARD', 'test fixture')
            ON CONFLICT (route_id) DO NOTHING
            """
        )
        result = conn.exec_driver_sql(
            """
            INSERT INTO watchlist (
                route_id, airline_code, cabin, booking_window_days,
                currency, poll_frequency_minutes, route_priority, strategic_tag
            )
            VALUES ('IST-DXB', 'TK', 'ECONOMY', 14, 'USD', 120, 'STANDARD', 'STANDARD')
            ON CONFLICT (route_id, airline_code, cabin, booking_window_days) DO UPDATE
                SET updated_at = NOW()
            RETURNING watch_id
            """
        )
        return int(result.scalar_one())


def _price_observation_insert_sql() -> str:
    return """
        INSERT INTO price_observations (
            watch_id, route_id, origin, destination, airline_code,
            cabin, booking_window_days, departure_date,
            native_currency, native_price, display_currency, display_price,
            source, request_hash, polling_bucket_hour, observed_at, raw_response
        )
        VALUES (
            %(watch_id)s,
            'IST-DXB', 'IST', 'DXB', 'TK', 'ECONOMY', 14,
            DATE '2026-06-01',
            'USD', 100.00, 'USD', 100.00,
            'AMADEUS', %(request_hash)s,
            TIMESTAMPTZ '2026-05-12 10:00:00+00',
            TIMESTAMPTZ '2026-05-12 10:15:00+00',
            '{}'::jsonb
        )
    """
