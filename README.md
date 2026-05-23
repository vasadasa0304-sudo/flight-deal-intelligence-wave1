# Flight Deal Intelligence - Wave1

Phase 1 internal operations app for Wave1 fare monitoring.

Wave1 is the mandatory first production scope. The build must stay limited to Middle East + Turkey until a later approved scope document expands it.

## Locked Scope

Authoritative build scope:

- [docs/BUILD_SCOPE_WAVE1.md](docs/BUILD_SCOPE_WAVE1.md)

Wave1 only:

- Geography: Middle East + Turkey.
- Hubs: `IST`, `SAW`, `DXB`, `AUH`, `RUH`, `JED`, `DOH`, `CAI`.
- Airlines: `TK`, `PC`, `EK`, `FZ`, `QR`, `EY`, `SV`, `XY`, `MS`, `G9`.
- Route target: 60-80 active monitored routes.
- Route source: selected only from `docs/Wave1_Airlines_Routes_v1.docx`.
- Booking windows: 14 days and 60 days.
- MVP cabins: `ECONOMY` and `BUSINESS`.
- Schema cabin vocabulary: `ECONOMY`, `PREMIUM_ECONOMY`, `BUSINESS`, `FIRST`.
- Active Wave1 watchlist rows are limited to `ECONOMY` and `BUSINESS` by row-level rule.
- Core model: append-only fare observations, 30-day rolling median baseline, Deal / Flash Deal / Phantom Fare classification.
- Operations gate: QA verification before alert export.

## Non-Scope

Wave1 does not include:

- public web app;
- mobile app;
- membership platform;
- airline direct scraping;
- OTA scraping;
- affiliate integration;
- social media content creation.

## Branch Strategy

- `main`: stable approved code.
- `staging`: active development and Codex work.

## Install

Use `.env.example` as the non-secret configuration reference. Do not commit real credentials.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run Tests

```bash
python -m pytest
```

## Start Postgres

```bash
docker compose up -d postgres
```

The initial schema is loaded from `migrations/001_init.sql` when the Postgres volume is first created.

## Run Streamlit

```bash
streamlit run app/streamlit_app.py
```

## Development Scripts

```bash
python scripts/load_seed_data.py
python scripts/build_baselines.py
python scripts/run_detector.py
python scripts/run_backtest.py
python scripts/run_scheduler.py
```

These scripts are placeholders for the Wave1 backend skeleton. They do not make external API calls.

## Deployment (Ubuntu 22.04 / 24.04)

### Prerequisites

```bash
# Docker Engine + Compose v2
sudo apt-get update
sudo apt-get install -y ca-certificates curl make postgresql-client
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER   # then log out and back in
```

### First-time bootstrap

```bash
git clone https://github.com/vasadasa0304-sudo/flight-deal-intelligence-wave1.git
cd flight-deal-intelligence-wave1

# 1. Configure environment
cp .env.example .env
# Edit .env: fill in AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET, DUFFEL_API_KEY

# 2. Python environment
python3 -m venv .venv && source .venv/bin/activate
make install

# 3. Start Postgres (migrations are auto-applied by Docker on first run)
make db-up
# Wait ~10 s for the healthcheck, then confirm:
docker compose ps

# 4. Seed reference data and provider budgets
make seed-wave1
python scripts/seed_quota.py

# 5. Pull 7 days of FX rates
make fx-refresh

# 6. Open the operations dashboard
make streamlit
# → http://localhost:8501
```

If you are running against a pre-existing Postgres (not Docker), apply migrations manually:

```bash
make migrate
```

To browse the database via Adminer (optional):

```bash
docker compose --profile tools up -d adminer
# → http://localhost:8080  (System: PostgreSQL, Server: postgres, User: postgres)
```

### Running the full stack with Docker

```bash
docker compose up -d
# app      → http://localhost:8501
# postgres → localhost:5432
docker compose logs -f scheduler   # tail scheduler output
docker compose down                # stop all services
```

### Daily ops

| Task | Command |
|---|---|
| Run anomaly detector | `make detect` |
| Run verifier | `make verify` |
| Export verified alerts | `make export-alerts` |
| Weekly summary | `make summary` |
| One polling pass (test run) | `make scheduler-once` |
| Backup database | `make backup` |
| Reset database (destructive) | `make db-reset` |

Backups are written to `data/exports/backups/` as gzip-compressed SQL dumps, timestamped `flight_deals_YYYYMMDD_HHMMSS.sql.gz`. The last 7 backups are kept automatically.

### Rotating Amadeus credentials

```bash
# 1. Obtain new key/secret from the Amadeus Developer Portal.
# 2. Update .env:
#       AMADEUS_CLIENT_ID=<new-id>
#       AMADEUS_CLIENT_SECRET=<new-secret>
# 3. Restart the affected processes:
#    Local:  Ctrl+C the scheduler, then: make scheduler
#    Docker: docker compose restart scheduler app
# 4. Verify with a dry run (no real API calls):
python scripts/run_scheduler.py --dry-run
```

Old credentials are revoked at the portal — the app picks up the new values from `.env` on restart with no code change required.

### Switching from test to production API

> **Warning:** `AMADEUS_ENV=production` routes all requests to the live Amadeus endpoint.
> Real fare data is returned. Check your provider quota budgets before switching.

```bash
# Confirm production credentials are set in .env, then:
AMADEUS_ENV=production make scheduler-once   # one-off production pass

# To switch permanently, set in .env:
#   AMADEUS_ENV=production
# then restart the scheduler (local or Docker).
```

To revert to the test environment, set `AMADEUS_ENV=test` in `.env` and restart.

## Source Documents

Employer source documents are stored in `docs/`.
Generated exports should not be committed.
