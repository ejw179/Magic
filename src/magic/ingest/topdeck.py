"""topdeck.gg tournament ingestion for cEDH.

Pulls tournaments from POST /v2/tournaments with standings + deckObj embedded,
filters to commanders on the watchlist, and persists tournaments /
tournament_entries / decks / deck_cards.

Docs: https://topdeck.gg/docs/tournaments-v2
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Config
from ..db.connection import transaction

BASE_URL = "https://topdeck.gg/api"
USER_AGENT = "Magic-DeckTool/0.1 (local; ejw179@gmail.com)"
DEFAULT_COLUMNS = ["name", "id", "decklist", "wins", "losses", "draws", "winRate"]


def _client(config: Config) -> httpx.Client:
    return httpx.Client(
        headers={
            "Authorization": config.topdeck_api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=120,
    )


def _unix_to_iso(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _fetch_tournaments(config: Config, *, last_days: int) -> list[dict]:
    payload = {
        "game": "Magic: The Gathering",
        "format": "EDH",
        "last": last_days,
        "participantMin": config.topdeck_min_event_size,
        "columns": DEFAULT_COLUMNS,
    }
    with _client(config) as client:
        resp = client.post(f"{BASE_URL}/v2/tournaments", json=payload)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response shape: {type(data).__name__}")
    return data


def _card_names(obj: Any) -> list[tuple[str, int]]:
    """Extract (name, qty) pairs from a deck category. Tolerant of shapes:
    list of strings, list of {name, count}, or dict {name: count}."""
    out: list[tuple[str, int]] = []
    if obj is None:
        return out
    if isinstance(obj, dict):
        for name, val in obj.items():
            qty = int(val) if isinstance(val, (int, float)) else 1
            out.append((name, qty))
        return out
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, str):
                out.append((item, 1))
            elif isinstance(item, dict):
                name = item.get("name") or item.get("cardName") or item.get("card")
                qty = item.get("count") or item.get("quantity") or 1
                if name:
                    out.append((name, int(qty)))
    return out


def _extract_categories(deck_obj: dict, keys: list[str]) -> list[tuple[str, int]]:
    """Aggregate all cards under any of the named top-level keys (case-insensitive match)."""
    lower = {k.lower(): v for k, v in deck_obj.items()} if isinstance(deck_obj, dict) else {}
    results: list[tuple[str, int]] = []
    for k in keys:
        results.extend(_card_names(lower.get(k.lower())))
    return results


def _resolve_card(conn: sqlite3.Connection, name: str, *, commander_only: bool) -> tuple[str, str] | None:
    """name → (oracle_id, canonical_name) via the local Scryfall cards table."""
    filt = "AND is_commander_eligible=1" if commander_only else ""
    row = conn.execute(
        f"SELECT oracle_id, name FROM cards WHERE name = ? {filt} LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return row[0], row[1]
    if " // " in name:
        front = name.split(" // ")[0]
        row = conn.execute(
            f"SELECT oracle_id, name FROM cards WHERE name LIKE ? {filt} LIMIT 1",
            (f"{front} //%",),
        ).fetchone()
        if row:
            return row[0], row[1]
    row = conn.execute(
        f"SELECT oracle_id, name FROM cards WHERE name = ? COLLATE NOCASE {filt} LIMIT 1",
        (name,),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _get_watchlist(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT oracle_id FROM commander_watchlist WHERE active=1"
        ).fetchall()
    }


def _upsert_tournament(conn: sqlite3.Connection, tourn: dict) -> None:
    conn.execute(
        """
        INSERT INTO tournaments (id, name, date, size, url, raw_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            date=excluded.date,
            size=excluded.size,
            url=excluded.url,
            raw_json=excluded.raw_json
        """,
        (
            tourn["TID"],
            tourn.get("tournamentName") or "",
            _unix_to_iso(tourn.get("startDate")),
            len(tourn.get("standings") or []),
            f"https://topdeck.gg/tournament/{tourn['TID']}",
            json.dumps(tourn, separators=(",", ":")),
        ),
    )


def _upsert_deck(
    conn: sqlite3.Connection,
    *,
    tid: str,
    standing_idx: int,
    standing: dict,
    tournament_name: str,
    primary_oracle: str,
    partner_oracle: str | None,
) -> int:
    external_id = f"{tid}-{standing.get('id') or standing_idx}"
    deck_name = f"{standing.get('name') or 'Unknown'} @ {tournament_name or tid}"
    decklist = standing.get("decklist") if isinstance(standing.get("decklist"), str) else None
    conn.execute(
        """
        INSERT INTO decks (
            source, external_id, name, commander_oracle_id, partner_oracle_id,
            format, owner, url, topdeck_deck_id, raw_json
        )
        VALUES ('topdeck', ?, ?, ?, ?, 'commander', ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            name=excluded.name,
            commander_oracle_id=excluded.commander_oracle_id,
            partner_oracle_id=excluded.partner_oracle_id,
            owner=excluded.owner,
            url=excluded.url,
            topdeck_deck_id=excluded.topdeck_deck_id,
            raw_json=excluded.raw_json,
            updated_at=datetime('now')
        """,
        (
            external_id,
            deck_name,
            primary_oracle,
            partner_oracle,
            standing.get("name"),
            decklist,
            standing.get("id"),
            json.dumps(standing, separators=(",", ":")),
        ),
    )
    deck_id = conn.execute(
        "SELECT id FROM decks WHERE source='topdeck' AND external_id=?",
        (external_id,),
    ).fetchone()[0]
    return deck_id


def _load_deck_cards(
    conn: sqlite3.Connection,
    deck_id: int,
    deck_obj: dict,
    commander_oracles: set[str],
) -> tuple[int, int]:
    """Replace deck_cards for this deck. Returns (matched, unmatched)."""
    conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
    matched = 0
    unmatched = 0

    for name, qty in _extract_categories(deck_obj, ["Commanders"]):
        resolved = _resolve_card(conn, name, commander_only=True)
        if not resolved:
            unmatched += 1
            continue
        oracle_id, canonical = resolved
        conn.execute(
            """INSERT OR IGNORE INTO deck_cards
               (deck_id, oracle_id, card_name, quantity, board, is_commander)
               VALUES (?, ?, ?, ?, 'commander', 1)""",
            (deck_id, oracle_id, canonical, qty),
        )
        commander_oracles.add(oracle_id)
        matched += 1

    mainboard = _extract_categories(deck_obj, ["Mainboard", "Deck", "Main"])
    for name, qty in mainboard:
        resolved = _resolve_card(conn, name, commander_only=False)
        if not resolved:
            unmatched += 1
            continue
        oracle_id, canonical = resolved
        if oracle_id in commander_oracles:
            continue  # already placed as commander
        conn.execute(
            """INSERT OR IGNORE INTO deck_cards
               (deck_id, oracle_id, card_name, quantity, board, is_commander)
               VALUES (?, ?, ?, ?, 'mainboard', 0)""",
            (deck_id, oracle_id, canonical, qty),
        )
        matched += 1

    return matched, unmatched


def _upsert_entry(
    conn: sqlite3.Connection,
    *,
    tid: str,
    standing_num: int,
    standing: dict,
    primary_oracle: str,
    partner_oracle: str | None,
    deck_id: int,
) -> None:
    wins = standing.get("wins")
    losses = standing.get("losses")
    draws = standing.get("draws")
    total = sum(x for x in (wins, losses, draws) if isinstance(x, int))
    win_rate = standing.get("winRate")
    if win_rate is None and isinstance(wins, int) and total > 0:
        win_rate = wins / total

    conn.execute(
        "DELETE FROM tournament_entries WHERE tournament_id=? AND player=?",
        (tid, standing.get("name")),
    )
    conn.execute(
        """INSERT INTO tournament_entries (
               tournament_id, standing, player, commander_oracle_id, partner_oracle_id,
               deck_id, wins, losses, draws, win_rate, decklist_url, raw_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tid,
            standing_num,
            standing.get("name"),
            primary_oracle,
            partner_oracle,
            deck_id,
            wins,
            losses,
            draws,
            win_rate,
            standing.get("decklist") if isinstance(standing.get("decklist"), str) else None,
            json.dumps(standing, separators=(",", ":")),
        ),
    )


def ingest(conn: sqlite3.Connection, config: Config, *, last_days: int | None = None) -> dict:
    """Fetch tournaments from topdeck.gg and persist watchlist-matched entries.

    Returns a stats dict.
    """
    if not config.topdeck_api_key:
        raise RuntimeError("topdeck api_key not set in config/config.toml")

    last = last_days if last_days else config.topdeck_lookback_months * 30
    watchlist = _get_watchlist(conn)
    if not watchlist:
        print("WARNING: watchlist is empty — no entries will be persisted.")
        print('         Add commanders with: python scripts/watchlist.py add "Kinnan, Bonder Prodigy"')

    run_id = conn.execute(
        "INSERT INTO ingestion_runs (source, dataset, status) VALUES ('topdeck', ?, 'running')",
        (f"last_{last}d",),
    ).lastrowid
    conn.commit()

    stats = {
        "tournaments_seen": 0,
        "tournaments_kept": 0,
        "entries_seen": 0,
        "entries_kept": 0,
        "decks_kept": 0,
        "cards_matched": 0,
        "cards_unmatched": 0,
        "skipped_no_commander": 0,
        "skipped_not_watchlist": 0,
        "skipped_unresolvable_commander": 0,
    }

    try:
        print(f"Fetching tournaments: last {last} days, >= {config.topdeck_min_event_size} players")
        tournaments = _fetch_tournaments(config, last_days=last)
        print(f"  got {len(tournaments)} tournaments")

        with transaction(conn):
            for tourn in tournaments:
                stats["tournaments_seen"] += 1
                tid = tourn.get("TID")
                if not tid:
                    continue

                standings = tourn.get("standings") or []
                kept_in_this_tournament = 0
                _upsert_tournament(conn, tourn)

                for idx, standing in enumerate(standings):
                    stats["entries_seen"] += 1
                    standing_num = idx + 1
                    if standing_num > config.topdeck_max_standing:
                        break

                    deck_obj = standing.get("deckObj") or {}
                    commander_names = [n for n, _ in _extract_categories(deck_obj, ["Commanders"])]
                    if not commander_names:
                        stats["skipped_no_commander"] += 1
                        continue

                    resolved: list[tuple[str, str]] = []
                    for cn in commander_names[:2]:
                        r = _resolve_card(conn, cn, commander_only=True)
                        if r:
                            resolved.append(r)
                    if not resolved:
                        stats["skipped_unresolvable_commander"] += 1
                        continue

                    primary_oracle, _ = resolved[0]
                    partner_oracle = resolved[1][0] if len(resolved) > 1 else None

                    if watchlist and primary_oracle not in watchlist:
                        stats["skipped_not_watchlist"] += 1
                        continue

                    deck_id = _upsert_deck(
                        conn,
                        tid=tid,
                        standing_idx=idx,
                        standing=standing,
                        tournament_name=tourn.get("tournamentName") or "",
                        primary_oracle=primary_oracle,
                        partner_oracle=partner_oracle,
                    )
                    stats["decks_kept"] += 1

                    matched, unmatched = _load_deck_cards(
                        conn, deck_id, deck_obj, commander_oracles={primary_oracle} | ({partner_oracle} if partner_oracle else set())
                    )
                    stats["cards_matched"] += matched
                    stats["cards_unmatched"] += unmatched

                    _upsert_entry(
                        conn,
                        tid=tid,
                        standing_num=standing_num,
                        standing=standing,
                        primary_oracle=primary_oracle,
                        partner_oracle=partner_oracle,
                        deck_id=deck_id,
                    )
                    stats["entries_kept"] += 1
                    kept_in_this_tournament += 1

                if kept_in_this_tournament:
                    stats["tournaments_kept"] += 1

            conn.execute(
                """INSERT INTO sync_checkpoints (source, key, last_synced_at, row_count)
                   VALUES ('topdeck', '', datetime('now'), ?)
                   ON CONFLICT(source, key) DO UPDATE SET
                       last_synced_at=excluded.last_synced_at,
                       row_count=excluded.row_count""",
                (stats["entries_kept"],),
            )

        conn.execute(
            "UPDATE ingestion_runs SET finished_at=datetime('now'), row_count=?, status='success' WHERE id=?",
            (stats["entries_kept"], run_id),
        )
        conn.commit()
    except Exception as e:
        conn.execute(
            "UPDATE ingestion_runs SET finished_at=datetime('now'), status='failed', error=? WHERE id=?",
            (str(e), run_id),
        )
        conn.commit()
        raise

    print("topdeck ingest summary:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats
