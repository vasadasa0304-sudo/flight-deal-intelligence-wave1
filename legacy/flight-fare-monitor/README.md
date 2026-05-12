# Flight Fare Monitor

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Streamlit-ff4b4b?logo=streamlit)](https://vasadasa0304-sudo-flight-fare--appdashboardstreamlit-app-rnegd4.streamlit.app)
[![GitHub](https://img.shields.io/badge/Source-GitHub-181717?logo=github)](https://github.com/vasadasa0304-sudo/flight-fare-monitor)

A Python data pipeline that fetches live flight fares from the Amadeus API, stores price snapshots in PostgreSQL, and surfaces trends through a Streamlit dashboard — with a configurable alert system that fires when fares drop below defined thresholds.

Built as a portfolio project demonstrating end-to-end data engineering: API integration, relational data modelling, analytics queries, a live dashboard, and a pluggable notification system.

---

## Business Problem

Flight prices change constantly and unpredictably. Travellers and travel businesses lack a simple, automated way to track fare movements over time for specific routes and dates. Manual price checking is slow, inconsistent, and produces no historical record for trend analysis.

---

## Solution

An automated pipeline that:

1. Fetches live fare offers from the Amadeus Self-Service API on demand
2. Stores every snapshot in a structured PostgreSQL database
3. Tracks price trends across multiple pipeline runs
4. Surfaces insights through a Streamlit dashboard
5. Fires configurable price alerts when fares drop below a threshold

Routes and search parameters are driven entirely by `config/routes.yaml` — no code changes required to add or remove a route.

---

## Architecture

```
config/routes.yaml
       │
       ▼
fetch_offers.py ──► data/raw/*.json  (raw JSON preserved)
       │
       ▼
normalize_offers.py
       │
       ▼
run_pipeline.py ──► PostgreSQL
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    analytics/     alerts/     dashboard/
    metrics.py    alerts.py  streamlit_app.py
```

**Pipeline stages:**

| Stage | Module | Responsibility |
|---|---|---|
| Fetch | `app/pipeline/fetch_offers.py` | Authenticate, call Amadeus API, save raw JSON |
| Normalize | `app/pipeline/normalize_offers.py` | Parse raw offers into structured rows |
| Store | `app/pipeline/run_pipeline.py` | Upsert routes/configs, insert fare snapshots, write audit log |
| Analyse | `app/analytics/metrics.py` | Pandas queries over PostgreSQL for dashboard and alerts |
| Alert | `app/alerts/alerts.py` | Compare cheapest fare per route against thresholds; notify |
| Dashboard | `app/dashboard/streamlit_app.py` | Streamlit UI: overview, fare table, route analysis, price trend |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12 |
| API | Amadeus Self-Service (free tier) |
| HTTP | requests |
| ORM | SQLAlchemy 2 |
| DB driver | psycopg2-binary |
| Data | pandas |
| Dashboard | Streamlit |
| Database | PostgreSQL 16 (Docker) |
| Config | PyYAML |
| Env | python-dotenv |

---

## Folder Structure

```
flight-fare-monitor/
├── app/
│   ├── api/
│   │   └── amadeus_client.py       # OAuth2 token + flight search
│   ├── pipeline/
│   │   ├── fetch_offers.py         # Fetch from API, save raw JSON
│   │   ├── normalize_offers.py     # Parse offers into flat dicts
│   │   └── run_pipeline.py         # Orchestrator: fetch → normalise → store
│   ├── db/
│   │   ├── base.py                 # SQLAlchemy declarative base
│   │   ├── connection.py           # Engine + SessionLocal
│   │   └── models.py               # Route, SearchConfig, FareSnapshot, PipelineRun
│   ├── analytics/
│   │   ├── metrics.py              # get_latest_fares, get_cheapest_by_route, get_price_trend
│   │   └── queries.sql             # Reference SQL
│   ├── alerts/
│   │   └── alerts.py               # Threshold checker, ConsoleNotifier, TelegramNotifier
│   └── dashboard/
│       └── streamlit_app.py        # Streamlit UI
├── config/
│   └── routes.yaml                 # Routes, departure dates, search parameters
├── data/
│   └── raw/                        # Raw JSON responses (one file per run/route/date)
├── sql/
│   ├── schema.sql                  # Table definitions
│   └── indexes.sql                 # Performance indexes
├── tests/
├── .env.example
└── requirements.txt
```

---

## Setup

### 1. Clone and create virtual environment

```bash
git clone https://github.com/yourname/flight-fare-monitor.git
cd flight-fare-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
AMADEUS_API_KEY=your_key_here
AMADEUS_API_SECRET=your_secret_here
DATABASE_URL=postgresql://fareuser:farepass@localhost:5432/flight_fare_monitor
TELEGRAM_BOT_TOKEN=your_bot_token_here   # optional
TELEGRAM_CHAT_ID=your_chat_id_here       # optional
```

Amadeus credentials are available for free at [developers.amadeus.com](https://developers.amadeus.com).

### 3. Start PostgreSQL

```bash
docker run --name fare-monitor-db \
  -e POSTGRES_USER=fareuser \
  -e POSTGRES_PASSWORD=farepass \
  -e POSTGRES_DB=flight_fare_monitor \
  -p 5432:5432 \
  -d postgres:16
```

### 4. Create tables and indexes

```bash
docker exec -i fare-monitor-db psql -U fareuser -d flight_fare_monitor < sql/schema.sql
docker exec -i fare-monitor-db psql -U fareuser -d flight_fare_monitor < sql/indexes.sql
```

### 5. Configure routes

Edit `config/routes.yaml` to set the routes and dates you want to monitor:

```yaml
routes:
  - origin: LHR
    destination: JFK
    label: "London to New York"
  - origin: LHR
    destination: DXB
    label: "London to Dubai"

departure_dates:
  - "2026-06-01"
  - "2026-06-15"

adults: 1
cabin: ECONOMY
currency: GBP
non_stop: false
max_offers: 5
```

---

## Running the Pipeline

```bash
PYTHONPATH=$(pwd) python -m app.pipeline.run_pipeline
```

The pipeline fetches fares for every `route × departure_date` combination defined in `config/routes.yaml`, normalises the results, and stores them in PostgreSQL with a full audit log entry in `pipeline_runs`.

---

## Running the Dashboard

```bash
PYTHONPATH=$(pwd) streamlit run app/dashboard/streamlit_app.py
```

Open [http://localhost:8501](http://localhost:8501).

The dashboard provides three sections:

- **Overview** — total routes tracked, total snapshots, best current fare
- **Latest Fares** — full fare table from the most recent pipeline run
- **Route Analysis** — per-route fare breakdown and price trend chart (requires 2+ pipeline runs to build a trend)

---

## Running Alerts

```bash
PYTHONPATH=$(pwd) python -m app.alerts.alerts
```

Alerts compare the cheapest stored fare per route against thresholds defined in `app/alerts/alerts.py`:

```python
THRESHOLDS = {
    "LHR-JFK": 500.00,
    "LHR-DXB": 300.00,
    "LHR-MAD": 150.00,
}
```

When a fare is below threshold, a `ConsoleNotifier` prints a formatted alert. If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`, a `TelegramNotifier` also sends a message to your Telegram chat.

---

## Example Use Case

A travel consultant wants to monitor economy fares from London Heathrow to New York JFK for a client travelling in June 2026.

1. Add `LHR → JFK` and the target departure date to `config/routes.yaml`
2. Run the pipeline once or twice daily to build a price history
3. Open the dashboard to view the current cheapest fare and how prices are moving
4. Set a threshold of £500 in `alerts.py` and run the alerts check — get notified by console or Telegram the moment fares drop below it

---

## Key Features

- **Live fare data** via Amadeus Self-Service API free tier
- **YAML-driven configuration** — add routes and dates without touching code
- **Relational schema** separating routes, search configs, fare snapshots, and pipeline runs
- **Full pipeline audit log** — every run recorded with status, row count, and error message
- **Raw JSON preserved** in `data/raw/` for reprocessing or debugging
- **Modular pipeline** — each stage (`fetch`, `normalize`, `store`) is independently runnable
- **Pluggable alert system** — `ConsoleNotifier` and `TelegramNotifier` share a common interface; new channels require only a new class
- **Streamlit dashboard** with overview metrics, fare table, route selector, and price trend chart

---

## Next Improvements

- Scheduled runs via cron or Airflow
- Email notifications (extend `BaseNotifier`)
- User-configurable alert thresholds via dashboard UI
- Hosted database (Supabase or Railway) for a live, shareable portfolio demo
- Multi-currency support in the dashboard

---

## Portfolio Screenshots

Suggested screenshots to capture for GitHub and Upwork:

1. **Dashboard — Overview section**: metrics cards showing routes tracked, total snapshots, and best fare across all routes
2. **Dashboard — Price Trend chart**: line chart showing `min_price` and `avg_price` over multiple pipeline runs for one route (requires several runs to populate)
3. **Dashboard — Latest Fares table**: full fare table with carrier, stops, duration, and price columns visible
4. **Terminal — Pipeline run output**: clean terminal output showing all routes and dates being fetched, rows normalised, and snapshots stored (`Stored: N snapshots · Pipeline run ID: N · Done.`)
