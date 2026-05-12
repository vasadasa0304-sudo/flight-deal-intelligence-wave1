"""Database helpers for migrations, tests, and local resets."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings


def get_engine(settings: Settings) -> Engine:
    """Create a SQLAlchemy engine from application settings."""
    return create_engine(settings.database_url, pool_pre_ping=True)


def run_migrations(engine: Engine, sql_path: Path) -> None:
    """Execute the SQL migration file against a fresh PostgreSQL database."""
    sql = sql_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql)
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional SQLAlchemy session boundary."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _split_sql_statements(sql: str) -> list[str]:
    """Split a plain SQL migration file on statement-ending semicolons."""
    statements: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False

    for char in sql:
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote

        if char == ";" and not in_single_quote and not in_double_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements
