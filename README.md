# Magic

Local-first tooling for MTG EDH/Commander deck building, meta analysis, and
upgrade suggestions. Designed to plug into Claude Desktop via MCP so Claude
can reason over your card pool, decklists, and the current tournament meta.

## Status

**Phase 1 (done): foundation + Scryfall card DB.**
**Phase 2 (done): topdeck.gg cEDH tournament ingestion + commander watchlist.**

Moxfield import (public + private), edhrec ingestion, and the MCP server
arrive in later phases.

## Setup

Requires Python 3.10+.

```bash
# from the repo root
python -m venv .venv
. .venv/Scripts/activate     # Windows (bash)
# .venv\Scripts\activate    # Windows (cmd)
# source .venv/bin/activate # macOS/Linux

pip install -e .

cp config/config.example.toml config/config.toml
# edit config/config.toml if you want to change defaults
```

## Usage

```bash
# Create/upgrade schema
python scripts/init_db.py

# Pull latest Scryfall bulk data (~500MB download, cached under data/cache/)
python scripts/refresh.py --sources scryfall

# Manage cEDH commander watchlist
python scripts/watchlist.py add "Kinnan, Bonder Prodigy"
python scripts/watchlist.py list
python scripts/watchlist.py remove "Kinnan, Bonder Prodigy"

# Pull tournaments from topdeck.gg (requires api_key in config/config.toml)
python scripts/refresh.py --sources topdeck
python scripts/refresh.py --sources topdeck --topdeck-last-days 14  # shorter window

# Refresh everything
python scripts/refresh.py
```

The SQLite database lives at `data/magic.db` by default. It is gitignored.

## Layout

```
Magic/
├── config/               # config.toml (gitignored) + example
├── data/                 # DB + API caches (gitignored)
├── scripts/              # init_db.py, refresh.py
└── src/magic/
    ├── config.py         # TOML config loader
    ├── db/
    │   ├── schema.sql    # SQLite schema (re-runnable)
    │   └── connection.py
    └── ingest/
        └── scryfall.py   # Scryfall bulk data ingestion
```

## Roadmap

- **Phase 1** (done): Scryfall card DB
- **Phase 2** (done): topdeck.gg cEDH tournament ingestion + commander watchlist
- **Phase 3**: Moxfield ingestion — public browse (casual, by bracket/views) + private decks (yours)
- **Phase 4**: edhrec commander page ingestion (card pool + inclusion rates for casual)
- **Phase 5**: MCP server exposing search, stats, and deck tools to Claude Desktop
- **Phase 6**: Upgrade suggestion engine (deck vs. meta scoring)
- **Phase 7** (optional): Local web UI for browsing
