"""Validate and load Wave1 seed CSV files."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.config import WAVE1_AIRLINES, WAVE1_MVP_CABINS

logger = logging.getLogger(__name__)

AIRPORTS_FILE = "airports.csv"
AIRLINES_FILE = "airlines.csv"
ROUTES_FILE = "routes_wave1.csv"
ROUTE_CARRIERS_FILE = "route_carriers_wave1.csv"
WATCHLIST_FILE = "watchlist_wave1.csv"

SEED_FILES = (
    AIRPORTS_FILE,
    AIRLINES_FILE,
    ROUTES_FILE,
    ROUTE_CARRIERS_FILE,
    WATCHLIST_FILE,
)

AIRPORT_COLUMNS = {
    "airport_code",
    "city",
    "country",
    "region",
    "timezone",
    "is_wave1_hub",
    "is_active",
}
AIRLINE_COLUMNS = {
    "airline_code",
    "airline_name",
    "carrier_type",
    "primary_hub",
    "is_wave1_airline",
    "is_active",
}
ROUTE_COLUMNS = {
    "route_id",
    "origin",
    "destination",
    "route_type",
    "route_priority",
    "strategic_tag",
    "strategic_relevance",
    "carrier_overlap_notes",
    "source_document_note",
    "is_new_launch",
    "is_active",
}
ROUTE_CARRIER_COLUMNS = {
    "route_id",
    "airline_code",
    "role_on_route",
    "is_primary_wave1_carrier",
    "notes",
}
WATCHLIST_COLUMNS = {
    "route_id",
    "airline_code",
    "cabin",
    "booking_window_days",
    "currency",
    "poll_frequency_minutes",
    "route_priority",
    "strategic_tag",
    "is_active",
}

# Backward-compatible name used by the smoke tests.
REQUIRED_COLUMNS = WATCHLIST_COLUMNS - {"is_active"}

VALID_ROUTE_PRIORITIES = {"TIER_1_DAILY", "TIER_2_EVERY_2_DAYS", "STANDARD"}
VALID_STRATEGIC_TAGS = {"STANDARD", "WAVE_2_PRESEED", "WAVE_3_PRESEED"}
VALID_BOOKING_WINDOWS = {14, 60}


@dataclass(frozen=True)
class SeedDataset:
    """Validated Wave1 seed CSV frames."""

    airports: pd.DataFrame
    airlines: pd.DataFrame
    routes: pd.DataFrame
    route_carriers: pd.DataFrame
    watchlist: pd.DataFrame
    validation_warnings: int = 0


@dataclass(frozen=True)
class SeedLoadSummary:
    """Final row counts from a Wave1 seed validation or load."""

    airports_loaded: int
    airlines_loaded: int
    routes_loaded: int
    route_carrier_mappings: int
    watchlist_rows_loaded: int
    validation_warnings: int = 0


def load_watchlist_csv(path: Path) -> pd.DataFrame:
    """Load and validate a Wave1 watchlist CSV without writing to the database.

    Raises ValueError with a descriptive message if validation fails.
    Returns the validated DataFrame on success.
    """
    logger.info("Loading watchlist seed file: %s", path)
    frame = _read_csv(path)

    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        raise ValueError(f"Missing watchlist columns: {sorted(missing_columns)}")

    _validate_watchlist_frame(frame)
    return frame


def validate_seed_files(seed_dir: Path) -> SeedDataset:
    """Read and validate all Wave1 seed CSVs before database writes."""
    logger.info("Validating Wave1 seed files from %s", seed_dir)

    airports = _read_seed_csv(seed_dir, AIRPORTS_FILE, AIRPORT_COLUMNS)
    airlines = _read_seed_csv(seed_dir, AIRLINES_FILE, AIRLINE_COLUMNS)
    routes = _read_seed_csv(seed_dir, ROUTES_FILE, ROUTE_COLUMNS)
    route_carriers = _read_seed_csv(seed_dir, ROUTE_CARRIERS_FILE, ROUTE_CARRIER_COLUMNS)
    watchlist = _read_seed_csv(seed_dir, WATCHLIST_FILE, WATCHLIST_COLUMNS)

    _validate_seed_dataset(airports, airlines, routes, route_carriers, watchlist)
    return SeedDataset(
        airports=airports,
        airlines=airlines,
        routes=routes,
        route_carriers=route_carriers,
        watchlist=watchlist,
    )


def load_seed_data(engine: Engine, seed_dir: Path, *, truncate: bool = False) -> SeedLoadSummary:
    """Validate and upsert all Wave1 seed files into PostgreSQL.

    Validation is completed before the first database write. Inserts and
    updates run in one transaction so failed loads cannot leave partial seed
    state behind.
    """
    dataset = validate_seed_files(seed_dir)

    with engine.begin() as connection:
        if truncate:
            logger.warning("Truncating Wave1 seed tables before load.")
            _truncate_seed_tables(connection)

        _upsert_airports(connection, dataset.airports)
        _upsert_airlines(connection, dataset.airlines)
        _upsert_routes(connection, dataset.routes)
        _upsert_route_carriers(connection, dataset.route_carriers)
        _upsert_watchlist(connection, dataset.watchlist)

    return summary_from_dataset(dataset)


def summary_from_dataset(dataset: SeedDataset) -> SeedLoadSummary:
    """Build a load-style summary from validated seed frames."""
    return SeedLoadSummary(
        airports_loaded=len(dataset.airports),
        airlines_loaded=len(dataset.airlines),
        routes_loaded=len(dataset.routes),
        route_carrier_mappings=len(dataset.route_carriers),
        watchlist_rows_loaded=len(dataset.watchlist),
        validation_warnings=dataset.validation_warnings,
    )


def format_load_summary(summary: SeedLoadSummary) -> str:
    """Format the final seed-load summary for stdout."""
    return "\n".join(
        (
            f"airports loaded:         {summary.airports_loaded}",
            f"airlines loaded:         {summary.airlines_loaded}",
            f"routes loaded:           {summary.routes_loaded}",
            f"route-carrier mappings:  {summary.route_carrier_mappings}",
            f"watchlist rows loaded:   {summary.watchlist_rows_loaded}",
            f"validation warnings:      {summary.validation_warnings}",
        )
    )


def _read_seed_csv(seed_dir: Path, filename: str, required_columns: set[str]) -> pd.DataFrame:
    path = seed_dir / filename
    if not path.exists():
        raise ValueError(f"Missing seed file: {path}")

    logger.info("Reading seed file %s", path)
    frame = _read_csv(path)
    logger.info("Read %d rows from %s", len(frame), path)

    missing_columns = required_columns - set(frame.columns)
    if missing_columns:
        raise ValueError(f"Missing columns in {filename}: {sorted(missing_columns)}")

    return frame.loc[:, list(required_columns)].copy()


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _validate_seed_dataset(
    airports: pd.DataFrame,
    airlines: pd.DataFrame,
    routes: pd.DataFrame,
    route_carriers: pd.DataFrame,
    watchlist: pd.DataFrame,
) -> None:
    _validate_unique(airports, ["airport_code"], AIRPORTS_FILE)
    _validate_unique(airlines, ["airline_code"], AIRLINES_FILE)
    _validate_unique(routes, ["route_id"], ROUTES_FILE)
    _validate_unique(route_carriers, ["route_id", "airline_code"], ROUTE_CARRIERS_FILE)
    _validate_unique(
        watchlist,
        ["route_id", "airline_code", "cabin", "booking_window_days"],
        WATCHLIST_FILE,
    )

    airport_codes = set(airports["airport_code"])
    route_airports = set(routes["origin"]) | set(routes["destination"])
    missing_route_airports = route_airports - airport_codes
    if missing_route_airports:
        raise ValueError(
            "Every airport_code in routes must exist in airports.csv; "
            f"missing: {sorted(missing_route_airports)}"
        )

    airline_codes = set(airlines["airline_code"])
    route_carrier_airlines = set(route_carriers["airline_code"])
    missing_route_carrier_airlines = route_carrier_airlines - airline_codes
    if missing_route_carrier_airlines:
        raise ValueError(
            "Every airline_code in route_carriers must exist in airlines.csv; "
            f"missing: {sorted(missing_route_carrier_airlines)}"
        )

    route_ids = set(routes["route_id"])
    missing_route_carrier_routes = set(route_carriers["route_id"]) - route_ids
    if missing_route_carrier_routes:
        raise ValueError(
            "Every route_id in route_carriers must exist in routes_wave1.csv; "
            f"missing: {sorted(missing_route_carrier_routes)}"
        )

    missing_watchlist_routes = set(watchlist["route_id"]) - route_ids
    if missing_watchlist_routes:
        raise ValueError(
            "Every route_id in watchlist must exist in routes_wave1.csv; "
            f"missing: {sorted(missing_watchlist_routes)}"
        )

    wave1_airlines = {
        row["airline_code"]
        for row in _records(airlines)
        if _parse_bool(row["is_wave1_airline"], field_name="airlines.is_wave1_airline")
    }
    missing_watchlist_airlines = set(watchlist["airline_code"]) - wave1_airlines
    if missing_watchlist_airlines:
        raise ValueError(
            "Every airline_code in watchlist must exist in airlines.csv with "
            "is_wave1_airline = TRUE; "
            f"missing or inactive: {sorted(missing_watchlist_airlines)}"
        )

    _validate_watchlist_frame(watchlist)
    _validate_route_metadata(routes, ROUTES_FILE)


def _validate_watchlist_frame(frame: pd.DataFrame) -> None:
    active_mask = _active_mask(frame)

    invalid_carriers = set(frame["airline_code"]) - set(WAVE1_AIRLINES)
    if invalid_carriers:
        raise ValueError(f"Carriers outside Wave1 airlines: {sorted(invalid_carriers)}")

    invalid_cabins = set(frame.loc[active_mask, "cabin"]) - set(WAVE1_MVP_CABINS)
    if invalid_cabins:
        raise ValueError(f"Active Wave1 rows outside MVP cabins: {sorted(invalid_cabins)}")

    booking_windows = _int_column(frame, "booking_window_days", WATCHLIST_FILE)
    invalid_windows = set(booking_windows) - VALID_BOOKING_WINDOWS
    if invalid_windows:
        raise ValueError(
            f"booking_window_days must be 14 or 60; found: {sorted(invalid_windows)}"
        )

    _validate_route_metadata(frame, WATCHLIST_FILE)

    poll_frequencies = _int_column(frame, "poll_frequency_minutes", WATCHLIST_FILE)
    if any(value <= 0 for value in poll_frequencies):
        raise ValueError("poll_frequency_minutes must be > 0 for all rows")

    blank_route_ids = frame["route_id"].isna() | (frame["route_id"].str.strip() == "")
    if blank_route_ids.any():
        raise ValueError("route_id must be non-empty for every row")

    logger.info(
        "Watchlist validation passed: %d rows (%d active).",
        len(frame),
        int(active_mask.sum()),
    )


def _validate_route_metadata(frame: pd.DataFrame, filename: str) -> None:
    invalid_priorities = set(frame["route_priority"].dropna()) - VALID_ROUTE_PRIORITIES
    if invalid_priorities:
        raise ValueError(
            f"Invalid route_priority values in {filename}: {sorted(invalid_priorities)}"
        )

    invalid_tags = set(frame["strategic_tag"].dropna()) - VALID_STRATEGIC_TAGS
    if invalid_tags:
        raise ValueError(f"Invalid strategic_tag values in {filename}: {sorted(invalid_tags)}")


def _validate_unique(frame: pd.DataFrame, columns: list[str], filename: str) -> None:
    duplicates = frame.duplicated(subset=columns, keep=False)
    if duplicates.any():
        duplicate_values = frame.loc[duplicates, columns].drop_duplicates().to_dict("records")
        raise ValueError(f"Duplicate grain in {filename} for {columns}: {duplicate_values}")


def _active_mask(frame: pd.DataFrame) -> pd.Series:
    if "is_active" not in frame.columns:
        return pd.Series(True, index=frame.index)
    return frame["is_active"].map(lambda value: _parse_bool(value, field_name="is_active"))


def _int_column(frame: pd.DataFrame, column: str, filename: str) -> list[int]:
    values: list[int] = []
    for row_number, raw_value in enumerate(frame[column], start=2):
        try:
            values.append(int(raw_value))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{filename} row {row_number}: {column} must be an integer; found {raw_value!r}"
            ) from exc
    return values


def _parse_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise ValueError(f"{field_name} must be TRUE or FALSE; found {value!r}")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: _db_value(value) for key, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _db_value(value: Any) -> Any:
    if value == "":
        return None
    return value


def _prepare_airports(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = _records(frame)
    for row in rows:
        row["is_wave1_hub"] = _parse_bool(row["is_wave1_hub"], field_name="is_wave1_hub")
        row["is_active"] = _parse_bool(row["is_active"], field_name="is_active")
    return rows


def _prepare_airlines(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = _records(frame)
    for row in rows:
        row["is_wave1_airline"] = _parse_bool(
            row["is_wave1_airline"], field_name="is_wave1_airline"
        )
        row["is_active"] = _parse_bool(row["is_active"], field_name="is_active")
    return rows


def _prepare_routes(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = _records(frame)
    for row in rows:
        row["is_new_launch"] = _parse_bool(row["is_new_launch"], field_name="is_new_launch")
        row["is_active"] = _parse_bool(row["is_active"], field_name="is_active")
    return rows


def _prepare_route_carriers(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = _records(frame)
    for row in rows:
        row["is_primary_wave1_carrier"] = _parse_bool(
            row["is_primary_wave1_carrier"], field_name="is_primary_wave1_carrier"
        )
    return rows


def _prepare_watchlist(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = _records(frame)
    for row in rows:
        row["booking_window_days"] = int(row["booking_window_days"])
        row["poll_frequency_minutes"] = int(row["poll_frequency_minutes"])
        row["is_active"] = _parse_bool(row["is_active"], field_name="is_active")
    return rows


def _truncate_seed_tables(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        TRUNCATE TABLE watchlist, route_carriers, routes, airlines, airports
        RESTART IDENTITY CASCADE
        """
    )


def _upsert_airports(connection: Connection, frame: pd.DataFrame) -> None:
    logger.info("Loading %d rows into airports", len(frame))
    connection.execute(
        text(
            """
            INSERT INTO airports (
                airport_code, city, country, region, timezone, is_wave1_hub, is_active
            )
            VALUES (
                :airport_code, :city, :country, :region, :timezone, :is_wave1_hub, :is_active
            )
            ON CONFLICT (airport_code) DO UPDATE SET
                city = EXCLUDED.city,
                country = EXCLUDED.country,
                region = EXCLUDED.region,
                timezone = EXCLUDED.timezone,
                is_wave1_hub = EXCLUDED.is_wave1_hub,
                is_active = EXCLUDED.is_active
            """
        ),
        _prepare_airports(frame),
    )


def _upsert_airlines(connection: Connection, frame: pd.DataFrame) -> None:
    logger.info("Loading %d rows into airlines", len(frame))
    connection.execute(
        text(
            """
            INSERT INTO airlines (
                airline_code, airline_name, carrier_type, primary_hub,
                is_wave1_airline, is_active
            )
            VALUES (
                :airline_code, :airline_name, :carrier_type, :primary_hub,
                :is_wave1_airline, :is_active
            )
            ON CONFLICT (airline_code) DO UPDATE SET
                airline_name = EXCLUDED.airline_name,
                carrier_type = EXCLUDED.carrier_type,
                primary_hub = COALESCE(EXCLUDED.primary_hub, airlines.primary_hub),
                is_wave1_airline = EXCLUDED.is_wave1_airline,
                is_active = EXCLUDED.is_active
            """
        ),
        _prepare_airlines(frame),
    )


def _upsert_routes(connection: Connection, frame: pd.DataFrame) -> None:
    logger.info("Loading %d rows into routes", len(frame))
    connection.execute(
        text(
            """
            INSERT INTO routes (
                route_id, origin, destination, route_type, route_priority,
                strategic_tag, strategic_relevance, carrier_overlap_notes,
                source_document_note, is_new_launch, is_active
            )
            VALUES (
                :route_id, :origin, :destination, :route_type, :route_priority,
                :strategic_tag, :strategic_relevance, :carrier_overlap_notes,
                :source_document_note, :is_new_launch, :is_active
            )
            ON CONFLICT (route_id) DO UPDATE SET
                origin = EXCLUDED.origin,
                destination = EXCLUDED.destination,
                route_type = EXCLUDED.route_type,
                route_priority = EXCLUDED.route_priority,
                strategic_tag = EXCLUDED.strategic_tag,
                strategic_relevance = COALESCE(
                    EXCLUDED.strategic_relevance,
                    routes.strategic_relevance
                ),
                carrier_overlap_notes = COALESCE(
                    EXCLUDED.carrier_overlap_notes,
                    routes.carrier_overlap_notes
                ),
                source_document_note = EXCLUDED.source_document_note,
                is_new_launch = EXCLUDED.is_new_launch,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
            """
        ),
        _prepare_routes(frame),
    )


def _upsert_route_carriers(connection: Connection, frame: pd.DataFrame) -> None:
    logger.info("Loading %d rows into route_carriers", len(frame))
    connection.execute(
        text(
            """
            INSERT INTO route_carriers (
                route_id, airline_code, role_on_route, is_primary_wave1_carrier, notes
            )
            VALUES (
                :route_id, :airline_code, :role_on_route, :is_primary_wave1_carrier, :notes
            )
            ON CONFLICT (route_id, airline_code) DO UPDATE SET
                role_on_route = EXCLUDED.role_on_route,
                is_primary_wave1_carrier = EXCLUDED.is_primary_wave1_carrier,
                notes = COALESCE(EXCLUDED.notes, route_carriers.notes)
            """
        ),
        _prepare_route_carriers(frame),
    )


def _upsert_watchlist(connection: Connection, frame: pd.DataFrame) -> None:
    logger.info("Loading %d rows into watchlist", len(frame))
    connection.execute(
        text(
            """
            INSERT INTO watchlist (
                route_id, airline_code, cabin, booking_window_days, currency,
                poll_frequency_minutes, route_priority, strategic_tag, is_active
            )
            VALUES (
                :route_id, :airline_code, :cabin, :booking_window_days, :currency,
                :poll_frequency_minutes, :route_priority, :strategic_tag, :is_active
            )
            ON CONFLICT (route_id, airline_code, cabin, booking_window_days)
            DO UPDATE SET
                currency = EXCLUDED.currency,
                poll_frequency_minutes = EXCLUDED.poll_frequency_minutes,
                route_priority = EXCLUDED.route_priority,
                strategic_tag = EXCLUDED.strategic_tag,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
            """
        ),
        _prepare_watchlist(frame),
    )
