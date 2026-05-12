import json
from datetime import datetime, UTC
from pathlib import Path

import yaml

from app.api.amadeus_client import AmadeusClient

RAW_DATA_DIR = Path("data/raw")
CONFIG_PATH = Path("config/routes.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_and_save(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    travel_class: str = "ECONOMY",
    currency_code: str = "GBP",
    non_stop: bool = False,
    max_offers: int = 10,
) -> list[dict]:
    client = AmadeusClient()

    print(f"Searching {origin} -> {destination} on {departure_date}...")

    offers = client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        adults=adults,
        travel_class=travel_class,
        currency_code=currency_code,
        non_stop=non_stop,
        max_offers=max_offers,
    )

    if not offers:
        print("No offers returned. The route or date may have no availability in test mode.")
        return []

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = RAW_DATA_DIR / f"{origin}_{destination}_{departure_date}_{timestamp}.json"
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(filename, "w") as f:
        json.dump(offers, f, indent=2)

    print(f"Offers returned: {len(offers)}")
    print(f"Raw response saved: {filename}")

    return offers


if __name__ == "__main__":
    cfg = load_config()
    route = cfg["routes"][0]
    date = cfg["departure_dates"][0]
    try:
        fetch_and_save(
            origin=route["origin"],
            destination=route["destination"],
            departure_date=date,
            adults=cfg.get("adults", 1),
            travel_class=cfg.get("cabin", "ECONOMY"),
            currency_code=cfg.get("currency", "GBP"),
            non_stop=cfg.get("non_stop", False),
            max_offers=cfg.get("max_offers", 10),
        )
    except Exception as e:
        print(f"Error: {e}")
