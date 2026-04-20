"""Create (or upgrade) the SQLite schema at the configured path."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python scripts/init_db.py` without installing the package.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from magic.config import load_config  # noqa: E402
from magic.db.connection import connect, init_schema  # noqa: E402


def main() -> int:
    config = load_config()
    print(f"Initializing DB at {config.db_path}")
    conn = connect(config.db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()
    print("Schema ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
