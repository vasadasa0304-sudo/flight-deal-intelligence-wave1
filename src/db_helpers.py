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
    """Execute SQL migration(s) against a PostgreSQL database.

    Accepts either:
    - A single .sql file: runs that file.
    - A directory: sorts all *.sql files inside and runs them in order.
      This means 001_init.sql always runs before 002_grain_constraints.sql.
    """
    if sql_path.is_dir():
        paths = sorted(sql_path.glob("*.sql"))
    else:
        paths = [sql_path]

    for path in paths:
        sql = path.read_text(encoding="utf-8")
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
    """Split a SQL migration file into individual statements on semicolons.

    Correctly handles all PostgreSQL quoting contexts so that semicolons
    inside string literals, identifiers, comments, or dollar-quoted blocks
    ($$...$$, $tag$...$tag$) are never treated as statement boundaries.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)

    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None  # e.g. '$$' or '$body$'; None = not in dollar quote

    while i < n:
        c = sql[i]

        # ------------------------------------------------------------------ #
        # Inside a line comment — consume until newline.                      #
        # ------------------------------------------------------------------ #
        if in_line_comment:
            current.append(c)
            if c == "\n":
                in_line_comment = False
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Inside a block comment — consume until closing */.                  #
        # ------------------------------------------------------------------ #
        if in_block_comment:
            current.append(c)
            if c == "*" and i + 1 < n and sql[i + 1] == "/":
                current.append(sql[i + 1])
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue

        # ------------------------------------------------------------------ #
        # Inside a dollar-quoted block — consume until the matching tag.      #
        # ------------------------------------------------------------------ #
        if dollar_tag is not None:
            tag_len = len(dollar_tag)
            if sql[i : i + tag_len] == dollar_tag:
                current.extend(dollar_tag)
                i += tag_len
                dollar_tag = None
            else:
                current.append(c)
                i += 1
            continue

        # ------------------------------------------------------------------ #
        # Inside a single-quoted string — consume until closing quote,        #
        # respecting '' escape sequences.                                      #
        # ------------------------------------------------------------------ #
        if in_single_quote:
            current.append(c)
            if c == "'" and i + 1 < n and sql[i + 1] == "'":
                current.append(sql[i + 1])  # escaped quote
                i += 2
            elif c == "'":
                in_single_quote = False
                i += 1
            else:
                i += 1
            continue

        # ------------------------------------------------------------------ #
        # Inside a double-quoted identifier.                                  #
        # ------------------------------------------------------------------ #
        if in_double_quote:
            current.append(c)
            if c == '"':
                in_double_quote = False
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Not inside any special context — detect context openings.           #
        # ------------------------------------------------------------------ #

        # Line comment
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            in_line_comment = True
            current.append(c)
            i += 1
            continue

        # Block comment
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            in_block_comment = True
            current.append(c)
            current.append(sql[i + 1])
            i += 2
            continue

        # Dollar quote: $optionaltag$ where tag is [A-Za-z0-9_]*
        if c == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                tag = sql[i : j + 1]
                dollar_tag = tag
                current.extend(tag)
                i = j + 1
                continue

        # Single quote
        if c == "'":
            in_single_quote = True
            current.append(c)
            i += 1
            continue

        # Double quote
        if c == '"':
            in_double_quote = True
            current.append(c)
            i += 1
            continue

        # Semicolon outside all special contexts = statement boundary
        if c == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements
