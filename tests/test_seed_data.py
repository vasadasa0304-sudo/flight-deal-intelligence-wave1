"""Validate Wave1 seed CSV integrity."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


SEED_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"

EXPECTED_WAVE3_PRESEED = {
    "IST-ALA",
    "IST-TAS",
    "IST-NQZ",
    "IST-GYD",
    "SAW-ALA",
    "SAW-TAS",
    "SAW-NQZ",
    "SAW-GYD",
    "DXB-ALA",
    "DXB-TAS",
    "DXB-GYD",
    "DOH-TAS",
    "DOH-ALA",
}

EXPECTED_WAVE2_PRESEED = {
    "DXB-NBO",
    "DXB-JNB",
    "DXB-ADD",
    "AUH-NBO",
}

REQUIRED_WATCH_COMBINATIONS = {
    ("14", "ECONOMY"),
    ("14", "BUSINESS"),
    ("60", "ECONOMY"),
    ("60", "BUSINESS"),
}


def _read_csv(filename: str) -> list[dict[str, str]]:
    with (SEED_DIR / filename).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _is_true(value: str) -> bool:
    return value.strip().upper() == "TRUE"


def test_active_route_count_is_in_wave1_target_range() -> None:
    routes = _read_csv("routes_wave1.csv")
    active_route_ids = {row["route_id"] for row in routes if _is_true(row["is_active"])}

    assert 65 <= len(active_route_ids) <= 82


def test_every_active_route_has_minimum_watchlist_grid_for_at_least_one_carrier() -> None:
    routes = _read_csv("routes_wave1.csv")
    watchlist = _read_csv("watchlist_wave1.csv")
    active_route_ids = {row["route_id"] for row in routes if _is_true(row["is_active"])}
    combinations_by_route_carrier: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)

    for row in watchlist:
        if not _is_true(row["is_active"]):
            continue
        key = (row["route_id"], row["airline_code"])
        combinations_by_route_carrier[key].add((row["booking_window_days"], row["cabin"]))

    for route_id in active_route_ids:
        route_carrier_grids = [
            combinations
            for (watch_route_id, _airline_code), combinations in combinations_by_route_carrier.items()
            if watch_route_id == route_id
        ]
        assert any(REQUIRED_WATCH_COMBINATIONS <= combinations for combinations in route_carrier_grids), route_id


def test_route_priority_counts_meet_wave1_minimums() -> None:
    routes = _read_csv("routes_wave1.csv")
    active_routes = [row for row in routes if _is_true(row["is_active"])]

    tier_1_count = sum(row["route_priority"] == "TIER_1_DAILY" for row in active_routes)
    tier_2_count = sum(row["route_priority"] == "TIER_2_EVERY_2_DAYS" for row in active_routes)

    assert tier_1_count >= 9
    assert tier_2_count >= 6


def test_watchlist_airlines_are_wave1_airlines() -> None:
    airlines = _read_csv("airlines.csv")
    watchlist = _read_csv("watchlist_wave1.csv")
    wave1_airlines = {
        row["airline_code"]
        for row in airlines
        if _is_true(row["is_wave1_airline"])
    }

    assert len(wave1_airlines) == 10
    assert {row["airline_code"] for row in watchlist} <= wave1_airlines


def test_watchlist_routes_are_active_seed_routes() -> None:
    routes = _read_csv("routes_wave1.csv")
    watchlist = _read_csv("watchlist_wave1.csv")
    active_route_ids = {row["route_id"] for row in routes if _is_true(row["is_active"])}

    assert {row["route_id"] for row in watchlist} <= active_route_ids


def test_route_endpoints_exist_in_airports_seed() -> None:
    airports = _read_csv("airports.csv")
    routes = _read_csv("routes_wave1.csv")
    airport_codes = {row["airport_code"] for row in airports}

    for row in routes:
        assert row["origin"] in airport_codes
        assert row["destination"] in airport_codes


def test_watchlist_has_no_duplicate_grain() -> None:
    watchlist = _read_csv("watchlist_wave1.csv")
    grain = [
        (row["route_id"], row["airline_code"], row["cabin"], row["booking_window_days"])
        for row in watchlist
    ]

    assert len(grain) == len(set(grain))


def test_wave3_preseed_routes_are_tagged() -> None:
    routes = {row["route_id"]: row for row in _read_csv("routes_wave1.csv")}

    for route_id in EXPECTED_WAVE3_PRESEED:
        assert routes[route_id]["strategic_tag"] == "WAVE_3_PRESEED"


def test_wave2_preseed_routes_are_tagged() -> None:
    routes = {row["route_id"]: row for row in _read_csv("routes_wave1.csv")}

    for route_id in EXPECTED_WAVE2_PRESEED:
        assert routes[route_id]["strategic_tag"] == "WAVE_2_PRESEED"


def test_route_source_note_is_exact_scope_text() -> None:
    routes = _read_csv("routes_wave1.csv")

    assert {
        row["source_document_note"]
        for row in routes
    } == {"Seeded from employer Wave1 route plan; live schedule validation required."}
