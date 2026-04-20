"""One-shot connectivity test for topdeck.gg.

Hits POST /v2/tournaments with a narrow filter, reports auth status and a
tournament count. Never prints the API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from magic.config import load_config  # noqa: E402

BASE_URL = "https://topdeck.gg/api"
USER_AGENT = "Magic-DeckTool/0.1 (local; ejw179@gmail.com)"


def main() -> int:
    config = load_config()
    if not config.topdeck_api_key:
        print("ERROR: config/config.toml has empty topdeck.api_key")
        return 1

    payload = {
        "game": "Magic: The Gathering",
        "format": "EDH",
        "last": 14,
        "participantMin": config.topdeck_min_event_size,
        "columns": ["name", "wins", "losses", "draws"],
    }

    headers = {
        "Authorization": config.topdeck_api_key,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    print(f"POST {BASE_URL}/v2/tournaments  (EDH, {config.topdeck_min_event_size}+ players, last 14 days)")
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{BASE_URL}/v2/tournaments", headers=headers, json=payload)
    except httpx.HTTPError as e:
        print(f"ERROR: network failure: {e}")
        return 2

    print(f"HTTP {resp.status_code}")
    if resp.status_code == 401 or resp.status_code == 403:
        print("Auth rejected. Double-check the API key in config/config.toml.")
        print(f"Body (first 300 chars): {resp.text[:300]}")
        return 3
    if resp.status_code != 200:
        print(f"Unexpected status. Body (first 500 chars): {resp.text[:500]}")
        return 4

    try:
        data = resp.json()
    except ValueError:
        print(f"Response was not JSON. Body (first 300 chars): {resp.text[:300]}")
        return 5

    if isinstance(data, list):
        print(f"OK: got {len(data)} tournaments in the window")
        for item in data[:3]:
            name = item.get("tournamentName", "?")
            start = item.get("startDate", "?")
            top_cut = item.get("topCut", "?")
            standings = item.get("standings", []) or []
            print(f"  - {name!r:55}  start={start}  topCut={top_cut}  entries={len(standings)}")
    else:
        print(f"Unexpected: response is {type(data).__name__}")
        if isinstance(data, dict):
            print(f"  top-level keys: {list(data.keys())[:10]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
