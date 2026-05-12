import json
import re
from datetime import datetime, UTC
from pathlib import Path

RAW_DATA_DIR = Path("data/raw")


def _parse_duration(iso_duration: str) -> int:
    if not iso_duration:
        return 0
    hours = int(re.search(r"(\d+)H", iso_duration).group(1)) if "H" in iso_duration else 0
    minutes = int(re.search(r"(\d+)M", iso_duration).group(1)) if "M" in iso_duration else 0
    return hours * 60 + minutes


def normalize_offer(offer: dict, collected_at: datetime) -> dict:
    try:
        itinerary = offer["itineraries"][0]
        segments = itinerary["segments"]
        first_segment = segments[0]
        last_segment = segments[-1]
        return {
            "origin_iata":             first_segment["departure"]["iataCode"],
            "destination_iata":        last_segment["arrival"]["iataCode"],
            "departure_time":          first_segment["departure"]["at"],
            "arrival_time":            last_segment["arrival"]["at"],
            "carrier_code":            first_segment["carrierCode"],
            "validating_airline_code": (offer.get("validatingAirlineCodes") or [None])[0],
            "stops":                   len(segments) - 1,
            "duration_minutes":        _parse_duration(itinerary.get("duration", "")),
            "price_total":             float(offer["price"]["grandTotal"]),
            "currency":                offer["price"]["currency"],
            "collected_at":            collected_at.isoformat(),
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def normalize_all(offers: list[dict], collected_at: datetime = None) -> list[dict]:
    if collected_at is None:
        collected_at = datetime.now(UTC)
    rows = [normalize_offer(o, collected_at) for o in offers]
    return [r for r in rows if r is not None]


def _load_latest_raw_file() -> list[dict]:
    files = sorted(RAW_DATA_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No JSON files found in {RAW_DATA_DIR}/")
    latest = files[-1]
    print(f"Loading: {latest}")
    with open(latest) as f:
        return json.load(f)


if __name__ == "__main__":
    try:
        raw_offers = _load_latest_raw_file()
        rows = normalize_all(raw_offers)
        if not rows:
            print("No rows produced — check the raw file structure.")
        else:
            print(f"\nNormalized {len(rows)} offers. First 3:\n")
            for row in rows[:3]:
                for key, value in row.items():
                    print(f"  {key:<28} {value}")
                print()
    except Exception as e:
        print(f"Error: {e}")