"""Live smoke test for AmadeusClient — multi-route/date probe matrix.

Probes a matrix of (route, departure_date) combinations against the
Amadeus TEST sandbox to discover which combinations actually return data.
Stops as soon as the first hit is confirmed, then prints a summary.

Run with real credentials exported as env vars (never written to disk):

    AMADEUS_CLIENT_ID=xxx AMADEUS_CLIENT_SECRET=yyy \\
        .venv/bin/python scripts/smoke_amadeus.py

Exit codes:
    0  at least one combination returned offers
    1  AMADEUS_CLIENT_ID or AMADEUS_CLIENT_SECRET not set
    2  all probes returned 0 offers (sandbox may be down or credentials
       are invalid for this environment)

NOTE ON ROUTE CHOICE
--------------------
The Amadeus TEST sandbox does NOT mirror production coverage.
Many Wave1 hub routes (e.g. IST→DXB) return HTTP 500 in TEST because
the sandbox has no data for them — this is not a client bug.  This script
probes a range of routes and dates to find what the sandbox actually serves.
For Wave1 hub routes use production credentials with AMADEUS_ENV=production.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from src.clients.amadeus_client import AmadeusClient
from src.config import load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("smoke_amadeus")
logger.setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Routes probed in order.  Starts with historically seeded test-sandbox routes,
# then adds Wave1-adjacent routes to catch any sandbox expansions.
PROBE_ROUTES: list[tuple[str, str]] = [
    ("MAD", "BCN"),
    ("LHR", "CDG"),
    ("JFK", "LHR"),
    ("MAD", "JFK"),
    ("DXB", "LHR"),
    ("IST", "LHR"),
]

# Departure date offsets (days from today) tried for each route.
DATE_OFFSETS: list[int] = [14, 30, 60, 90]


@dataclass
class _ProbeResult:
    origin: str
    destination: str
    departure_date: date
    offer_count: int
    cheapest_price: str | None
    cheapest_currency: str | None
    carrier: str | None

    @property
    def route_label(self) -> str:
        return f"{self.origin}→{self.destination}"


def _extract_first_offer_info(
    offer: dict,
) -> tuple[str | None, str | None, str | None]:
    """Return (grandTotal, currency, first_validating_carrier) from one offer."""
    price = offer.get("price", {})
    total = price.get("grandTotal") or price.get("total")
    currency = price.get("currency")
    carriers: list[str] = offer.get("validatingAirlineCodes", [])
    return total, currency, (carriers[0] if carriers else None)


async def main() -> int:
    settings = load_settings()

    if not settings.amadeus_client_id or not settings.amadeus_client_secret:
        logger.error(
            "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set as env vars."
        )
        return 1

    today = date.today()
    probe_dates = [today + timedelta(days=d) for d in DATE_OFFSETS]
    env_label = settings.amadeus_env.upper()
    logger.info(
        "Amadeus %s env — probing %d routes × %d dates (%d combinations)",
        env_label,
        len(PROBE_ROUTES),
        len(probe_dates),
        len(PROBE_ROUTES) * len(probe_dates),
    )

    results: list[_ProbeResult] = []
    first_hit_offer: dict | None = None

    async with AmadeusClient(settings) as client:
        outer_done = False
        for origin, destination in PROBE_ROUTES:
            if outer_done:
                break
            for dep_date in probe_dates:
                route_label = f"{origin}→{destination}"
                logger.debug("Probing %s on %s...", route_label, dep_date)

                offers = await client.search_flight_offers(
                    origin=origin,
                    destination=destination,
                    departure_date=dep_date,
                    cabin="ECONOMY",
                    adults=1,
                    max_offers=2,
                )

                if offers:
                    total, currency, carrier = _extract_first_offer_info(offers[0])
                    results.append(
                        _ProbeResult(
                            origin=origin,
                            destination=destination,
                            departure_date=dep_date,
                            offer_count=len(offers),
                            cheapest_price=total,
                            cheapest_currency=currency,
                            carrier=carrier,
                        )
                    )
                    logger.info(
                        "✓ %s %s — %d offer(s), cheapest %s %s (%s)",
                        route_label,
                        dep_date,
                        len(offers),
                        total or "?",
                        currency or "?",
                        carrier or "?",
                    )
                    first_hit_offer = offers[0]
                    outer_done = True
                    break
                else:
                    results.append(
                        _ProbeResult(
                            origin=origin,
                            destination=destination,
                            departure_date=dep_date,
                            offer_count=0,
                            cheapest_price=None,
                            cheapest_currency=None,
                            carrier=None,
                        )
                    )
                    logger.info("✗ %s %s — 0 offers", route_label, dep_date)

        if first_hit_offer is not None:
            logger.info("Running verify_price on first offer of first hit...")
            verified = await client.verify_price(first_hit_offer)
            if verified is None:
                logger.info(
                    "verify_price → None  "
                    "(expected in TEST env; /pricing is often unavailable in the sandbox)"
                )
            else:
                logger.info("verify_price → dict ✓")

    # --- Summary table ---
    col_route = max((len(r.route_label) for r in results), default=9)
    header = f"  {'Route':<{col_route}}  {'Date':<10}  Result  Offers"
    bar = "  " + "-" * (len(header) - 2)

    print()
    print("  " + "=" * (len(header) - 2))
    print(header)
    print(bar)
    for r in results:
        if r.offer_count == 0:
            symbol = "✗"
            detail = "0 offers"
        else:
            price_str = (
                f"{r.cheapest_price} {r.cheapest_currency}"
                if r.cheapest_price
                else "?"
            )
            detail = (
                f"{r.offer_count} offer(s), cheapest {price_str} ({r.carrier or '?'})"
            )
            symbol = "✓"
        print(
            f"  {r.route_label:<{col_route}}  {str(r.departure_date):<10}  "
            f"{symbol:<6}  {detail}"
        )
    print("  " + "=" * (len(header) - 2))
    print()

    if first_hit_offer is None:
        logger.error(
            "All %d probe(s) returned 0 offers. "
            "The sandbox may be down, or the credentials may be invalid for env=%s.",
            len(results),
            env_label,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
