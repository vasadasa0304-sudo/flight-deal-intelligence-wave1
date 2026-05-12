"""
Pipeline entry point: fetch -> normalize -> store.

Run with:
    python -m app.pipeline.run_pipeline
"""

from datetime import datetime, UTC
from app.pipeline.fetch_offers import fetch_and_save, load_config
from app.pipeline.normalize_offers import normalize_all
from app.db.connection import SessionLocal
from app.db.models import Route, SearchConfig, FareSnapshot, PipelineRun
from app.alerts.alerts import check_alerts


def _finalize_run(pipeline_run: PipelineRun, status: str, rows_inserted: int = 0, error_message: str = None) -> None:
    pipeline_run.status = status
    pipeline_run.finished_at = datetime.now(UTC)
    if rows_inserted:
        pipeline_run.rows_inserted = rows_inserted
    if error_message:
        pipeline_run.error_message = error_message


def get_or_create_route(session, origin: str, destination: str) -> Route:
    route = session.query(Route).filter_by(
        origin_iata=origin, destination_iata=destination
    ).first()
    if not route:
        route = Route(origin_iata=origin, destination_iata=destination)
        session.add(route)
        session.flush()
    return route


def get_or_create_search_config(
    session,
    route: Route,
    departure_date: str,
    adults: int,
    cabin: str,
    currency: str,
    non_stop: bool,
) -> SearchConfig:
    config = session.query(SearchConfig).filter_by(
        route_id=route.route_id,
        departure_date=departure_date,
        adults=adults,
        cabin=cabin,
        currency=currency,
        non_stop=non_stop,
    ).first()
    if not config:
        config = SearchConfig(
            route_id=route.route_id,
            departure_date=departure_date,
            adults=adults,
            cabin=cabin,
            currency=currency,
            non_stop=non_stop,
        )
        session.add(config)
        session.flush()
    return config


def run() -> None:
    cfg = load_config()
    adults = cfg.get("adults", 1)
    cabin = cfg.get("cabin", "ECONOMY")
    currency = cfg.get("currency", "GBP")
    non_stop = cfg.get("non_stop", False)
    max_offers = cfg.get("max_offers", 10)

    started_at = datetime.now(UTC)
    print("=== Flight Fare Monitor Pipeline ===")

    with SessionLocal() as session:
        pipeline_run = PipelineRun(started_at=started_at, status="running")
        session.add(pipeline_run)
        session.flush()

        try:
            total_snapshots = 0

            for route_cfg in cfg["routes"]:
                origin = route_cfg["origin"]
                destination = route_cfg["destination"]

                for departure_date in cfg["departure_dates"]:
                    raw_offers = fetch_and_save(
                        origin=origin,
                        destination=destination,
                        departure_date=departure_date,
                        adults=adults,
                        travel_class=cabin,
                        currency_code=currency,
                        non_stop=non_stop,
                        max_offers=max_offers,
                    )
                    if not raw_offers:
                        continue

                    rows = normalize_all(raw_offers, collected_at=started_at)
                    print(f"Normalized: {len(rows)} rows")

                    route = get_or_create_route(session, origin, destination)
                    search_config = get_or_create_search_config(
                        session, route, departure_date, adults, cabin, currency, non_stop
                    )

                    snapshots = [
                        FareSnapshot(
                            search_id=search_config.search_id,
                            carrier_code=r["carrier_code"],
                            validating_airline_code=r["validating_airline_code"],
                            departure_time=r["departure_time"],
                            arrival_time=r["arrival_time"],
                            stops=r["stops"],
                            duration_minutes=r["duration_minutes"],
                            price_total=r["price_total"],
                            currency=r["currency"],
                            collected_at=started_at,
                        )
                        for r in rows
                    ]
                    session.add_all(snapshots)
                    total_snapshots += len(snapshots)

            if total_snapshots == 0:
                _finalize_run(pipeline_run, "no_data")
                session.commit()
                print("No offers fetched. Exiting.")
                return

            _finalize_run(pipeline_run, "success", rows_inserted=total_snapshots)
            session.commit()

            print(f"Stored: {total_snapshots} snapshots")
            print(f"Pipeline run ID: {pipeline_run.run_id}")

            print("\n=== Checking alerts ===")
            check_alerts()
            print("Done.")

        except Exception as e:
            _finalize_run(pipeline_run, "error", error_message=str(e))
            session.commit()
            print(f"Pipeline failed: {e}")
            raise


if __name__ == "__main__":
    run()
