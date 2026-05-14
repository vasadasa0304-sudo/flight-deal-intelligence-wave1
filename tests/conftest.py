"""Shared pytest fixtures for PostgreSQL-backed tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from src.db_helpers import run_migrations


@pytest.fixture(scope="session")
def pg_schema_engine() -> Iterator[tuple[Engine, str]]:
    """Create an isolated PostgreSQL schema and run all migrations into it.

    Skips locally when no DB is configured; fails in CI (CI env var = true).
    """
    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        in_ci = os.getenv("CI", "").lower() in ("true", "1")
        msg = (
            "Set TEST_DATABASE_URL to run PostgreSQL schema tests.\n"
            "Local setup: sudo service postgresql start && "
            "export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
        )
        if in_ci:
            pytest.fail(msg)
        else:
            pytest.skip(msg)

    admin_engine = create_engine(
        database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )
    schema_name = f"test_wave1_{uuid.uuid4().hex}"

    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
    except OperationalError as exc:
        admin_engine.dispose()
        in_ci = os.getenv("CI", "").lower() in ("true", "1")
        msg = f"PostgreSQL is not reachable for schema tests: {exc}"
        if in_ci:
            pytest.fail(msg)
        else:
            pytest.skip(msg)
    except SQLAlchemyError:
        admin_engine.dispose()
        raise

    test_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": f"-csearch_path={schema_name},public",
        },
    )
    try:
        run_migrations(test_engine, Path("migrations"))
        yield test_engine, schema_name
    finally:
        test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()
