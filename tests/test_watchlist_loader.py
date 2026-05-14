"""PostgreSQL tests for the Wave1 seed loader."""

from __future__ import annotations

import csv
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.load_seed_data import main as load_seed_cli
from src.ingestion.watchlist_loader import load_seed_data


SEED_DIR = Path("data/seed")
SEED_TABLES = ("airports", "airlines", "routes", "route_carriers", "watchlist")


@pytest.fixture()
def empty_seed_schema(pg_schema_engine: tuple[Engine, str]) -> Iterator[Engine]:
    """Provide a migrated schema with empty seed tables for each loader test."""
    engine, _schema_name = pg_schema_engine
    _clear_seed_tables(engine)
    try:
        yield engine
    finally:
        _clear_seed_tables(engine)


def test_seed_loader_happy_path_loads_all_five_csvs(
    empty_seed_schema: Engine,
) -> None:
    summary = load_seed_data(empty_seed_schema, SEED_DIR)

    assert summary.airports_loaded == _csv_row_count(SEED_DIR / "airports.csv")
    assert summary.airlines_loaded == _csv_row_count(SEED_DIR / "airlines.csv")
    assert summary.routes_loaded == _csv_row_count(SEED_DIR / "routes_wave1.csv")
    assert summary.route_carrier_mappings == _csv_row_count(
        SEED_DIR / "route_carriers_wave1.csv"
    )
    assert summary.watchlist_rows_loaded == _csv_row_count(SEED_DIR / "watchlist_wave1.csv")
    assert _table_counts(empty_seed_schema) == {
        "airports": summary.airports_loaded,
        "airlines": summary.airlines_loaded,
        "routes": summary.routes_loaded,
        "route_carriers": summary.route_carrier_mappings,
        "watchlist": summary.watchlist_rows_loaded,
    }


def test_seed_loader_is_idempotent(empty_seed_schema: Engine) -> None:
    load_seed_data(empty_seed_schema, SEED_DIR)
    first_counts = _table_counts(empty_seed_schema)

    load_seed_data(empty_seed_schema, SEED_DIR)

    assert _table_counts(empty_seed_schema) == first_counts


def test_seed_validation_blocks_unknown_watchlist_airline_before_insert(
    empty_seed_schema: Engine,
    tmp_path: Path,
) -> None:
    seed_dir = _copy_seed_dir(tmp_path)
    _replace_first_watchlist_value(seed_dir, "airline_code", "ZZ")

    with pytest.raises(ValueError, match="watchlist.*airlines.csv"):
        load_seed_data(empty_seed_schema, seed_dir)

    assert _table_counts(empty_seed_schema) == _zero_counts()


def test_seed_validation_blocks_active_phase2_cabin_before_insert(
    empty_seed_schema: Engine,
    tmp_path: Path,
) -> None:
    seed_dir = _copy_seed_dir(tmp_path)
    _replace_first_watchlist_value(seed_dir, "cabin", "FIRST")
    _replace_first_watchlist_value(seed_dir, "is_active", "TRUE")

    with pytest.raises(ValueError, match="Active Wave1 rows outside MVP cabins"):
        load_seed_data(empty_seed_schema, seed_dir)

    assert _table_counts(empty_seed_schema) == _zero_counts()


def test_validate_only_cli_exits_without_writing_rows(
    empty_seed_schema: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = load_seed_cli(["--validate-only"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validation passed. No rows inserted." in captured.out
    assert _table_counts(empty_seed_schema) == _zero_counts()


def _copy_seed_dir(tmp_path: Path) -> Path:
    seed_dir = tmp_path / "seed"
    shutil.copytree(SEED_DIR, seed_dir)
    return seed_dir


def _replace_first_watchlist_value(seed_dir: Path, column: str, value: str) -> None:
    path = seed_dir / "watchlist_wave1.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    rows[0][column] = value

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _csv_row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def _table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table_name: int(
                connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
            )
            for table_name in SEED_TABLES
        }


def _clear_seed_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            TRUNCATE TABLE watchlist, route_carriers, routes, airlines, airports
            RESTART IDENTITY CASCADE
            """
        )


def _zero_counts() -> dict[str, int]:
    return {table_name: 0 for table_name in SEED_TABLES}
