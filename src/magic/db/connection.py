"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    from .migrate import pre_schema_migrations, apply_migrations
    # Destructive migrations (drop/recreate) run before schema.sql, which is
    # idempotent via CREATE IF NOT EXISTS.
    pre_schema_migrations(conn)
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    # Additive migrations (ALTER ADD COLUMN) run after schema.sql.
    apply_migrations(conn)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
