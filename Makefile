.PHONY: install test lint typecheck \
        db-up db-down db-reset migrate \
        seed-wave1 fx-refresh \
        scheduler-once scheduler detect verify export-alerts summary \
        streamlit backup

# Default DATABASE_URL for local dev; override via environment or .env.
DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5432/flight_deals
# Strip the +psycopg driver suffix so psql can accept the URL.
_PSQL_URL    := $(subst +psycopg,,$(DATABASE_URL))

# ── Python tooling ────────────────────────────────────────────────────────────

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	python -m ruff check src/ app/ scripts/ tests/

typecheck:
	python -m mypy src/

# ── Database ──────────────────────────────────────────────────────────────────

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v && docker compose up -d postgres

migrate:
	cat migrations/*.sql | psql "$(_PSQL_URL)"

# ── Data bootstrap ────────────────────────────────────────────────────────────

seed-wave1:
	python scripts/load_seed_data.py

fx-refresh:
	python scripts/refresh_fx.py --backfill 7

# ── Runtime processes ─────────────────────────────────────────────────────────

scheduler-once:
	python scripts/run_scheduler.py --once

scheduler:
	python scripts/run_scheduler.py

detect:
	python scripts/run_detector.py

verify:
	python scripts/run_verifier.py

export-alerts:
	python scripts/export_alerts.py

summary:
	python scripts/run_weekly_summary.py

# ── Dashboard ─────────────────────────────────────────────────────────────────

streamlit:
	python -m streamlit run app/streamlit_app.py

# ── Ops ───────────────────────────────────────────────────────────────────────

backup:
	bash scripts/backup_postgres.sh
