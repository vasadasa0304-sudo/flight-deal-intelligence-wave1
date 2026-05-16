"""Amadeus Self-Service API async client — Wave 1.

Handles OAuth token lifecycle, flight-offer search, and price verification.
All methods return raw dicts; typed parsing is the downstream parser's job.

Usage:
    async with AmadeusClient(settings) as client:
        offers = await client.search_flight_offers(
            origin="YUL", destination="CDG",
            departure_date=date(2025, 9, 1), cabin="ECONOMY",
        )
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Logger — one per module, standard Python practice
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base URLs — pinned explicitly per spec.  Never derive one from the other.
# ---------------------------------------------------------------------------
_BASE_URL_TEST = "https://test.api.amadeus.com"
_BASE_URL_PROD = "https://api.amadeus.com"


class _TokenCache:
    """Holds a single OAuth bearer token and knows when it needs refreshing.

    We subtract 60 s from expires_in so we refresh *before* the server
    rejects us rather than after.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        # Unix timestamp after which we must re-fetch
        self._expires_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        """True if the cached token is still good."""
        return self._token is not None and time.monotonic() < self._expires_at

    def store(self, token: str, expires_in: int) -> None:
        """Cache token with a 60-second safety buffer."""
        self._token = token
        self._expires_at = time.monotonic() + max(0, expires_in - 60)

    def get(self) -> str | None:
        """Return the token string if valid, else None."""
        return self._token if self.is_valid else None

    def invalidate(self) -> None:
        """Force a refresh on the next call (used after a 401)."""
        self._expires_at = 0.0


class AmadeusClient:
    """Async Amadeus Self-Service API client.

    Create one instance per process.  Use as an async context manager so
    the underlying httpx.AsyncClient is properly closed:

        async with AmadeusClient(settings) as client:
            offers = await client.search_flight_offers(...)

    Args:
        settings: A Settings object that exposes the Amadeus env vars.
        db_session: Optional SQLAlchemy async session for request logging.
                    If None, logging is skipped silently.
    """

    def __init__(self, settings: Any, db_session: Any | None = None) -> None:
        # Decide which base URL to use.  Production must be set *explicitly*.
        env = (settings.amadeus_env or "test").strip().lower()
        if env == "production":
            self._base_url = _BASE_URL_PROD
        else:
            # Any non-production value → test.  Never silently flip to prod.
            if env != "test":
                logger.warning(
                    "Unknown AMADEUS_ENV=%r — defaulting to test environment.", env
                )
            self._base_url = _BASE_URL_TEST

        self._client_id: str = settings.amadeus_client_id
        self._client_secret: str = settings.amadeus_client_secret
        self._timeout: float = float(settings.amadeus_timeout_seconds)
        self._is_test_env: bool = env != "production"

        # One semaphore caps concurrent *data* endpoint calls (not token calls)
        self._semaphore = asyncio.Semaphore(int(settings.amadeus_max_concurrency))

        self._token_cache = _TokenCache()
        self._db_session = db_session

        # The shared HTTP client is created lazily in __aenter__
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Async context manager — ensures the HTTP client is always closed
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AmadeusClient":
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Internal: OAuth token management
    # ------------------------------------------------------------------

    async def _fetch_token(self) -> str:
        """Request a new OAuth token from Amadeus.

        Uses the client-credentials grant.  This call is NOT protected by
        the concurrency semaphore — token fetches are lightweight and must
        not be blocked by a saturated data-endpoint pool.

        Returns:
            The bearer token string.

        Raises:
            RuntimeError: If the token request fails after all retries.
        """
        assert self._http is not None, "Call inside 'async with AmadeusClient()'"

        url = f"{self._base_url}/v1/security/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        # Token endpoint gets up to 3 simple retries (no backoff needed here)
        for attempt in range(3):
            try:
                resp = await self._http.post(url, data=payload)
                resp.raise_for_status()
                body = resp.json()
                token: str = body["access_token"]
                expires_in: int = int(body.get("expires_in", 1799))
                self._token_cache.store(token, expires_in)
                logger.debug("Fetched new Amadeus token; expires_in=%d s", expires_in)
                return token
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning(
                    "Token fetch attempt %d/3 failed: %s", attempt + 1, exc
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError("Failed to obtain Amadeus OAuth token after 3 attempts.")

    async def _get_token(self) -> str:
        """Return a valid token, refreshing if necessary."""
        token = self._token_cache.get()
        if token:
            return token
        return await self._fetch_token()

    # ------------------------------------------------------------------
    # Internal: logging to api_request_logs
    # ------------------------------------------------------------------

    async def _log_request(
        self,
        *,
        endpoint: str,
        method: str,
        status_code: int | None,
        duration_ms: float,
        success: bool,
        error_message: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Write one row to api_request_logs.

        Silently swallows DB errors — a logging failure must never crash
        a data call.

        Args:
            endpoint:      e.g. '/v2/shopping/flight-offers'
            method:        HTTP verb, uppercase
            status_code:   HTTP response code, or None on network error
            duration_ms:   Wall-clock time for the request in milliseconds
            success:       True if the call returned usable data
            error_message: Human-readable error on failure
            request_id:    Value of x-amzn-RequestId response header
        """
        if self._db_session is None:
            return

        # estimated_cost_usd is always 0 in test; you may expand this later
        estimated_cost_usd = 0.0

        try:
            # Import here to avoid a hard dependency when the session is None
            from sqlalchemy import text  # type: ignore

            await self._db_session.execute(
                text(
                    """
                    INSERT INTO api_request_logs
                        (provider, endpoint, method, status_code, duration_ms,
                         success, error_message, request_id, estimated_cost_usd,
                         created_at)
                    VALUES
                        (:provider, :endpoint, :method, :status_code, :duration_ms,
                         :success, :error_message, :request_id, :estimated_cost_usd,
                         :created_at)
                    """
                ),
                {
                    "provider": "AMADEUS",
                    "endpoint": endpoint,
                    "method": method,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "success": success,
                    "error_message": error_message,
                    "request_id": request_id,
                    "estimated_cost_usd": estimated_cost_usd,
                    "created_at": datetime.utcnow(),
                },
            )
            await self._db_session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write api_request_log: %s", exc)

    # ------------------------------------------------------------------
    # Internal: core request executor with retry / backoff
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        _token_refreshed: bool = False,
    ) -> httpx.Response | None:
        """Execute one authenticated request with retry / backoff logic.

        This is the single choke-point for all data-endpoint calls.  The
        concurrency semaphore is acquired here so it covers every retry.

        Retry rules (per spec):
          - 429  → exponential backoff, up to 3 retries; honour Retry-After
          - 5xx  → 3 retries with 1 s backoff
          - Timeout / NetworkError → 2 retries
          - 400, 403, 404 → fail immediately (no retry)
          - 401  → refresh token once and retry the entire call once

        Args:
            method:           HTTP verb ('GET' or 'POST')
            endpoint:         Path starting with '/', e.g. '/v2/shopping/...'
            params:           Query-string parameters (GET)
            json:             Request body (POST)
            _token_refreshed: Internal flag — prevents infinite 401 loops

        Returns:
            The httpx.Response, or None if all retries are exhausted.
        """
        assert self._http is not None, "Call inside 'async with AmadeusClient()'"

        url = f"{self._base_url}{endpoint}"
        max_retries_5xx = 3
        max_retries_network = 2
        attempt_5xx = 0
        attempt_network = 0

        async with self._semaphore:
            while True:
                token = await self._get_token()
                headers = {"Authorization": f"Bearer {token}"}

                t_start = time.monotonic()
                status_code: int | None = None
                error_message: str | None = None
                request_id: str | None = None
                response: httpx.Response | None = None

                try:
                    response = await self._http.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json,
                    )
                    status_code = response.status_code
                    request_id = response.headers.get("x-amzn-RequestId")
                    duration_ms = (time.monotonic() - t_start) * 1000

                    # ---- 401: refresh token and retry once ----
                    if status_code == 401 and not _token_refreshed:
                        logger.info("Got 401; refreshing token and retrying once.")
                        self._token_cache.invalidate()
                        await self._fetch_token()
                        await self._log_request(
                            endpoint=endpoint,
                            method=method,
                            status_code=401,
                            duration_ms=duration_ms,
                            success=False,
                            error_message="401 — token refreshed",
                            request_id=request_id,
                        )
                        # Recurse with the flag set so we don't loop forever
                        return await self._request(
                            method,
                            endpoint,
                            params=params,
                            json=json,
                            _token_refreshed=True,
                        )

                    # ---- 429: back off and retry (max 3) ----
                    if status_code == 429:
                        retry_after = float(
                            response.headers.get("Retry-After", 1)
                        )
                        # Exponential backoff, but honour the server's hint
                        backoff = max(retry_after, 2 ** attempt_5xx)
                        attempt_5xx += 1
                        if attempt_5xx > max_retries_5xx:
                            error_message = "429 — max retries exceeded"
                            await self._log_request(
                                endpoint=endpoint,
                                method=method,
                                status_code=429,
                                duration_ms=duration_ms,
                                success=False,
                                error_message=error_message,
                                request_id=request_id,
                            )
                            return None
                        logger.warning(
                            "429 rate-limited on %s; sleeping %.1f s (attempt %d/3)",
                            endpoint, backoff, attempt_5xx,
                        )
                        await self._log_request(
                            endpoint=endpoint,
                            method=method,
                            status_code=429,
                            duration_ms=duration_ms,
                            success=False,
                            error_message=f"429 — retry {attempt_5xx}",
                            request_id=request_id,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    # ---- 5xx: retry up to 3 times ----
                    if 500 <= status_code <= 599:
                        attempt_5xx += 1
                        if attempt_5xx > max_retries_5xx:
                            error_message = f"{status_code} — max retries exceeded"
                            await self._log_request(
                                endpoint=endpoint,
                                method=method,
                                status_code=status_code,
                                duration_ms=duration_ms,
                                success=False,
                                error_message=error_message,
                                request_id=request_id,
                            )
                            return None
                        logger.warning(
                            "%d error on %s; retry %d/3",
                            status_code, endpoint, attempt_5xx,
                        )
                        await self._log_request(
                            endpoint=endpoint,
                            method=method,
                            status_code=status_code,
                            duration_ms=duration_ms,
                            success=False,
                            error_message=f"{status_code} — retry {attempt_5xx}",
                            request_id=request_id,
                        )
                        await asyncio.sleep(1.0)
                        continue

                    # ---- Terminal 4xx (not 401/429): fail immediately ----
                    if 400 <= status_code <= 499:
                        error_message = (
                            f"HTTP {status_code} — {response.text[:200]}"
                        )
                        logger.error("Non-retryable error on %s: %s", endpoint, error_message)
                        await self._log_request(
                            endpoint=endpoint,
                            method=method,
                            status_code=status_code,
                            duration_ms=duration_ms,
                            success=False,
                            error_message=error_message,
                            request_id=request_id,
                        )
                        return None

                    # ---- Success ----
                    await self._log_request(
                        endpoint=endpoint,
                        method=method,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        success=True,
                        request_id=request_id,
                    )
                    return response

                except httpx.TimeoutException as exc:
                    duration_ms = (time.monotonic() - t_start) * 1000
                    attempt_network += 1
                    error_message = f"Timeout: {exc}"
                    if attempt_network > max_retries_network:
                        logger.error("Timeout on %s after %d retries.", endpoint, max_retries_network)
                        await self._log_request(
                            endpoint=endpoint,
                            method=method,
                            status_code=None,
                            duration_ms=duration_ms,
                            success=False,
                            error_message=error_message,
                        )
                        return None
                    logger.warning(
                        "Timeout on %s; retry %d/%d", endpoint, attempt_network, max_retries_network
                    )
                    await asyncio.sleep(1.0)

                except httpx.NetworkError as exc:
                    duration_ms = (time.monotonic() - t_start) * 1000
                    attempt_network += 1
                    error_message = f"NetworkError: {exc}"
                    if attempt_network > max_retries_network:
                        logger.error("NetworkError on %s after %d retries.", endpoint, max_retries_network)
                        await self._log_request(
                            endpoint=endpoint,
                            method=method,
                            status_code=None,
                            duration_ms=duration_ms,
                            success=False,
                            error_message=error_message,
                        )
                        return None
                    logger.warning(
                        "NetworkError on %s; retry %d/%d", endpoint, attempt_network, max_retries_network
                    )
                    await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Search for available flight offers.

        Maps to GET /v2/shopping/flight-offers.

        Args:
            origin:         IATA airport code for the origin, e.g. 'YUL'
            destination:    IATA airport code for the destination, e.g. 'CDG'
            departure_date: Date of departure
            cabin:          Cabin class: 'ECONOMY', 'PREMIUM_ECONOMY',
                            'BUSINESS', or 'FIRST'
            adults:         Number of adult passengers (default 1)
            currency_code:  ISO 4217 currency for prices, e.g. 'CAD'
                            (defaults to USD if omitted)
            non_stop:       If True, only return non-stop flights
            max_offers:     Maximum number of offers to return (default 5)

        Returns:
            A list of raw offer dicts from the Amadeus API.
            Returns an empty list on any hard failure — never raises.
        """
        endpoint = "/v2/shopping/flight-offers"
        params: dict[str, Any] = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": departure_date.isoformat(),
            "adults": adults,
            "travelClass": cabin.upper(),
            "nonStop": str(non_stop).lower(),  # API expects "true"/"false"
            "max": max_offers,
        }
        if currency_code:
            params["currencyCode"] = currency_code.upper()

        try:
            response = await self._request("GET", endpoint, params=params)
            if response is None:
                return []
            body = response.json()
            # The data array lives under "data" in the Amadeus response shape
            return body.get("data", [])
        except Exception as exc:  # noqa: BLE001
            # Belt-and-suspenders: nothing should escape to the caller
            logger.error("Unexpected error in search_flight_offers: %s", exc)
            return []

    async def verify_price(
        self,
        flight_offer: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Confirm the current price for a specific flight offer.

        Maps to POST /v1/shopping/flight-offers/pricing.

        Note: This endpoint is frequently unavailable in the Amadeus *test*
        environment and returns a 404 or 500.  The method returns None in
        that case rather than raising, so callers can decide whether to
        proceed with the unverified offer price.

        Args:
            flight_offer: A single offer dict as returned by
                          search_flight_offers().

        Returns:
            The first element of the 'data' array from the pricing response,
            or None if the endpoint is unavailable or the call fails.
        """
        endpoint = "/v1/shopping/flight-offers/pricing"
        body = {
            "data": {
                "type": "flight-offers-pricing",
                "flightOffers": [flight_offer],
            }
        }

        try:
            response = await self._request("POST", endpoint, json=body)
            if response is None:
                return None
            data = response.json()
            offers = data.get("data", {})
            # The pricing endpoint wraps the result differently from search
            return offers if isinstance(offers, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error in verify_price: %s", exc)
            return None
