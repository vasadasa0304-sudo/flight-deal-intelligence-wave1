"""Amadeus Self-Service API async client for Wave1 fare monitoring.

Usage:
    async with AmadeusClient(settings) as client:
        offers = await client.search_flight_offers(
            origin="IST", destination="DXB",
            departure_date=date(2026, 6, 1), cabin="ECONOMY",
        )

The client is NOT thread-safe but is safe for concurrent async tasks up to
the concurrency limit controlled by self._semaphore.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import Any

import httpx
from sqlalchemy.orm import Session

from src.config import Settings

logger = logging.getLogger(__name__)

_TEST_BASE_URL = "https://test.api.amadeus.com"
_PROD_BASE_URL = "https://api.amadeus.com"

_TOKEN_PATH = "/v1/security/oauth2/token"
_OFFERS_PATH = "/v2/shopping/flight-offers"
_PRICING_PATH = "/v1/shopping/flight-offers/pricing"

_TOKEN_EXPIRY_BUFFER = 60
_MAX_RETRY_429 = 3
_MAX_RETRY_5XX = 3
_MAX_RETRY_NETWORK = 2
_BACKOFF_BASE = 1.0


class _TokenCache:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str | None:
        if self._token and time.monotonic() < self._expires_at - _TOKEN_EXPIRY_BUFFER:
            return self._token
        return None

    def store(self, token: str, expires_in: int) -> None:
        self._token = token
        self._expires_at = time.monotonic() + expires_in

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0


class AmadeusClient:
    """Async Amadeus Self-Service API client.

    Must be used as an async context manager.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        _transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = _transport
        self._http: httpx.AsyncClient | None = None
        self._cache = _TokenCache()
        self._semaphore = asyncio.Semaphore(settings.amadeus_max_concurrency)

    async def __aenter__(self) -> "AmadeusClient":
        kwargs: dict[str, Any] = {
            "timeout": self._settings.amadeus_timeout_seconds,
            "base_url": self._base_url,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        self._http = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def search_flight_offers(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: str,
        adults: int = 1,
        currency_code: str | None = None,
        non_stop: bool = True,
        max_offers: int = 5,
    ) -> list[dict[str, Any]]:
        """GET /v2/shopping/flight-offers. Returns [] on any failure."""
        params: dict[str, Any] = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date.isoformat(),
            "adults": adults,
            "travelClass": cabin.upper(),
            "nonStop": str(non_stop).lower(),
            "max": max_offers,
        }
        if currency_code:
            params["currencyCode"] = currency_code

        raw = await self._call(method="GET", path=_OFFERS_PATH, params=params)
        if raw is None:
            return []
        return raw.get("data", [])

    async def verify_price(
        self,
        flight_offer: dict[str, Any],
    ) -> dict[str, Any] | None:
        """POST /v1/shopping/flight-offers/pricing. Returns None on failure."""
        body = {"data": {"type": "flight-offers-pricing", "flightOffers": [flight_offer]}}
        raw = await self._call(method="POST", path=_PRICING_PATH, json=body)
        if raw is None:
            return None
        return raw.get("data")

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = self._cache.get()
            if cached:
                return cached
        assert self._http is not None
        response = await self._http.post(
            _TOKEN_PATH,
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.amadeus_client_id or "",
                "client_secret": self._settings.amadeus_client_secret or "",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        token: str = payload["access_token"]
        expires_in: int = int(payload.get("expires_in", 1799))
        self._cache.store(token, expires_in)
        logger.debug("OAuth token refreshed; expires_in=%d", expires_in)
        return token

    async def _call(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        session: Session | None = None,
        _token_refreshed: bool = False,
    ) -> dict[str, Any] | None:
        assert self._http is not None

        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        retry_429 = retry_5xx = retry_net = 0

        while True:
            started = time.monotonic()
            status_code: int | None = None
            error_message: str | None = None
            request_id: str | None = None

            try:
                async with self._semaphore:
                    response = await self._http.request(
                        method, path, headers=headers, params=params, json=json,
                    )

                status_code = response.status_code
                request_id = response.headers.get("x-amzn-RequestId")
                duration_ms = int((time.monotonic() - started) * 1000)

                if status_code == 401 and not _token_refreshed:
                    logger.warning("401 on %s; refreshing token once", path)
                    self._cache.invalidate()
                    return await self._call(
                        method=method, path=path, params=params,
                        json=json, session=session, _token_refreshed=True,
                    )

                if status_code == 429 and retry_429 < _MAX_RETRY_429:
                    delay = float(
                        response.headers.get("Retry-After", _BACKOFF_BASE * (2 ** retry_429))
                    )
                    logger.warning("429 on %s; retry %d after %.1fs", path, retry_429 + 1, delay)
                    await asyncio.sleep(delay)
                    retry_429 += 1
                    continue

                if 500 <= status_code <= 599 and retry_5xx < _MAX_RETRY_5XX:
                    delay = _BACKOFF_BASE * (2 ** retry_5xx)
                    logger.warning(
                        "%d on %s; retry %d after %.1fs", status_code, path, retry_5xx + 1, delay
                    )
                    await asyncio.sleep(delay)
                    retry_5xx += 1
                    continue

                success = 200 <= status_code < 300
                if not success:
                    error_message = f"HTTP {status_code}: {response.text[:200]}"
                    logger.warning("Amadeus %s %s: %s", method, path, error_message)

                await self._log_request(
                    path=path, method=method, status_code=status_code,
                    duration_ms=duration_ms, success=success,
                    error_message=error_message, request_id=request_id,
                    session=session,
                )
                return response.json() if success else None

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                if retry_net < _MAX_RETRY_NETWORK:
                    delay = _BACKOFF_BASE * (2 ** retry_net)
                    logger.warning(
                        "Network error on %s (%s); retry %d after %.1fs",
                        path, type(exc).__name__, retry_net + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    retry_net += 1
                    continue

                error_message = f"{type(exc).__name__}: {exc}"
                logger.error("Amadeus %s %s failed after retries: %s", method, path, error_message)
                await self._log_request(
                    path=path, method=method, status_code=None,
                    duration_ms=duration_ms, success=False,
                    error_message=error_message, session=session,
                )
                return None

    async def _log_request(
        self,
        *,
        path: str,
        method: str,
        status_code: int | None,
        duration_ms: int,
        success: bool,
        error_message: str | None = None,
        request_id: str | None = None,
        session: Session | None = None,
    ) -> None:
        """Write to api_request_logs. Silently catches all DB errors."""
        if session is None:
            return
        try:
            import sqlalchemy
            session.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO api_request_logs (
                        provider, endpoint, method, status_code,
                        duration_ms, success, error_message, request_id,
                        estimated_cost_usd
                    ) VALUES (
                        :provider, :endpoint, :method, :status_code,
                        :duration_ms, :success, :error_message, :request_id,
                        :estimated_cost_usd
                    )
                    """
                ),
                {
                    "provider": "AMADEUS",
                    "endpoint": path,
                    "method": method,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "success": success,
                    "error_message": error_message,
                    "request_id": request_id,
                    "estimated_cost_usd": 0.0,
                },
            )
            session.flush()
        except Exception as exc:
            logger.warning("Failed to log Amadeus request: %s", exc)

    @property
    def _base_url(self) -> str:
        if self._settings.amadeus_env == "production":
            return _PROD_BASE_URL
        return _TEST_BASE_URL
