"""Root pytest configuration.

Schema tests (tests/test_schema.py) need a real PostgreSQL connection.
This conftest does NOT use Docker or testcontainers — it simply checks
whether TEST_DATABASE_URL is available and behaves accordingly:

  - Local dev, no DB configured : tests SKIP with a setup hint.
  - CI (CI=true in environment) : tests FAIL so the pipeline catches it.
  - TEST_DATABASE_URL is set    : tests run normally.

To run schema tests locally without Docker, start PostgreSQL natively:

  # Ubuntu / WSL
  sudo apt-get install -y postgresql
  sudo service postgresql start
  sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
  export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres
  .venv/bin/python -m pytest tests/test_schema.py -v

No changes are needed for smoke tests — they never touch this fixture.
"""
