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

## Source Documents

Employer source documents are stored in `docs/`.
Generated exports should not be committed.
