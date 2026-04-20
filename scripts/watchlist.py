"""Manage the cEDH commander watchlist.

Examples:
    python scripts/watchlist.py add "Kinnan, Bonder Prodigy"
    python scripts/watchlist.py add "Tivit, Seller of Secrets"
    python scripts/watchlist.py list
    python scripts/watchlist.py remove "Kinnan, Bonder Prodigy"
    python scripts/watchlist.py disable "Kinnan, Bonder Prodigy"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from magic.config import load_config  # noqa: E402
from magic.db.connection import connect, init_schema  # noqa: E402


def _resolve(conn, name: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT oracle_id, name FROM cards WHERE name = ? AND is_commander_eligible=1 LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return row[0], row[1]
    row = conn.execute(
        "SELECT oracle_id, name FROM cards WHERE name = ? COLLATE NOCASE AND is_commander_eligible=1 LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return row[0], row[1]
    # Suggest matches
    matches = conn.execute(
        "SELECT DISTINCT name FROM cards WHERE name LIKE ? AND is_commander_eligible=1 LIMIT 5",
        (f"%{name}%",),
    ).fetchall()
    if matches:
        print(f"No exact commander match for {name!r}. Close matches:")
        for (n,) in matches:
            print(f"  - {n}")
    else:
        print(f"No commander-eligible card found matching {name!r}.")
    return None


def cmd_add(conn, args: argparse.Namespace) -> int:
    resolved = _resolve(conn, args.name)
    if not resolved:
        return 1
    oracle_id, canonical = resolved
    conn.execute(
        """INSERT INTO commander_watchlist (oracle_id, name, notes, active)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(oracle_id) DO UPDATE SET
               name=excluded.name, notes=excluded.notes, active=1""",
        (oracle_id, canonical, args.notes or None),
    )
    conn.commit()
    print(f"Added/activated: {canonical}  ({oracle_id})")
    return 0


def cmd_remove(conn, args: argparse.Namespace) -> int:
    cur = conn.execute(
        "DELETE FROM commander_watchlist WHERE oracle_id IN (SELECT oracle_id FROM cards WHERE name = ? LIMIT 1)",
        (args.name,),
    )
    conn.commit()
    print(f"Removed {cur.rowcount} entries for {args.name!r}")
    return 0


def cmd_disable(conn, args: argparse.Namespace) -> int:
    cur = conn.execute(
        "UPDATE commander_watchlist SET active=0 WHERE name = ?",
        (args.name,),
    )
    conn.commit()
    print(f"Disabled {cur.rowcount} entries for {args.name!r}")
    return 0


def cmd_list(conn, args: argparse.Namespace) -> int:
    rows = conn.execute(
        "SELECT name, active, added_at, notes FROM commander_watchlist ORDER BY active DESC, name"
    ).fetchall()
    if not rows:
        print("(watchlist is empty)")
        return 0
    print(f"{'name':50} {'active':7} {'added_at':20} notes")
    print("-" * 90)
    for r in rows:
        print(f"{r[0]:50} {str(bool(r[1])):7} {r[2]:20} {r[3] or ''}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the cEDH commander watchlist.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add a commander to the watchlist")
    p_add.add_argument("name", help="Exact commander name (e.g. 'Kinnan, Bonder Prodigy')")
    p_add.add_argument("--notes", help="Optional notes for this commander")

    p_rm = sub.add_parser("remove", help="Remove a commander from the watchlist")
    p_rm.add_argument("name")

    p_dis = sub.add_parser("disable", help="Mark a commander as inactive (keeps row)")
    p_dis.add_argument("name")

    sub.add_parser("list", help="Show the current watchlist")

    args = parser.parse_args()

    config = load_config()
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        handler = {
            "add": cmd_add,
            "remove": cmd_remove,
            "disable": cmd_disable,
            "list": cmd_list,
        }[args.cmd]
        return handler(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
