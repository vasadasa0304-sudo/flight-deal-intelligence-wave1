"""Unit tests for the Amadeus async client.

All tests use a custom AsyncBaseTransport — no real network calls are made.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.clients.amadeus_client import AmadeusClient
from src.config import Settings

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text())


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        app_env="test",
        log_level="WARNING",
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/flight_deals",
        wave_scope="WAVE1",
        display_currency="USD",
        wave1_hubs=("IST", "SAW", "DXB", "AUH", "RUH", "JED", "DOH", "CAI"),
        wave1_airlines=("TK", "PC", "EK", "FZ", "QR", "EY", "SV", "XY", "MS", "G9"),
        wave1_booking_windows_days=(14, 60),
        wave1_mvp_cabins=("ECONOMY", "BUSINESS"),
        amadeus_env="test",
        amadeus_client_id="test-client-id",
        amadeus_client_secret="test-client-secret",
        amadeus_max_concurrency=5,
        amadeus_timeout_seconds=25.0,
        duffel_api_key=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": "mock-token-abc", "expires_in": 1799, "token_type": "Bearer"},
    )


def _offers_response() -> httpx.Response:
    return httpx.Response(200, json=_load_fixture("amadeus_flight_offers_sample.json"))


def _pricing_response() -> httpx.Response:
    offer = _load_fixture("amadeus_flight_offers_sample.json")["data"][0]
    return httpx.Response(
        200,
        json={"data": {"type": "flight-offers-pricing", "flightOffers": [offer]}},
    )


class _SequentialTransport(httpx.AsyncBaseTransport):
    """Serves responses from a pre-built list, one per request."""

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._queue = list(responses)
        self._index = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._index >= len(self._queue):
            raise AssertionError(
                f"Unexpected call #{self._index + 1} to {request.url}; "
                f"only {len(self._queue)} responses queued."
            )
        item = self._queue[self._index]
        self._index += 1
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def call_count(self) -> int:
        return self._index


@pytest.mark.asyncio
async def test_token_cached_across_two_searches() -> None:
    """Token should be fetched once for two consecutive search calls."""
    transport = _SequentialTransport([
        _token_response(),
        _offers_response(),
        _offers_response(),
    ])
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        await c.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
        await c.search_flight_offers("IST", "DXB", date(2026, 6, 15), "ECONOMY")
    assert transport.call_count == 3


@pytest.mark.asyncio
async def test_401_triggers_one_token_refresh_and_one_retry() -> None:
    """401 on data endpoint → exactly one token refresh, then one retry."""
    transport = _SequentialTransport([
        _token_response(),
        httpx.Response(401),
        _token_response(),
        _offers_response(),
    ])
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        offers = await c.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
    assert len(offers) == 1
    assert transport.call_count == 4


@pytest.mark.asyncio
async def test_429_retries_with_backoff_third_attempt_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 twice then success; sleep is called for each backoff."""
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    transport = _SequentialTransport([
        _token_response(),
        httpx.Response(429, headers={"Retry-After": "0.01"}),
        httpx.Response(429, headers={"Retry-After": "0.01"}),
        _offers_response(),
    ])
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        offers = await c.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
    assert len(offers) == 1
    assert len(sleeps) == 2
    assert transport.call_count == 4


@pytest.mark.asyncio
async def test_500_retries_three_times_then_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 500: retries 3 times, then returns [] without raising."""
    async def _no_sleep(_: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    transport = _SequentialTransport([
        _token_response(),
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(500),
    ])
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        offers = await c.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
    assert offers == []
    assert transport.call_count == 5  # 1 token + 4 attempts (initial + 3 retries)


@pytest.mark.asyncio
async def test_successful_search_returns_offer_dicts() -> None:
    """200 response returns list of raw offer dicts with expected fields."""
    transport = _SequentialTransport([_token_response(), _offers_response()])
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        offers = await c.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
    assert len(offers) == 1
    offer = offers[0]
    assert offer["validatingAirlineCodes"] == ["TK"]
    assert offer["price"]["grandTotal"] == "450.00"
    assert offer["itineraries"][0]["segments"][0]["departure"]["iataCode"] == "IST"
    assert offer["itineraries"][0]["segments"][0]["arrival"]["iataCode"] == "DXB"


@pytest.mark.asyncio
async def test_verify_price_success_returns_dict() -> None:
    """verify_price returns the data dict from a 200 pricing response."""
    transport = _SequentialTransport([_token_response(), _pricing_response()])
    offer = _load_fixture("amadeus_flight_offers_sample.json")["data"][0]
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        result = await c.verify_price(offer)
    assert result is not None
    assert result["type"] == "flight-offers-pricing"
    assert "flightOffers" in result


@pytest.mark.asyncio
async def test_timeout_exception_returns_empty_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TimeoutException after exhausting retries must return [] silently."""
    async def _no_sleep(_: float) -> None:
        pass
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    transport = _SequentialTransport([
        _token_response(),
        httpx.TimeoutException("timed out"),
        httpx.TimeoutException("timed out"),
        httpx.TimeoutException("timed out"),
    ])
    async with AmadeusClient(_make_settings(), _transport=transport) as c:
        offers = await c.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
    assert offers == []


@pytest.mark.asyncio
async def test_production_env_uses_production_base_url() -> None:
    settings = _make_settings(amadeus_env="production")
    async with AmadeusClient(settings, _transport=_SequentialTransport([])) as c:
        assert c._base_url == "https://api.amadeus.com"


@pytest.mark.asyncio
async def test_test_env_uses_test_base_url() -> None:
    settings = _make_settings(amadeus_env="test")
    async with AmadeusClient(settings, _transport=_SequentialTransport([])) as c:
        assert c._base_url == "https://test.api.amadeus.com"
