"""Idempotent schema migrations for existing databases.

schema.sql handles fresh creation. This module adds columns that were
introduced after an earlier schema version, so re-running init_db.py on a
pre-existing DB brings it up to date without losing data (e.g. the 113k
Scryfall cards already loaded).
"""

from __future__ import annotations

import sqlite3
from typing import Iterable


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _add_columns(conn: sqlite3.Connection, table: str, specs: Iterable[tuple[str, str]]) -> None:
    """specs is an iterable of (column_name, column_type_and_default)."""
    if not _table_exists(conn, table):
        return
    existing = _table_columns(conn, table)
    for name, spec in specs:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")


def _primary_key_cols(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows if r[5]]  # pk column is index 5


def pre_schema_migrations(conn: sqlite3.Connection) -> None:
    """Run BEFORE schema.sql — handles destructive changes like PK restructuring.

    Safe because these changes only fire when the table has an out-of-date shape.
    For commander_card_stats specifically, this runs only if the old
    (commander, card) PK is still in place; after that, schema.sql recreates it
    with the new shape.
    """
    if _table_exists(conn, "commander_card_stats"):
        pk = set(_primary_key_cols(conn, "commander_card_stats"))
        if pk and "category" not in pk:
            # Old schema — drop so schema.sql recreates with new PK.
            # Safe: edhrec ingestion hadn't landed yet, so nothing of value lives here.
            conn.execute("DROP TABLE commander_card_stats")
            conn.commit()


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply all outstanding column additions. Safe to run repeatedly."""
    _add_columns(conn, "decks", [
        ("view_count", "INTEGER"),
        ("bracket", "INTEGER"),
        ("source_updated_at", "TEXT"),
        ("topdeck_deck_id", "TEXT"),
    ])
    _add_columns(conn, "tournament_entries", [
        ("wins", "INTEGER"),
        ("losses", "INTEGER"),
        ("draws", "INTEGER"),
        ("win_rate", "REAL"),
        ("decklist_url", "TEXT"),
    ])
    # Indexes on migrated columns (after columns exist).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tourn_entries_win_rate ON tournament_entries(win_rate)"
    )
    conn.commit()
