"""Tests for AmadeusClient — all network I/O mocked via httpx.MockTransport.

No real API calls are made.  Every test drives the client through its
full retry / token-cache / error-handling code paths.

Run with:
    pytest tests/test_amadeus_client.py -v
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.clients.amadeus_client import AmadeusClient

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers — build mock Settings and fake HTTP transports
# ---------------------------------------------------------------------------

def _make_settings(
    env: str = "test",
    max_concurrency: int = 5,
    timeout: float = 5.0,
) -> MagicMock:
    """Return a minimal Settings-like mock object."""
    s = MagicMock()
    s.amadeus_client_id = "TEST_CLIENT_ID"
    s.amadeus_client_secret = "TEST_CLIENT_SECRET"
    s.amadeus_env = env
    s.amadeus_max_concurrency = max_concurrency
    s.amadeus_timeout_seconds = timeout
    return s


def _token_response(token: str = "mock_token_abc", expires_in: int = 1799) -> dict:
    """Minimal OAuth token response body."""
    return {
        "type": "amadeusOAuth2Token",
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "state": "approved",
    }


def _load_fixture(filename: str) -> dict:
    """Load a JSON fixture file from tests/fixtures/."""
    with open(FIXTURES_DIR / filename) as fh:
        return json.load(fh)


class _CallRecorder:
    """Records every (method, url, attempt) so tests can assert call counts."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, request: httpx.Request) -> None:
        self.calls.append({"method": request.method, "url": str(request.url)})

    @property
    def count(self) -> int:
        return len(self.calls)


# ---------------------------------------------------------------------------
# Transport factories
# ---------------------------------------------------------------------------

def _build_transport(handler) -> httpx.MockTransport:
    """Wrap a handler function into an httpx.MockTransport.

    The handler receives an httpx.Request and must return an httpx.Response.
    """
    return httpx.MockTransport(handler)


def _json_response(
    status: int, body: dict, headers: dict | None = None
) -> httpx.Response:
    raw_headers = {"content-type": "application/json"}
    if headers:
        raw_headers.update(headers)
    return httpx.Response(
        status_code=status,
        json=body,
        headers=raw_headers,
    )


# ---------------------------------------------------------------------------
# Test: token is cached (only one token request for two search calls)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_cached_across_calls() -> None:
    """OAuth token should be fetched once and reused for subsequent calls."""
    recorder = _CallRecorder()
    flight_data = _load_fixture("amadeus_flight_offers_sample.json")

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)
        if "oauth2/token" in str(request.url):
            return _json_response(200, _token_response())
        # Both search calls hit this branch
        return _json_response(200, flight_data)

    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        # Swap out the real http client for our mock
        client._http = httpx.AsyncClient(transport=_build_transport(handler))

        dep = date(2025, 9, 1)
        await client.search_flight_offers("YUL", "CDG", dep, "ECONOMY")
        await client.search_flight_offers("YUL", "LHR", dep, "ECONOMY")

    token_calls = [c for c in recorder.calls if "oauth2/token" in c["url"]]
    # Only ONE token request even though we made TWO search calls
    assert len(token_calls) == 1, (
        f"Expected 1 token call, got {len(token_calls)}"
    )


# ---------------------------------------------------------------------------
# Test: 401 triggers exactly one token refresh, then one retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_401_triggers_one_token_refresh_and_retry() -> None:
    """A 401 from a data endpoint must refresh the token and retry exactly once."""
    token_calls: list[str] = []
    data_calls: list[str] = []
    flight_data = _load_fixture("amadeus_flight_offers_sample.json")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            token_calls.append(url)
            # Give back a different token on second request so we can tell them apart
            tok = "initial_token" if len(token_calls) == 1 else "refreshed_token"
            return _json_response(200, _token_response(token=tok))

        data_calls.append(url)
        auth = request.headers.get("Authorization", "")
        if "initial_token" in auth:
            # First data call: pretend token is expired
            return _json_response(401, {"errors": [{"status": 401}]})
        # Second data call (with refreshed token): success
        return _json_response(200, flight_data)

    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_build_transport(handler))

        result = await client.search_flight_offers(
            "YUL", "CDG", date(2025, 9, 1), "ECONOMY"
        )

    assert len(token_calls) == 2, "Token should have been fetched twice (initial + refresh)"
    assert len(data_calls) == 2, "Data endpoint should have been called twice (fail + retry)"
    assert isinstance(result, list) and len(result) > 0


# ---------------------------------------------------------------------------
# Test: 429 triggers exponential backoff; 3rd attempt succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_429_retries_and_succeeds_on_third_attempt() -> None:
    """429 responses should be retried with backoff; success on 3rd attempt."""
    call_count = 0
    flight_data = _load_fixture("amadeus_flight_offers_sample.json")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if "oauth2/token" in str(request.url):
            return _json_response(200, _token_response())
        call_count += 1
        if call_count < 3:
            return _json_response(429, {"errors": []}, headers={"Retry-After": "0"})
        return _json_response(200, flight_data)

    settings = _make_settings()
    # Patch asyncio.sleep to avoid actually waiting in the test
    with patch("src.clients.amadeus_client.asyncio.sleep", new=AsyncMock()):
        async with AmadeusClient(settings) as client:
            client._http = httpx.AsyncClient(transport=_build_transport(handler))
            result = await client.search_flight_offers(
                "YUL", "CDG", date(2025, 9, 1), "ECONOMY"
            )

    assert call_count == 3, f"Expected 3 data calls, got {call_count}"
    assert isinstance(result, list) and len(result) > 0


# ---------------------------------------------------------------------------
# Test: 500 retries up to 3 times, then returns []
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_500_retries_three_times_then_returns_empty() -> None:
    """Persistent 500 errors should exhaust retries and return an empty list."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if "oauth2/token" in str(request.url):
            return _json_response(200, _token_response())
        call_count += 1
        return _json_response(500, {"errors": [{"status": 500, "title": "Server Error"}]})

    settings = _make_settings()
    with patch("src.clients.amadeus_client.asyncio.sleep", new=AsyncMock()):
        async with AmadeusClient(settings) as client:
            client._http = httpx.AsyncClient(transport=_build_transport(handler))
            result = await client.search_flight_offers(
                "YUL", "CDG", date(2025, 9, 1), "ECONOMY"
            )

    # 3 retries = 1 initial attempt + 3 retry attempts = 4 total data endpoint calls
    assert call_count == 4, f"Expected 4 data calls (1 initial + 3 retries), got {call_count}"
    assert result == [], "Should return empty list after exhausting retries"


# ---------------------------------------------------------------------------
# Test: successful search returns a list of offer dicts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_flight_offers_success_returns_list_of_dicts() -> None:
    """A successful search call should return a list of raw offer dicts."""
    flight_data = _load_fixture("amadeus_flight_offers_sample.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _json_response(200, _token_response())
        return _json_response(200, flight_data)

    settings = _make_settings()
    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_build_transport(handler))
        result = await client.search_flight_offers(
            "YUL", "CDG", date(2025, 9, 1), "ECONOMY"
        )

    assert isinstance(result, list), "Result should be a list"
    assert len(result) == 1, "Fixture contains one offer"

    offer = result[0]
    # Spot-check the key fields the spec requires in the fixture
    assert offer["validatingAirlineCodes"] == ["AC"]
    assert offer["price"]["grandTotal"] == "612.50"
    assert offer["price"]["currency"] == "CAD"
    seg = offer["itineraries"][0]["segments"][0]
    assert seg["departure"]["iataCode"] == "YUL"
    assert seg["arrival"]["iataCode"] == "CDG"


# ---------------------------------------------------------------------------
# Test: verify_price success returns a dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_price_success_returns_dict() -> None:
    """A successful verify_price call should return a dict."""
    pricing_response = {
        "data": {
            "type": "flight-offers-pricing",
            "flightOffers": [{"id": "1", "price": {"grandTotal": "612.50"}}],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return _json_response(200, _token_response())
        return _json_response(200, pricing_response)

    settings = _make_settings()
    flight_data = _load_fixture("amadeus_flight_offers_sample.json")
    sample_offer = flight_data["data"][0]

    async with AmadeusClient(settings) as client:
        client._http = httpx.AsyncClient(transport=_build_transport(handler))
        result = await client.verify_price(sample_offer)

    assert result is not None, "verify_price should return a dict on success"
    assert isinstance(result, dict)
    assert result["type"] == "flight-offers-pricing"


# ---------------------------------------------------------------------------
# Test: TimeoutException returns [] without raising
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_returns_empty_list_without_raising() -> None:
    """A TimeoutException should be swallowed and return an empty list."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if "oauth2/token" in str(request.url):
            return _json_response(200, _token_response())
        call_count += 1
        raise httpx.TimeoutException("simulated timeout", request=request)

    settings = _make_settings()
    with patch("src.clients.amadeus_client.asyncio.sleep", new=AsyncMock()):
        async with AmadeusClient(settings) as client:
            client._http = httpx.AsyncClient(transport=_build_transport(handler))
            result = await client.search_flight_offers(
                "YUL", "CDG", date(2025, 9, 1), "ECONOMY"
            )

    # 2 retries allowed for network errors → 3 total attempts (initial + 2)
    assert call_count == 3, f"Expected 3 timeout attempts, got {call_count}"
    # Crucially: no exception escaped the client
    assert result == [], "Should return empty list on repeated timeout"


@pytest.mark.asyncio
async def test_log_request_uses_correct_column(monkeypatch: pytest.MonkeyPatch) -> None:
    """_log_request must write requested_at, not created_at."""
    monkeypatch.setenv("AMADEUS_ENV", "test")
    captured = {}

    async def fake_execute(stmt, params):
        captured.update(params)

    session = MagicMock()
    session.execute = fake_execute
    session.commit = AsyncMock()

    class FakeSettings:
        amadeus_env = "test"
        amadeus_client_id = "x"
        amadeus_client_secret = "y"
        amadeus_timeout_seconds = 10
        amadeus_max_concurrency = 1

    client = AmadeusClient(FakeSettings(), db_session=session)
    await client._log_request(
        endpoint="/v2/shopping/flight-offers",
        method="GET",
        status_code=200,
        duration_ms=42.0,
        success=True,
    )

    assert "requested_at" in captured
    assert "created_at" not in captured
