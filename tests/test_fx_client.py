"""Tests for the Frankfurter FX client."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.clients.fx_client import FxClient


@pytest.mark.asyncio
async def test_fetch_latest_parses_frankfurter_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-05-16",
                "rates": {"USD": 1.0875, "GBP": 0.8621},
            },
        )

    async with FxClient(transport=httpx.MockTransport(handler)) as client:
        rates = await client.fetch_latest("EUR", ["USD", "GBP"])

    assert rates == {"USD": Decimal("1.0875"), "GBP": Decimal("0.8621")}
    assert str(requests[0].url).startswith("https://api.frankfurter.dev/v1/latest")
    assert "base=EUR" in str(requests[0].url)
    assert "symbols=USD%2CGBP" in str(requests[0].url)


@pytest.mark.asyncio
async def test_fetch_for_date_writes_api_request_log(
    pg_schema_engine: tuple[Engine, str],
) -> None:
    engine, _schema_name = pg_schema_engine
    _clear_api_request_logs(engine)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "amount": 1.0,
                "base": "TRY",
                "date": "2026-05-16",
                "rates": {"USD": 0.031},
            },
        )

    with engine.begin() as connection:
        async with FxClient(
            db_session=connection,
            transport=httpx.MockTransport(handler),
        ) as client:
            rates = await client.fetch_for_date(date(2026, 5, 16), "TRY", ["USD"])

    assert rates == {"USD": Decimal("0.031")}
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT provider, endpoint, method, status_code, success
                FROM api_request_logs
                WHERE provider = 'FX_FRANKFURTER'
                """
            )
        ).one()

    assert row.provider == "FX_FRANKFURTER"
    assert row.endpoint == "/2026-05-16"
    assert row.method == "GET"
    assert row.status_code == 200
    assert row.success is True


def _clear_api_request_logs(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE TABLE api_request_logs")
