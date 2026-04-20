"""Reconnaissance script: probe Moxfield public search and edhrec JSON.

Prints enough of each response to let us design the ingestion schema.
Run once to confirm endpoints work from this machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

UA = "Mozilla/5.0 (compatible; Magic-DeckTool/0.1; +local research)"


def probe_moxfield() -> None:
    url = "https://api2.moxfield.com/v2/decks/search"
    params = {
        "commanderCardName": "Kinnan, Bonder Prodigy",
        "pageNumber": 1,
        "pageSize": 3,
        "sortType": "views",
        "sortDirection": "Descending",
    }
    print(f"GET {url}")
    print(f"  params: {params}")
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30) as c:
        resp = c.get(url, params=params)
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body preview: {resp.text[:500]}")
        return
    data = resp.json()
    print(f"  top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    decks = data.get("data") if isinstance(data, dict) else None
    if isinstance(decks, list) and decks:
        print(f"  first deck keys: {list(decks[0].keys())[:40]}")
        first = decks[0]
        # Print identifying fields if present
        for k in ["publicId", "publicUrl", "name", "createdByUser", "viewCount", "likeCount",
                  "lastUpdatedAtUtc", "commandersCount", "bracket", "format", "commanders"]:
            if k in first:
                val = first[k]
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)[:200]
                print(f"    {k}: {val}")
    elif isinstance(data, dict):
        print(f"  body preview: {json.dumps(data)[:500]}")


def probe_moxfield_deck_fetch(public_id: str) -> None:
    url = f"https://api2.moxfield.com/v2/decks/all/{public_id}"
    print(f"\nGET {url}")
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30) as c:
        resp = c.get(url)
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body preview: {resp.text[:500]}")
        return
    data = resp.json()
    print(f"  top-level keys: {list(data.keys())[:40]}")
    for k in ["publicId", "name", "viewCount", "likeCount", "commentCount", "bracket",
              "lastUpdatedAtUtc", "createdByUser", "format", "commanders", "mainboard",
              "boards"]:
        if k in data:
            val = data[k]
            if isinstance(val, (dict, list)):
                val = json.dumps(val)[:300] + "..."
            print(f"    {k}: {val}")


def probe_edhrec() -> None:
    url = "https://json.edhrec.com/v2/commanders/kinnan-bonder-prodigy.json"
    print(f"\nGET {url}")
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30) as c:
        resp = c.get(url)
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body preview: {resp.text[:500]}")
        return
    data = resp.json()
    print(f"  top-level keys: {list(data.keys())[:20]}")
    # common edhrec structure
    container = data.get("container") or data
    if isinstance(container, dict):
        print(f"  container keys: {list(container.keys())[:20]}")
        json_dict = container.get("json_dict") or {}
        if json_dict:
            print(f"  json_dict keys: {list(json_dict.keys())[:20]}")
            cardlists = json_dict.get("cardlists") or []
            print(f"  cardlists count: {len(cardlists)}")
            if cardlists:
                first = cardlists[0]
                print(f"  first cardlist keys: {list(first.keys())}")
                print(f"  first cardlist tag: {first.get('tag')}")
                items = first.get("cardviews") or first.get("cards") or []
                print(f"  first cardlist item count: {len(items)}")
                if items:
                    print(f"  first item keys: {list(items[0].keys())[:20]}")
                    print(f"  first item sample: {json.dumps(items[0])[:400]}")


def main() -> int:
    probe_moxfield()
    # Optionally probe one deck fetch if we got a publicId
    probe_moxfield_deck_fetch("iuP243NS8EOSqgDav5__hg")  # example from user's initial message
    probe_edhrec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
