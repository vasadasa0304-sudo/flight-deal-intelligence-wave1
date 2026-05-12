import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
from app.analytics.metrics import get_latest_fares, get_cheapest_by_route, get_price_trend
from app.db.connection import engine
from sqlalchemy import text

st.set_page_config(page_title="Flight Fare Monitor", page_icon="✈️", layout="wide")
st.title("✈️ Flight Fare Monitor")


@st.cache_data(ttl=600)
def load_latest_fares():
    return get_latest_fares()


@st.cache_data(ttl=600)
def load_cheapest_by_route():
    return get_cheapest_by_route()


@st.cache_data(ttl=600)
def load_price_trend(origin, destination, departure_date):
    return get_price_trend(origin, destination, departure_date)


@st.cache_data(ttl=600)
def load_counts():
    with engine.connect() as conn:
        routes = conn.execute(text("SELECT COUNT(*) FROM routes")).scalar()
        snapshots = conn.execute(text("SELECT COUNT(*) FROM fare_snapshots")).scalar()
    return routes, snapshots


st.header("Overview")
try:
    total_routes, total_snapshots = load_counts()
    cheapest_df = load_cheapest_by_route()
    col1, col2, col3 = st.columns(3)
    col1.metric("Routes Tracked", total_routes)
    col2.metric("Total Snapshots", total_snapshots)
    if not cheapest_df.empty:
        best = cheapest_df.iloc[0]
        col3.metric(
            label=f"Best Fare {best['origin_iata']} to {best['destination_iata']}",
            value=f"{best['currency']} {best['cheapest_price']:.2f}",
        )
        st.subheader("Cheapest fare by route")
        st.dataframe(
            cheapest_df.rename(columns={
                "origin_iata": "Origin",
                "destination_iata": "Destination",
                "departure_date": "Departure",
                "currency": "Currency",
                "cheapest_price": "Cheapest",
                "last_checked": "Last Checked",
            }),
            use_container_width=True,
            hide_index=True,
        )
except Exception as e:
    st.error(f"Overview error: {e}")

st.divider()

st.header("Latest Fares")
try:
    latest_df = load_latest_fares()
    if latest_df.empty:
        st.info("No fare data yet. Run the pipeline first.")
    else:
        st.dataframe(
            latest_df[[
                "origin_iata", "destination_iata", "departure_date",
                "carrier_code", "stops", "duration_minutes",
                "price_total", "currency", "departure_time", "arrival_time",
            ]].rename(columns={
                "origin_iata": "Origin",
                "destination_iata": "Destination",
                "departure_date": "Departure",
                "carrier_code": "Carrier",
                "stops": "Stops",
                "duration_minutes": "Duration min",
                "price_total": "Price",
                "currency": "Currency",
                "departure_time": "Dep Time",
                "arrival_time": "Arr Time",
            }),
            use_container_width=True,
            hide_index=True,
        )
except Exception as e:
    st.error(f"Latest fares error: {e}")

st.divider()

st.header("Route Analysis")
try:
    latest_df = load_latest_fares()
    if latest_df.empty:
        st.info("No data available yet.")
    else:
        routes = latest_df[["origin_iata", "destination_iata"]].drop_duplicates()
        route_options = {
            f"{r.origin_iata} to {r.destination_iata}": (r.origin_iata, r.destination_iata)
            for r in routes.itertuples()
        }
        col_left, col_right = st.columns([1, 3])
        with col_left:
            selected_label = st.selectbox("Select route", list(route_options.keys()))
            origin, destination = route_options[selected_label]
            dates = sorted(latest_df[
                (latest_df["origin_iata"] == origin) &
                (latest_df["destination_iata"] == destination)
            ]["departure_date"].unique())
            selected_date = st.selectbox("Departure date", [str(d)[:10] for d in dates])
        with col_right:
            filtered = latest_df[
                (latest_df["origin_iata"] == origin) &
                (latest_df["destination_iata"] == destination)
            ][["carrier_code", "stops", "duration_minutes", "price_total", "currency"]]
            st.subheader(f"Fares: {selected_label}")
            st.dataframe(
                filtered.rename(columns={
                    "carrier_code": "Carrier",
                    "stops": "Stops",
                    "duration_minutes": "Duration min",
                    "price_total": "Price",
                    "currency": "Currency",
                }),
                use_container_width=True,
                hide_index=True,
            )
        st.subheader(f"Price trend: {selected_label} on {selected_date}")
        trend_df = load_price_trend(origin, destination, selected_date)
        if len(trend_df) < 2:
            st.info("Run the pipeline a few more times to build a trend.")
        else:
            st.line_chart(
                trend_df.set_index("snapshot_time")[["min_price", "avg_price"]],
                use_container_width=True,
            )
except Exception as e:
    st.error(f"Route analysis error: {e}")

st.divider()
st.caption("Amadeus Self-Service API · Refresh to reload data")
