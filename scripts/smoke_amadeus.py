"""Live smoke test for AmadeusClient against the TEST sandbox.

Run with real credentials exported as env vars (never written to disk):

    AMADEUS_CLIENT_ID=xxx AMADEUS_CLIENT_SECRET=yyy \
        .venv/bin/python scripts/smoke_amadeus.py

NOTE ON ROUTE CHOICE
--------------------
The Amadeus TEST sandbox does NOT mirror production coverage.
Many Wave1 hub routes (e.g. IST->DXB, DXB->CAI) return HTTP 500
in TEST — this is a sandbox data gap, not a client bug.

Routes reliably covered in the Amadeus TEST sandbox:
  MAD -> BCN  (high-frequency short-haul, always seeded)
  LHR -> CDG  (high-frequency, always seeded)
  JFK -> LAX  (high-frequency, always seeded)

For production validation of Wave1 routes (IST, DXB, etc.) you must
switch AMADEUS_ENV=production with production credentials.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta

from src.config import load_settings
from src.clients.amadeus_client import AmadeusClient

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("smoke_amadeus")

# Sandbox-reliable route — NOT a Wave1 hub pair, but proves the client works.
# Switch to a Wave1 route only when AMADEUS_ENV=production.
SMOKE_ORIGIN = "MAD"
SMOKE_DESTINATION = "BCN"
# Use a date ~60 days out so the sandbox has inventory
SMOKE_DATE = date.today() + timedelta(days=60)


async def main() -> int:
    settings = load_settings()

    if not settings.amadeus_client_id or not settings.amadeus_client_secret:
        logger.error(
            "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set as env vars."
        )
        return 1

    env_label = settings.amadeus_env.upper()
    logger.info(
        "Connecting to Amadeus %s env — %s → %s on %s",
        env_label, SMOKE_ORIGIN, SMOKE_DESTINATION, SMOKE_DATE,
    )

    async with AmadeusClient(settings) as client:
        offers = await client.search_flight_offers(
            origin=SMOKE_ORIGIN,
            destination=SMOKE_DESTINATION,
            departure_date=SMOKE_DATE,
            cabin="ECONOMY",
            adults=1,
            max_offers=3,
        )

    if not offers:
        logger.error(
            "Got 0 offers — check credentials and AMADEUS_ENV. "
            "If env=test, the route %s->%s may not be seeded in the sandbox.",
            SMOKE_ORIGIN, SMOKE_DESTINATION,
        )
        return 1

    logger.info("Got %d offer(s) from %s env ✓", len(offers), env_label)
    for i, offer in enumerate(offers, 1):
        price = offer.get("price", {})
        seg = offer["itineraries"][0]["segments"][0]
        airlines = offer.get("validatingAirlineCodes", [])
        logger.info(
            "  Offer %d: %s  %s->%s  %s %s",
            i,
            "/".join(airlines),
            seg["departure"]["iataCode"],
            seg["arrival"]["iataCode"],
            price.get("grandTotal", "?"),
            price.get("currency", "?"),
        )

    # Also smoke verify_price on the first offer
    logger.info("Testing verify_price on offer 1...")
    async with AmadeusClient(settings) as client:
        verified = await client.verify_price(offers[0])

    if verified is None:
        logger.warning(
            "verify_price returned None — this is expected in TEST env "
            "(the /pricing endpoint is often unavailable in the sandbox)."
        )
    else:
        logger.info("verify_price returned a dict ✓")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
