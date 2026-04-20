# Magic

Local-first tooling for MTG EDH/Commander deck building, meta analysis, and
upgrade suggestions. Designed to plug into Claude Desktop via MCP so Claude
can reason over your card pool, decklists, and the current tournament meta.

## Status

**Phase 1: foundation + Scryfall ingestion.** Card database works end-to-end.
Moxfield import, edhrec/edhtop16 ingestion, and the MCP server arrive in
later phases.

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

# Force a fresh download even if cache is current
python scripts/refresh.py --sources scryfall --force-download
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
- **Phase 2**: Moxfield deck import (your existing decklists)
- **Phase 3**: edhrec + edhtop16 ingestion (commander stats, tournament meta)
- **Phase 4**: MCP server exposing search, stats, and deck tools to Claude Desktop
- **Phase 5**: Upgrade suggestion engine (deck vs. meta scoring)
- **Phase 6** (optional): Local web UI for browsing
