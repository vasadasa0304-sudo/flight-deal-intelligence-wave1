"""Unit tests for AmadeusClient using httpx.MockTransport — no real network calls."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.clients.amadeus_client import (
    AmadeusClient,
    _TOKEN_PATH,
)
from src.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text())


def _make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        app_env="test",
        log_level="INFO",
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/test",
        wave_scope="WAVE1",
        display_currency="USD",
        wave1_hubs=("IST", "SAW", "DXB", "AUH", "RUH", "JED", "DOH", "CAI"),
        wave1_airlines=("TK", "PC", "EK", "FZ", "QR", "EY", "SV", "XY", "MS", "G9"),
        wave1_booking_windows_days=(14, 60),
        wave1_mvp_cabins=("ECONOMY", "BUSINESS"),
        amadeus_env="test",
        amadeus_client_id="test_id",
        amadeus_client_secret="test_secret",
        amadeus_max_concurrency=5,
        amadeus_timeout_seconds=25.0,
        duffel_api_key=None,
    )
    base.update(overrides)
    return Settings(**base)


def _token_resp() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "test_token_abc123",
            "token_type": "Bearer",
            "expires_in": 1799,
        },
    )


def _search_resp() -> httpx.Response:
    return httpx.Response(200, json=_load_fixture("amadeus_flight_offers_sample.json"))


def _pricing_resp(offer: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"type": "flight-offers-pricing", "flightOffers": [offer]}},
    )


class _SequentialTransport(httpx.AsyncBaseTransport):
    """Returns responses in order; repeats the last one if the list is exhausted."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self._index = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_cached_across_two_consecutive_searches() -> None:
    """Token endpoint is called only once for two back-to-back search calls."""
    token_calls = 0

    class CountingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal token_calls
            if request.url.path == _TOKEN_PATH:
                token_calls += 1
                return _token_resp()
            return _search_resp()

    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=CountingTransport())
        await client.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")
        await client.search_flight_offers("IST", "DXB", date(2026, 6, 15), "ECONOMY")

    assert token_calls == 1, f"Expected 1 token call, got {token_calls}"


@pytest.mark.asyncio
async def test_401_triggers_exactly_one_token_refresh_then_retries() -> None:
    """401 on the data endpoint: refresh token once, retry once, succeed."""
    token_calls = 0
    data_calls = 0

    class RefreshTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal token_calls, data_calls
            if request.url.path == _TOKEN_PATH:
                token_calls += 1
                return _token_resp()
            data_calls += 1
            if data_calls == 1:
                return httpx.Response(
                    401, json={"errors": [{"status": 401, "title": "Unauthorized"}]}
                )
            return _search_resp()

    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=RefreshTransport())
        result = await client.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")

    assert token_calls == 2, f"Expected 2 token calls (initial + refresh), got {token_calls}"
    assert data_calls == 2, f"Expected 2 data calls (fail + retry), got {data_calls}"
    assert len(result) == 1


@pytest.mark.asyncio
async def test_429_retries_and_succeeds_on_third_attempt() -> None:
    """Two 429 responses followed by a 200 — eventually returns offers."""
    responses = [
        _token_resp(),
        httpx.Response(429, headers={"Retry-After": "0"}, json={}),
        httpx.Response(429, headers={"Retry-After": "0"}, json={}),
        _search_resp(),
    ]
    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_SequentialTransport(responses))
        result = await client.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")

    assert len(result) == 1
    assert result[0]["validatingAirlineCodes"] == ["TK"]


@pytest.mark.asyncio
async def test_500_retries_three_times_then_returns_empty_list() -> None:
    """Max 3 retries on 500; all fail → returns [] without raising."""
    responses = [_token_resp()] + [httpx.Response(500, json={})] * 4
    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_SequentialTransport(responses))
        result = await client.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")

    assert result == []


@pytest.mark.asyncio
async def test_search_flight_offers_success_returns_offer_list() -> None:
    """Successful 200 response returns the data array from the fixture."""
    fixture = _load_fixture("amadeus_flight_offers_sample.json")
    responses = [_token_resp(), httpx.Response(200, json=fixture)]
    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_SequentialTransport(responses))
        result = await client.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")

    assert isinstance(result, list)
    assert len(result) == 1
    offer = result[0]
    assert offer["validatingAirlineCodes"] == ["TK"]
    assert offer["price"]["grandTotal"] == "310.00"
    assert offer["itineraries"][0]["segments"][0]["departure"]["iataCode"] == "IST"
    assert offer["itineraries"][0]["segments"][0]["arrival"]["iataCode"] == "DXB"


@pytest.mark.asyncio
async def test_verify_price_success_returns_repriced_offer() -> None:
    """verify_price returns the first flightOffer from the pricing response."""
    fixture = _load_fixture("amadeus_flight_offers_sample.json")
    offer = fixture["data"][0]
    responses = [_token_resp(), _pricing_resp(offer)]
    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_SequentialTransport(responses))
        result = await client.verify_price(offer)

    assert result is not None
    assert result["price"]["grandTotal"] == "310.00"
    assert result["validatingAirlineCodes"] == ["TK"]


@pytest.mark.asyncio
async def test_timeout_exception_returns_empty_list_without_raising() -> None:
    """httpx.TimeoutException is caught silently; search returns []."""

    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_resp()
            raise httpx.TimeoutException("timed out", request=request)

    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=TimeoutTransport())
        result = await client.search_flight_offers("IST", "DXB", date(2026, 6, 1), "ECONOMY")

    assert result == []
