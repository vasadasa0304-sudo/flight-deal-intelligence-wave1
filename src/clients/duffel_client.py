"""Duffel API client for secondary fare verification (phantom fare two-source rule)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from src.config import Settings

logger = logging.getLogger(__name__)

DUFFEL_BASE_URL = "https://api.duffel.com"
DUFFEL_API_VERSION = "v2"

_CABIN_MAP: dict[str, str] = {
    "ECONOMY": "economy",
    "PREMIUM_ECONOMY": "premium_economy",
    "BUSINESS": "business",
    "FIRST": "first",
}


@dataclass(frozen=True)
class DuffelClient:
    """Duffel API client — used as second source for PHANTOM_FARE verification."""

    settings: Settings
    timeout_seconds: float = 20.0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.duffel_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Duffel-Version": DUFFEL_API_VERSION,
        }

    async def verify_offer(self, raw_response: dict[str, Any]) -> dict[str, Any] | None:
        """Search Duffel for the same route and return a price dict for the verifier.

        Parses the Amadeus raw_response stored on a PriceObservation to extract
        the route, searches Duffel's offer_requests endpoint, and returns the
        cheapest matching offer in the format expected by _extract_verified_price:
            {"price": {"total": "<amount>", "currency": "<ISO>"}}

        Returns None if the route cannot be determined or Duffel returns no offers.
        """
        route = _extract_route(raw_response)
        if route is None:
            logger.debug("Cannot extract route from raw_response; skipping Duffel check.")
            return None

        origin, destination, departure_date, cabin, airline_code = route
        duffel_cabin = _CABIN_MAP.get(cabin, "economy")

        request_body = {
            "data": {
                "slices": [
                    {
                        "origin": origin,
                        "destination": destination,
                        "departure_date": departure_date,
                    }
                ],
                "passengers": [{"type": "adult"}],
                "cabin_class": duffel_cabin,
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.post(
                    f"{DUFFEL_BASE_URL}/air/offer_requests",
                    json=request_body,
                    headers=self._headers(),
                    params={"return_offers": "true"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Duffel API %s for %s→%s: %s",
                    exc.response.status_code,
                    origin,
                    destination,
                    exc,
                )
                return None
            except httpx.RequestError as exc:
                logger.warning("Duffel network error for %s→%s: %s", origin, destination, exc)
                return None

        try:
            offers = resp.json().get("data", {}).get("offers", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Duffel response parse error: %s", exc)
            return None

        best = _best_offer(offers, airline_code)
        if best is None:
            logger.debug(
                "No Duffel offer found for %s %s→%s on %s",
                airline_code,
                origin,
                destination,
                departure_date,
            )
            return None

        logger.info(
            "Duffel confirmed %s %s→%s at %s %s",
            airline_code,
            origin,
            destination,
            best["total_amount"],
            best["total_currency"],
        )
        return {"price": {"total": best["total_amount"], "currency": best["total_currency"]}}


def _extract_route(
    raw_response: dict[str, Any],
) -> tuple[str, str, str, str, str] | None:
    """Extract (origin, destination, departure_date, cabin, airline_code) from an Amadeus offer."""
    try:
        itineraries = raw_response.get("itineraries", [])
        if not itineraries:
            return None
        segments = itineraries[0].get("segments", [])
        if not segments:
            return None

        origin = segments[0]["departure"]["iataCode"].upper()
        destination = segments[-1]["arrival"]["iataCode"].upper()
        departure_date = segments[0]["departure"]["at"][:10]  # YYYY-MM-DD from ISO datetime

        validating = raw_response.get("validatingAirlineCodes", [])
        airline_code = (
            validating[0] if validating else segments[0].get("carrierCode", "")
        ).upper()

        cabin = "ECONOMY"
        pricings = raw_response.get("travelerPricings", [])
        if pricings:
            fare_details = pricings[0].get("fareDetailsBySegment", [])
            if fare_details:
                cabin = fare_details[0].get("cabin", "ECONOMY").upper()

        if not (origin and destination and departure_date and airline_code):
            return None

        return origin, destination, departure_date, cabin, airline_code
    except (KeyError, IndexError, AttributeError, TypeError):
        return None


def _best_offer(offers: list[dict[str, Any]], preferred_airline: str) -> dict[str, Any] | None:
    """Return the cheapest offer from the preferred airline, or cheapest overall."""
    if not offers:
        return None

    def _amount(offer: dict[str, Any]) -> Decimal:
        try:
            return Decimal(str(offer.get("total_amount", "9999999")))
        except InvalidOperation:
            return Decimal("9999999")

    airline_offers = [
        o
        for o in offers
        if o.get("owner", {}).get("iata_code", "").upper() == preferred_airline
    ]
    candidates = airline_offers if airline_offers else offers
    return min(candidates, key=_amount)
