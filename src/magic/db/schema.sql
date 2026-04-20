-- SQLite schema for Magic DB.
-- Designed to be re-runnable: uses CREATE IF NOT EXISTS throughout.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================================
-- Cards (from Scryfall bulk data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS cards (
    id              TEXT PRIMARY KEY,          -- Scryfall UUID
    oracle_id       TEXT NOT NULL,             -- Oracle (printing-agnostic) ID
    name            TEXT NOT NULL,
    set_code        TEXT NOT NULL,
    set_name        TEXT,
    collector_number TEXT,
    rarity          TEXT,
    lang            TEXT,
    released_at     TEXT,
    layout          TEXT,
    mana_cost       TEXT,
    cmc             REAL,
    type_line       TEXT,
    oracle_text     TEXT,
    power           TEXT,
    toughness       TEXT,
    loyalty         TEXT,
    colors          TEXT,                      -- JSON array
    color_identity  TEXT,                      -- JSON array
    keywords        TEXT,                      -- JSON array
    legalities      TEXT,                      -- JSON object {format: status}
    is_legendary    INTEGER NOT NULL DEFAULT 0,
    is_commander_eligible INTEGER NOT NULL DEFAULT 0,
    price_usd       REAL,
    price_usd_foil  REAL,
    image_uri_normal TEXT,
    scryfall_uri    TEXT,
    edhrec_rank     INTEGER,
    raw_json        TEXT NOT NULL              -- full card as shipped by Scryfall
);

CREATE INDEX IF NOT EXISTS idx_cards_oracle_id ON cards(oracle_id);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_name_nocase ON cards(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_type_line ON cards(type_line);
CREATE INDEX IF NOT EXISTS idx_cards_color_identity ON cards(color_identity);
CREATE INDEX IF NOT EXISTS idx_cards_commander_eligible ON cards(is_commander_eligible);
CREATE INDEX IF NOT EXISTS idx_cards_edhrec_rank ON cards(edhrec_rank);

-- Full-text search on name and oracle_text.
CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name,
    oracle_text,
    type_line,
    content='cards',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS cards_ai AFTER INSERT ON cards BEGIN
    INSERT INTO cards_fts(rowid, name, oracle_text, type_line)
    VALUES (new.rowid, new.name, new.oracle_text, new.type_line);
END;

CREATE TRIGGER IF NOT EXISTS cards_ad AFTER DELETE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, name, oracle_text, type_line)
    VALUES('delete', old.rowid, old.name, old.oracle_text, old.type_line);
END;

CREATE TRIGGER IF NOT EXISTS cards_au AFTER UPDATE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, name, oracle_text, type_line)
    VALUES('delete', old.rowid, old.name, old.oracle_text, old.type_line);
    INSERT INTO cards_fts(rowid, name, oracle_text, type_line)
    VALUES (new.rowid, new.name, new.oracle_text, new.type_line);
END;

-- ============================================================================
-- Decks (imported from Moxfield / Archidekt / manual)
-- ============================================================================

CREATE TABLE IF NOT EXISTS decks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,             -- 'moxfield', 'archidekt', 'topdeck', 'manual'
    external_id     TEXT,                      -- e.g. Moxfield public ID or topdeck player ID
    name            TEXT NOT NULL,
    commander_oracle_id TEXT,                  -- primary commander
    partner_oracle_id TEXT,                    -- optional partner/background
    format          TEXT NOT NULL DEFAULT 'commander',
    owner           TEXT,                      -- username on the source platform
    url             TEXT,
    description     TEXT,
    view_count      INTEGER,                   -- popularity (moxfield public browse)
    bracket         INTEGER,                   -- moxfield bracket 1-5 (casual power level)
    source_updated_at TEXT,                    -- when the deck was last updated on the source platform
    topdeck_deck_id TEXT,                      -- topdeck.gg player/deck identifier
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    raw_json        TEXT,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_decks_commander ON decks(commander_oracle_id);
CREATE INDEX IF NOT EXISTS idx_decks_source ON decks(source);

CREATE TABLE IF NOT EXISTS deck_cards (
    deck_id         INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    oracle_id       TEXT NOT NULL,
    card_name       TEXT NOT NULL,             -- denormalized for convenience
    quantity        INTEGER NOT NULL DEFAULT 1,
    board           TEXT NOT NULL DEFAULT 'mainboard', -- mainboard, sideboard, maybeboard, commander
    is_commander    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (deck_id, oracle_id, board)
);

CREATE INDEX IF NOT EXISTS idx_deck_cards_oracle ON deck_cards(oracle_id);

-- ============================================================================
-- Commander meta stats (from edhrec / edhtop16)
-- ============================================================================

CREATE TABLE IF NOT EXISTS commanders (
    oracle_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    partner_oracle_id TEXT,                    -- for partner/background pairs
    color_identity  TEXT NOT NULL,
    edhrec_url      TEXT,
    edhrec_deck_count INTEGER,
    last_refreshed  TEXT
);

-- Per-commander card inclusion rates (edhrec). One row per (commander, card,
-- category) so a single card can appear in multiple edhrec cardlists
-- (e.g. "topcards" AND "ramp") without collision.
CREATE TABLE IF NOT EXISTS commander_card_stats (
    commander_oracle_id TEXT NOT NULL REFERENCES commanders(oracle_id) ON DELETE CASCADE,
    card_oracle_id  TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '',  -- edhrec tag: topcards, highsynergycards, ramp, carddraw, removal, ...
    inclusion_count INTEGER NOT NULL,          -- num_decks
    potential_decks INTEGER,                   -- sample size
    inclusion_pct   REAL NOT NULL,             -- num_decks / potential_decks (0.0 - 1.0)
    synergy_score   REAL,
    last_refreshed  TEXT NOT NULL,
    PRIMARY KEY (commander_oracle_id, card_oracle_id, category)
);

CREATE INDEX IF NOT EXISTS idx_ccs_card ON commander_card_stats(card_oracle_id);
CREATE INDEX IF NOT EXISTS idx_ccs_inclusion ON commander_card_stats(commander_oracle_id, inclusion_pct);
CREATE INDEX IF NOT EXISTS idx_ccs_category ON commander_card_stats(commander_oracle_id, category);

-- ============================================================================
-- Tournament meta (from edhtop16)
-- ============================================================================

CREATE TABLE IF NOT EXISTS tournaments (
    id              TEXT PRIMARY KEY,          -- edhtop16 tournament id
    name            TEXT NOT NULL,
    date            TEXT,
    size            INTEGER,
    url             TEXT,
    raw_json        TEXT,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tournament_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id   TEXT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    standing        INTEGER,
    player          TEXT,
    commander_oracle_id TEXT,
    partner_oracle_id TEXT,
    deck_id         INTEGER REFERENCES decks(id),
    wins            INTEGER,
    losses          INTEGER,
    draws           INTEGER,
    win_rate        REAL,                      -- wins / (wins + losses + draws)
    decklist_url    TEXT,                      -- raw decklist reference from topdeck (URL or identifier)
    raw_json        TEXT
);

CREATE INDEX IF NOT EXISTS idx_tourn_entries_commander ON tournament_entries(commander_oracle_id);
CREATE INDEX IF NOT EXISTS idx_tourn_entries_tourn ON tournament_entries(tournament_id);
-- idx_tourn_entries_win_rate is created in migrate.py so it works for DBs
-- created before the win_rate column existed.

-- ============================================================================
-- Commander watchlist (which commanders to ingest tournament/meta data for)
-- ============================================================================

CREATE TABLE IF NOT EXISTS commander_watchlist (
    oracle_id       TEXT PRIMARY KEY,          -- FK-ish to cards.oracle_id
    name            TEXT NOT NULL,
    notes           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    added_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================================
-- Sync checkpoints (per-source watermarks for delta ingestion)
-- ============================================================================

CREATE TABLE IF NOT EXISTS sync_checkpoints (
    source          TEXT NOT NULL,             -- 'topdeck', 'moxfield_public', 'edhrec'
    key             TEXT NOT NULL DEFAULT '',  -- optional sub-key (e.g. commander name)
    last_synced_at  TEXT NOT NULL,
    watermark       TEXT,                      -- highest-seen timestamp or cursor; source-specific
    row_count       INTEGER,
    PRIMARY KEY (source, key)
);

-- ============================================================================
-- Ingestion bookkeeping
-- ============================================================================

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,             -- 'scryfall', 'moxfield', 'edhrec', 'edhtop16'
    dataset         TEXT,                      -- e.g. scryfall bulk type
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT,
    row_count       INTEGER,
    status          TEXT NOT NULL DEFAULT 'running',  -- running, success, failed
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_source ON ingestion_runs(source, finished_at);
