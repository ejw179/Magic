"""edhrec commander-page ingestion.

For each active commander on the watchlist, fetch
    https://json.edhrec.com/pages/commanders/<slug>.json
parse the cardlists, and populate `commanders` and `commander_card_stats`.

Each cardlist is tagged with a category (topcards, highsynergycards, ramp,
carddraw, removal, creatures, ...). We store one row per (commander, card,
category) so a card can appear in multiple lists without collision.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from typing import Any

import httpx

from ..config import Config
from ..db.connection import transaction

BASE_URL = "https://json.edhrec.com/pages/commanders"
USER_AGENT = "Magic-DeckTool/0.1 (local; ejw179@gmail.com)"


def commander_slug(name: str) -> str:
    """Convert a commander name into edhrec's URL slug.

    Examples:
        "Kinnan, Bonder Prodigy" -> "kinnan-bonder-prodigy"
        "Tivit, Seller of Secrets" -> "tivit-seller-of-secrets"
        "Ms. Bumbleflower" -> "ms-bumbleflower"
        "Atraxa, Praetors' Voice" -> "atraxa-praetors-voice"
    """
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_name.lower()
    # strip apostrophes and commas entirely (don't leave hyphens in their place)
    stripped = re.sub(r"[',\.]", "", lowered)
    # any remaining non-alphanumeric becomes a separator
    slugged = re.sub(r"[^a-z0-9]+", "-", stripped)
    return slugged.strip("-")


def _fetch_commander_page(client: httpx.Client, slug: str) -> dict | None:
    url = f"{BASE_URL}/{slug}.json"
    try:
        resp = client.get(url, timeout=30)
    except httpx.HTTPError as e:
        print(f"  ERROR fetching {url}: {e}")
        return None
    if resp.status_code == 404:
        print(f"  not found on edhrec: {slug}")
        return None
    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code} for {url}")
        return None
    try:
        return resp.json()
    except ValueError:
        print(f"  non-JSON response for {url}")
        return None


def _resolve_card(conn: sqlite3.Connection, name: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT oracle_id, name FROM cards WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if row:
        return row[0], row[1]
    if " // " in name:
        front = name.split(" // ")[0]
        row = conn.execute(
            "SELECT oracle_id, name FROM cards WHERE name LIKE ? LIMIT 1",
            (f"{front} //%",),
        ).fetchone()
        if row:
            return row[0], row[1]
    row = conn.execute(
        "SELECT oracle_id, name FROM cards WHERE name = ? COLLATE NOCASE LIMIT 1",
        (name,),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _upsert_commander_row(
    conn: sqlite3.Connection,
    *,
    oracle_id: str,
    name: str,
    edhrec_url: str,
    deck_count: int | None,
) -> None:
    color_identity = None
    row = conn.execute(
        "SELECT color_identity FROM cards WHERE oracle_id=? LIMIT 1", (oracle_id,)
    ).fetchone()
    if row:
        color_identity = row[0]
    conn.execute(
        """INSERT INTO commanders (oracle_id, name, color_identity, edhrec_url, edhrec_deck_count, last_refreshed)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(oracle_id) DO UPDATE SET
               name=excluded.name,
               color_identity=COALESCE(excluded.color_identity, commanders.color_identity),
               edhrec_url=excluded.edhrec_url,
               edhrec_deck_count=excluded.edhrec_deck_count,
               last_refreshed=excluded.last_refreshed""",
        (oracle_id, name, color_identity or "[]", edhrec_url, deck_count),
    )


def _ingest_commander(
    conn: sqlite3.Connection,
    client: httpx.Client,
    *,
    oracle_id: str,
    name: str,
) -> dict:
    slug = commander_slug(name)
    url = f"{BASE_URL}/{slug}.json"
    print(f"edhrec: {name}  ->  {url}")

    payload = _fetch_commander_page(client, slug)
    stats = {
        "slug": slug,
        "cardlists": 0,
        "rows_written": 0,
        "cards_unmatched": 0,
    }
    if not payload:
        return stats

    deck_count = payload.get("num_decks_avg")
    _upsert_commander_row(
        conn,
        oracle_id=oracle_id,
        name=name,
        edhrec_url=f"https://edhrec.com/commanders/{slug}",
        deck_count=int(deck_count) if isinstance(deck_count, (int, float)) else None,
    )

    # Clear previous rows so removed cards don't linger.
    conn.execute(
        "DELETE FROM commander_card_stats WHERE commander_oracle_id = ?",
        (oracle_id,),
    )

    container = payload.get("container") or {}
    json_dict = container.get("json_dict") if isinstance(container, dict) else None
    cardlists = (json_dict or {}).get("cardlists") or []

    for cardlist in cardlists:
        tag = cardlist.get("tag") or ""
        items = cardlist.get("cardviews") or cardlist.get("cards") or []
        if not items:
            continue
        stats["cardlists"] += 1

        for item in items:
            card_name = item.get("name")
            if not card_name:
                continue
            resolved = _resolve_card(conn, card_name)
            if not resolved:
                stats["cards_unmatched"] += 1
                continue
            card_oracle_id, _ = resolved

            inclusion = item.get("inclusion")
            potential = item.get("potential_decks") or deck_count
            synergy = item.get("synergy")
            if inclusion is None or not potential:
                continue
            pct = float(inclusion) / float(potential) if potential else 0.0

            conn.execute(
                """INSERT INTO commander_card_stats (
                       commander_oracle_id, card_oracle_id, category,
                       inclusion_count, potential_decks, inclusion_pct,
                       synergy_score, last_refreshed
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(commander_oracle_id, card_oracle_id, category) DO UPDATE SET
                       inclusion_count=excluded.inclusion_count,
                       potential_decks=excluded.potential_decks,
                       inclusion_pct=excluded.inclusion_pct,
                       synergy_score=excluded.synergy_score,
                       last_refreshed=excluded.last_refreshed""",
                (oracle_id, card_oracle_id, tag, int(inclusion), int(potential), pct,
                 float(synergy) if isinstance(synergy, (int, float)) else None),
            )
            stats["rows_written"] += 1

    return stats


def ingest(conn: sqlite3.Connection, config: Config) -> dict:
    """Pull edhrec data for every active commander on the watchlist."""
    watchlist = conn.execute(
        "SELECT oracle_id, name FROM commander_watchlist WHERE active=1 ORDER BY name"
    ).fetchall()
    if not watchlist:
        print("watchlist is empty; nothing to fetch from edhrec.")
        return {"commanders": 0, "cardlists": 0, "rows_written": 0, "cards_unmatched": 0}

    run_id = conn.execute(
        "INSERT INTO ingestion_runs (source, dataset, status) VALUES ('edhrec', 'commanders', 'running')"
    ).lastrowid
    conn.commit()

    totals = {"commanders": 0, "cardlists": 0, "rows_written": 0, "cards_unmatched": 0, "commanders_missed": 0}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"}) as client:
            for i, (oracle_id, name) in enumerate(watchlist):
                with transaction(conn):
                    per = _ingest_commander(conn, client, oracle_id=oracle_id, name=name)
                if per["rows_written"] == 0:
                    totals["commanders_missed"] += 1
                else:
                    totals["commanders"] += 1
                totals["cardlists"] += per["cardlists"]
                totals["rows_written"] += per["rows_written"]
                totals["cards_unmatched"] += per["cards_unmatched"]
                if i + 1 < len(watchlist):
                    time.sleep(config.edhrec_request_delay)

        conn.execute(
            "UPDATE ingestion_runs SET finished_at=datetime('now'), row_count=?, status='success' WHERE id=?",
            (totals["rows_written"], run_id),
        )
        conn.commit()
    except Exception as e:
        conn.execute(
            "UPDATE ingestion_runs SET finished_at=datetime('now'), status='failed', error=? WHERE id=?",
            (str(e), run_id),
        )
        conn.commit()
        raise

    print("edhrec ingest summary:")
    for k, v in totals.items():
        print(f"  {k}: {v}")
    return totals
