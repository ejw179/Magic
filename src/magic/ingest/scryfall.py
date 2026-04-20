"""Scryfall bulk data ingestion.

Downloads the selected bulk dataset (default: default_cards, ~500MB JSON),
streams it with ijson so we don't hold it all in memory, and loads it into
the cards table.

Docs: https://scryfall.com/docs/api/bulk-data
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx
import ijson

from ..config import Config
from ..db.connection import transaction

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
USER_AGENT = "Magic-DeckTool/0.1 (local; ejw179@gmail.com)"
BATCH_SIZE = 2000


def _get_bulk_descriptor(bulk_type: str) -> dict[str, Any]:
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"}) as client:
        resp = client.get(BULK_INDEX_URL, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    for item in payload.get("data", []):
        if item.get("type") == bulk_type:
            return item
    raise ValueError(f"Scryfall bulk type {bulk_type!r} not found. "
                     f"Available: {[i.get('type') for i in payload.get('data', [])]}")


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        with client.stream("GET", url, timeout=300) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            last_log = time.monotonic()
            with tmp.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_log > 2:
                        mb = downloaded / (1 << 20)
                        pct = f"{downloaded / total:.0%}" if total else "?"
                        print(f"  downloaded {mb:,.1f} MB ({pct})")
                        last_log = now
    tmp.replace(dest)


def _is_commander_eligible(card: dict[str, Any]) -> bool:
    """Heuristic for commander eligibility: legendary creature, or card with
    'can be your commander' clause (Planeswalkers, Backgrounds, etc.)."""
    type_line = (card.get("type_line") or "").lower()
    oracle_text = (card.get("oracle_text") or "").lower()
    if "legendary" in type_line and "creature" in type_line:
        return True
    if "can be your commander" in oracle_text:
        return True
    # Double-faced cards: check faces.
    for face in card.get("card_faces", []) or []:
        face_type = (face.get("type_line") or "").lower()
        face_text = (face.get("oracle_text") or "").lower()
        if "legendary" in face_type and "creature" in face_type:
            return True
        if "can be your commander" in face_text:
            return True
    return False


def _row_from_card(card: dict[str, Any]) -> tuple[Any, ...]:
    type_line = card.get("type_line") or ""
    is_legendary = 1 if "legendary" in type_line.lower() else 0

    def _face_field(name: str) -> str | None:
        val = card.get(name)
        if val is not None:
            return val
        for face in card.get("card_faces", []) or []:
            if face.get(name) is not None:
                return face[name]
        return None

    prices = card.get("prices") or {}
    image_uris = card.get("image_uris") or {}
    if not image_uris and card.get("card_faces"):
        image_uris = card["card_faces"][0].get("image_uris") or {}

    return (
        card["id"],
        card["oracle_id"] if card.get("oracle_id") else card["id"],
        card.get("name", ""),
        card.get("set", ""),
        card.get("set_name"),
        card.get("collector_number"),
        card.get("rarity"),
        card.get("lang"),
        card.get("released_at"),
        card.get("layout"),
        _face_field("mana_cost"),
        card.get("cmc"),
        type_line,
        _face_field("oracle_text"),
        _face_field("power"),
        _face_field("toughness"),
        _face_field("loyalty"),
        json.dumps(card.get("colors")) if card.get("colors") is not None else None,
        json.dumps(card.get("color_identity", [])),
        json.dumps(card.get("keywords", [])),
        json.dumps(card.get("legalities", {})),
        is_legendary,
        1 if _is_commander_eligible(card) else 0,
        float(prices["usd"]) if prices.get("usd") else None,
        float(prices["usd_foil"]) if prices.get("usd_foil") else None,
        image_uris.get("normal"),
        card.get("scryfall_uri"),
        card.get("edhrec_rank"),
        json.dumps(card, separators=(",", ":")),
    )


INSERT_SQL = """
INSERT INTO cards (
    id, oracle_id, name, set_code, set_name, collector_number, rarity, lang,
    released_at, layout, mana_cost, cmc, type_line, oracle_text,
    power, toughness, loyalty, colors, color_identity, keywords, legalities,
    is_legendary, is_commander_eligible, price_usd, price_usd_foil,
    image_uri_normal, scryfall_uri, edhrec_rank, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    oracle_id=excluded.oracle_id,
    name=excluded.name,
    set_code=excluded.set_code,
    set_name=excluded.set_name,
    collector_number=excluded.collector_number,
    rarity=excluded.rarity,
    lang=excluded.lang,
    released_at=excluded.released_at,
    layout=excluded.layout,
    mana_cost=excluded.mana_cost,
    cmc=excluded.cmc,
    type_line=excluded.type_line,
    oracle_text=excluded.oracle_text,
    power=excluded.power,
    toughness=excluded.toughness,
    loyalty=excluded.loyalty,
    colors=excluded.colors,
    color_identity=excluded.color_identity,
    keywords=excluded.keywords,
    legalities=excluded.legalities,
    is_legendary=excluded.is_legendary,
    is_commander_eligible=excluded.is_commander_eligible,
    price_usd=excluded.price_usd,
    price_usd_foil=excluded.price_usd_foil,
    image_uri_normal=excluded.image_uri_normal,
    scryfall_uri=excluded.scryfall_uri,
    edhrec_rank=excluded.edhrec_rank,
    raw_json=excluded.raw_json
"""


def _iter_cards(json_path: Path) -> Iterator[dict[str, Any]]:
    # use_float=True makes ijson emit Python floats instead of Decimals,
    # which matters for json.dumps of the raw payload and for SQLite binding.
    with json_path.open("rb") as f:
        yield from ijson.items(f, "item", use_float=True)


def _chunks(iterable: Iterable[Any], size: int) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def ingest(conn: sqlite3.Connection, config: Config, force_download: bool = False) -> int:
    """Download (if needed) and load Scryfall bulk data. Returns rows written."""
    desc = _get_bulk_descriptor(config.scryfall_bulk_type)
    download_url = desc["download_uri"]
    updated_at = desc["updated_at"]
    print(f"Scryfall bulk '{config.scryfall_bulk_type}' updated_at={updated_at}")

    # Cache by updated_at so we can skip re-downloading if unchanged.
    stamp = updated_at.replace(":", "").replace("-", "")[:15]
    json_path = config.cache_dir / f"scryfall-{config.scryfall_bulk_type}-{stamp}.json"

    if not json_path.exists() or force_download:
        print(f"Downloading {download_url} -> {json_path}")
        _download(download_url, json_path)
    else:
        print(f"Using cached {json_path}")

    run_id = conn.execute(
        "INSERT INTO ingestion_runs (source, dataset, status) VALUES (?, ?, 'running')",
        ("scryfall", config.scryfall_bulk_type),
    ).lastrowid
    conn.commit()

    count = 0
    try:
        with transaction(conn):
            for batch in _chunks(_iter_cards(json_path), BATCH_SIZE):
                rows = [_row_from_card(c) for c in batch]
                conn.executemany(INSERT_SQL, rows)
                count += len(rows)
                if count % (BATCH_SIZE * 5) == 0:
                    print(f"  loaded {count:,} cards")
        conn.execute(
            "UPDATE ingestion_runs SET finished_at=datetime('now'), row_count=?, status='success' WHERE id=?",
            (count, run_id),
        )
        conn.commit()
    except Exception as e:
        conn.execute(
            "UPDATE ingestion_runs SET finished_at=datetime('now'), status='failed', error=? WHERE id=?",
            (str(e), run_id),
        )
        conn.commit()
        raise

    print(f"Scryfall load complete: {count:,} rows")
    return count
