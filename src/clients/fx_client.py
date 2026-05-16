"""FX reference-rate client for Wave1."""

from __future__ import annotations

import inspect
import logging
import os
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

FX_PROVIDER_FRANKFURTER = "FRANKFURTER"
FX_LOG_PROVIDER = "FX_FRANKFURTER"
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"


class FxClient:
    """Async client for Frankfurter ECB reference rates."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        db_session: Any | None = None,
        base_url: str = FRANKFURTER_BASE_URL,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = (provider or os.getenv("FX_PROVIDER") or FX_PROVIDER_FRANKFURTER).upper()
        if self.provider != FX_PROVIDER_FRANKFURTER:
            raise ValueError(f"Unsupported FX_PROVIDER: {self.provider}")
        self._db_session = db_session
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "FxClient":
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds),
            transport=self._transport,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def fetch_latest(self, base: str, symbols: list[str]) -> dict[str, Decimal]:
        """Fetch latest rates for a base currency."""
        return await self._fetch("/latest", base=base, symbols=symbols)

    async def fetch_for_date(
        self,
        when: date,
        base: str,
        symbols: list[str],
    ) -> dict[str, Decimal]:
        """Fetch historical rates for a base currency and date."""
        return await self._fetch(f"/{when.isoformat()}", base=base, symbols=symbols)

    async def _fetch(self, endpoint: str, *, base: str, symbols: list[str]) -> dict[str, Decimal]:
        if not symbols:
            return {}

        close_after = False
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                transport=self._transport,
                follow_redirects=True,
            )
            close_after = True

        params = {
            "base": base.upper(),
            "symbols": ",".join(symbol.upper() for symbol in symbols),
        }
        url = f"{self._base_url}{endpoint}"
        started = time.monotonic()
        status_code: int | None = None
        error_message: str | None = None

        try:
            response = await self._http.get(url, params=params)
            status_code = response.status_code
            response.raise_for_status()
            body = response.json()
            rates = {
                str(currency).upper(): Decimal(str(rate))
                for currency, rate in body.get("rates", {}).items()
            }
            await self._log_request(
                endpoint=endpoint,
                method="GET",
                status_code=status_code,
                duration_ms=(time.monotonic() - started) * 1000,
                success=True,
            )
            return rates
        except (httpx.HTTPError, ValueError) as exc:
            error_message = str(exc)
            logger.warning("FX fetch failed for %s %s: %s", base, symbols, exc)
            await self._log_request(
                endpoint=endpoint,
                method="GET",
                status_code=status_code,
                duration_ms=(time.monotonic() - started) * 1000,
                success=False,
                error_message=error_message,
            )
            return {}
        finally:
            if close_after and self._http is not None:
                await self._http.aclose()
                self._http = None

    async def _log_request(
        self,
        *,
        endpoint: str,
        method: str,
        status_code: int | None,
        duration_ms: float,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        if self._db_session is None:
            return

        params = {
            "provider": FX_LOG_PROVIDER,
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "duration_ms": int(round(duration_ms)),
            "success": success,
            "error_message": error_message,
            "request_id": None,
            "estimated_cost_usd": Decimal("0"),
            "requested_at": datetime.now(UTC),
        }
        statement = text(
            """
            INSERT INTO api_request_logs (
                provider, endpoint, method, status_code, duration_ms,
                success, error_message, request_id, estimated_cost_usd, requested_at
            )
            VALUES (
                :provider, :endpoint, :method, :status_code, :duration_ms,
                :success, :error_message, :request_id, :estimated_cost_usd, :requested_at
            )
            """
        )

        try:
            result = self._db_session.execute(statement, params)
            if inspect.isawaitable(result):
                await result

            commit = getattr(self._db_session, "commit", None)
            if commit is not None and not isinstance(self._db_session, Connection):
                commit_result = commit()
                if inspect.isawaitable(commit_result):
                    await commit_result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write FX api_request_log: %s", exc)
