"""Parse provider fare payloads into price observation rows."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.utils.currency import convert_amount
from src.utils.hashing import make_request_hash

logger = logging.getLogger(__name__)

PROVIDER_AMADEUS = "AMADEUS"


def parse_offer_payload(
    payload: dict[str, Any],
    watch_row: Any,
    observed_at: datetime,
    session: Any | None = None,
) -> dict[str, Any] | None:
    """Parse one Amadeus offer, or select and parse one offer from a response.

    Returns a dict shaped for the price_observations table, or None if the
    payload cannot produce a valid observation.
    """
    try:
        selected_payload = _select_payload(payload, watch_row)
        if selected_payload is None:
            return None

        watch_id = int(_watch_value(watch_row, "watch_id"))
        route_id = str(_watch_value(watch_row, "route_id"))
        origin = str(_watch_value(watch_row, "origin", _route_origin(route_id))).upper()
        destination = str(
            _watch_value(watch_row, "destination", _route_destination(route_id))
        ).upper()
        cabin = str(_watch_value(watch_row, "cabin")).upper()
        booking_window_days = int(_watch_value(watch_row, "booking_window_days"))

        airline_code = _carrier_code(selected_payload)
        departure_date = _departure_date(selected_payload)
        return_date = _return_date(selected_payload)
        native_currency = str(selected_payload["price"]["currency"]).upper()
        native_price = Decimal(str(selected_payload["price"]["grandTotal"]))
        taxes_fees = _taxes_fees(selected_payload)
        observed_at_utc = _as_utc(observed_at)
        polling_bucket_hour = _bucket_hour(observed_at_utc)
        display_currency = _display_currency()

        if native_currency == display_currency:
            display_price: Decimal = native_price
            fx_rate_used: Decimal | None = Decimal("1")
        else:
            conversion = (
                convert_amount(
                    native_price,
                    from_currency=native_currency,
                    to_currency=display_currency,
                    rate_date=observed_at_utc.date(),
                    session=session,
                )
                if session is not None
                else None
            )
            if conversion is None:
                logger.warning(
                    "No FX rate available for %s→%s; storing display_price=native_price.",
                    native_currency,
                    display_currency,
                )
                display_price = native_price
                display_currency = native_currency
                fx_rate_used = None
            else:
                display_price, fx_rate_used = conversion

        request_hash = make_request_hash(
            provider=PROVIDER_AMADEUS,
            route_id=route_id,
            watch_id=watch_id,
            airline_code=airline_code,
            cabin=cabin,
            departure_date=departure_date,
            booking_window_days=booking_window_days,
            polling_bucket_hour=polling_bucket_hour,
        )

        return {
            "watch_id": watch_id,
            "route_id": route_id,
            "origin": origin,
            "destination": destination,
            "airline_code": airline_code,
            "cabin": cabin,
            "booking_window_days": booking_window_days,
            "departure_date": departure_date,
            "return_date": return_date,
            "native_currency": native_currency,
            "native_price": native_price,
            "taxes_fees": taxes_fees,
            "display_currency": display_currency,
            "display_price": display_price,
            "fx_rate_used": fx_rate_used,
            "source": PROVIDER_AMADEUS,
            "deeplink": None,
            "request_hash": request_hash,
            "polling_bucket_hour": polling_bucket_hour,
            "observed_at": observed_at_utc,
            "raw_response": selected_payload,
        }
    except KeyError as exc:
        logger.warning("Could not parse Amadeus offer; missing key: %s", exc)
        return None
    except ValueError as exc:
        logger.warning("Could not parse Amadeus offer; invalid value: %s", exc)
        return None
    except InvalidOperation as exc:
        logger.warning("Could not parse Amadeus offer; invalid decimal: %s", exc)
        return None


def select_offer_payload(
    offers: list[dict[str, Any]],
    watch_row: Any,
) -> dict[str, Any] | None:
    """Select the best offer for one watchlist row from Amadeus search results."""
    watch_airline = str(_watch_value(watch_row, "airline_code")).upper()
    matching_offers = [
        offer
        for offer in offers
        if _first_validating_airline(offer) == watch_airline
    ]
    if not matching_offers:
        logger.warning(
            "No Amadeus offers matched watchlist airline_code=%s.",
            watch_airline,
        )
        return None

    direct_matches = [offer for offer in matching_offers if _is_non_stop(offer)]
    if direct_matches:
        return min(direct_matches, key=_offer_price)

    one_stop_matches = [offer for offer in matching_offers if _total_stops(offer) == 1]
    if one_stop_matches:
        return min(one_stop_matches, key=_offer_price)

    return min(matching_offers, key=_offer_price)


def _select_payload(payload: dict[str, Any], watch_row: Any) -> dict[str, Any] | None:
    if isinstance(payload, list):
        return select_offer_payload(payload, watch_row)
    data = payload.get("data")
    if isinstance(data, list):
        return select_offer_payload(data, watch_row)
    return payload


def _first_validating_airline(offer: dict[str, Any]) -> str | None:
    codes = offer.get("validatingAirlineCodes") or []
    if not codes:
        return None
    return str(codes[0]).upper()


def _carrier_code(offer: dict[str, Any]) -> str:
    validating_code = _first_validating_airline(offer)
    if validating_code:
        return validating_code
    return str(offer["itineraries"][0]["segments"][0]["carrierCode"]).upper()


def _is_non_stop(offer: dict[str, Any]) -> bool:
    return all(
        int(segment.get("numberOfStops", 0)) == 0
        for itinerary in offer["itineraries"]
        for segment in itinerary["segments"]
    )


def _total_stops(offer: dict[str, Any]) -> int:
    return sum(
        int(segment.get("numberOfStops", 0))
        for itinerary in offer["itineraries"]
        for segment in itinerary["segments"]
    )


def _offer_price(offer: dict[str, Any]) -> Decimal:
    return Decimal(str(offer["price"]["grandTotal"]))


def _departure_date(offer: dict[str, Any]) -> date:
    raw_departure = str(offer["itineraries"][0]["segments"][0]["departure"]["at"])
    return datetime.fromisoformat(raw_departure).date()


def _return_date(offer: dict[str, Any]) -> date | None:
    itineraries = offer["itineraries"]
    if len(itineraries) < 2:
        return None
    raw_departure = str(itineraries[1]["segments"][0]["departure"]["at"])
    return datetime.fromisoformat(raw_departure).date()


def _taxes_fees(offer: dict[str, Any]) -> Decimal | None:
    base = offer.get("price", {}).get("base")
    grand_total = offer.get("price", {}).get("grandTotal")
    if base is None or grand_total is None:
        return None
    return Decimal(str(grand_total)) - Decimal(str(base))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bucket_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _display_currency() -> str:
    return os.getenv("DISPLAY_CURRENCY", "USD").upper()


def _watch_value(watch_row: Any, key: str, default: Any = None) -> Any:
    if isinstance(watch_row, Mapping):
        value = watch_row.get(key, default)
    elif hasattr(watch_row, "_mapping"):
        value = watch_row._mapping.get(key, default)
    else:
        value = getattr(watch_row, key, default)
    if value is None:
        raise ValueError(f"watch_row.{key} is required")
    return value


def _route_origin(route_id: str) -> str:
    parts = route_id.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"route_id must use ORIGIN-DESTINATION format: {route_id}")
    return parts[0]


def _route_destination(route_id: str) -> str:
    parts = route_id.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"route_id must use ORIGIN-DESTINATION format: {route_id}")
    return parts[1]
