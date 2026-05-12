import pandas as pd
from sqlalchemy import text
from app.db.connection import engine


def get_latest_fares() -> pd.DataFrame:
    sql = text("""
        WITH latest_run AS (
            SELECT MAX(collected_at) AS max_collected_at
            FROM fare_snapshots
        )
        SELECT
            r.origin_iata,
            r.destination_iata,
            sc.departure_date,
            fs.carrier_code,
            fs.stops,
            fs.duration_minutes,
            fs.price_total,
            sc.currency,
            fs.departure_time,
            fs.arrival_time,
            fs.collected_at
        FROM fare_snapshots fs
        JOIN search_configs sc ON sc.search_id    = fs.search_id
        JOIN routes         r  ON r.route_id      = sc.route_id
        JOIN latest_run     lr ON fs.collected_at = lr.max_collected_at
        ORDER BY fs.price_total ASC
    """)
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def get_cheapest_by_route() -> pd.DataFrame:
    sql = text("""
        SELECT
            r.origin_iata,
            r.destination_iata,
            sc.departure_date,
            sc.currency,
            MIN(fs.price_total)  AS cheapest_price,
            MAX(fs.collected_at) AS last_checked
        FROM fare_snapshots fs
        JOIN search_configs sc ON sc.search_id = fs.search_id
        JOIN routes         r  ON r.route_id   = sc.route_id
        GROUP BY
            r.origin_iata,
            r.destination_iata,
            sc.departure_date,
            sc.currency
        ORDER BY r.origin_iata, r.destination_iata
    """)
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def get_price_trend(origin: str, destination: str, departure_date: str) -> pd.DataFrame:
    sql = text("""
        SELECT
            DATE_TRUNC('minute', fs.collected_at) AS snapshot_time,
            MIN(fs.price_total)                   AS min_price,
            ROUND(AVG(fs.price_total), 2)         AS avg_price
        FROM fare_snapshots fs
        JOIN search_configs sc ON sc.search_id = fs.search_id
        JOIN routes         r  ON r.route_id   = sc.route_id
        WHERE r.origin_iata      = :origin
          AND r.destination_iata = :destination
          AND sc.departure_date  = :departure_date
        GROUP BY DATE_TRUNC('minute', fs.collected_at)
        ORDER BY snapshot_time ASC
    """)
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={
            "origin": origin,
            "destination": destination,
            "departure_date": departure_date,
        })


if __name__ == "__main__":
    print("--- Latest fares ---")
    df = get_latest_fares()
    print(df[["origin_iata", "destination_iata", "carrier_code",
              "stops", "duration_minutes", "price_total", "currency"]].to_string(index=False))

    print("\n--- Cheapest by route ---")
    df2 = get_cheapest_by_route()
    print(df2.to_string(index=False))