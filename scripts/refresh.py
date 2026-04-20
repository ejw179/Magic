"""Refresh data from all available sources.

Phase 1: only Scryfall is wired up. Later phases will add Moxfield, edhrec,
edhtop16.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from magic.config import load_config  # noqa: E402
from magic.db.connection import connect, init_schema  # noqa: E402
from magic.ingest import scryfall, topdeck, edhrec  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh data from all sources.")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["scryfall", "topdeck", "edhrec"],
        choices=["scryfall", "topdeck", "edhrec"],
        help="Which data sources to refresh.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Ignore cached bulk file and re-download.",
    )
    parser.add_argument(
        "--topdeck-last-days",
        type=int,
        default=None,
        help="Override lookback window (days) for topdeck. Default: config.lookback_months * 30.",
    )
    args = parser.parse_args()

    config = load_config()
    conn = connect(config.db_path)
    try:
        init_schema(conn)

        if "scryfall" in args.sources:
            print("=== Scryfall ===")
            scryfall.ingest(conn, config, force_download=args.force_download)

        if "topdeck" in args.sources:
            print("=== topdeck.gg ===")
            topdeck.ingest(conn, config, last_days=args.topdeck_last_days)

        if "edhrec" in args.sources:
            print("=== edhrec ===")
            edhrec.ingest(conn, config)

    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
