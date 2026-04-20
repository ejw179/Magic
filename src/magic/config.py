"""Configuration loading."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.toml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "config.example.toml"


@dataclass(frozen=True)
class Config:
    db_path: Path
    cache_dir: Path
    scryfall_bulk_type: str
    moxfield_auth_token: str
    moxfield_username: str
    edhrec_request_delay: float
    edhtop16_endpoint: str
    topdeck_api_key: str
    topdeck_lookback_months: int
    topdeck_min_event_size: int
    topdeck_max_standing: int
    topdeck_request_delay: float


def load_config() -> Config:
    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    with path.open("rb") as f:
        raw = tomllib.load(f)

    db_path = REPO_ROOT / raw["paths"]["db"]
    cache_dir = REPO_ROOT / raw["paths"]["cache_dir"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        db_path=db_path,
        cache_dir=cache_dir,
        scryfall_bulk_type=raw["scryfall"]["bulk_type"],
        moxfield_auth_token=raw.get("moxfield", {}).get("auth_token", ""),
        moxfield_username=raw.get("moxfield", {}).get("username", ""),
        edhrec_request_delay=float(raw.get("edhrec", {}).get("request_delay", 0.5)),
        edhtop16_endpoint=raw.get("edhtop16", {}).get(
            "endpoint", "https://edhtop16.com/api/graphql"
        ),
        topdeck_api_key=raw.get("topdeck", {}).get("api_key", ""),
        topdeck_lookback_months=int(raw.get("topdeck", {}).get("lookback_months", 3)),
        topdeck_min_event_size=int(raw.get("topdeck", {}).get("min_event_size", 30)),
        topdeck_max_standing=int(raw.get("topdeck", {}).get("max_standing", 16)),
        topdeck_request_delay=float(raw.get("topdeck", {}).get("request_delay", 0.7)),
    )
