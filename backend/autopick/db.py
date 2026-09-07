from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


GLOBAL_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS checklist_catalog (
    label TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS preference_profiles (
    name TEXT PRIMARY KEY,
    weights_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS checklist_aliases (
    checklist_type_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    alias TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'search',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(checklist_type_id, item_key, alias)
);
CREATE TABLE IF NOT EXISTS template_blueprints (
    fingerprint TEXT PRIMARY KEY,
    template_name TEXT NOT NULL,
    slots_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

PROJECT_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY,
    factory_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    template_relative_path TEXT NOT NULL,
    checklist_relative_path TEXT,
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL,
    preprocess_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    source_filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    dhash TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    byte_size INTEGER NOT NULL,
    blur_score REAL NOT NULL,
    dark_ratio REAL NOT NULL,
    bright_ratio REAL NOT NULL,
    quality_score REAL NOT NULL,
    quality_flags_json TEXT NOT NULL,
    duplicate_of TEXT,
    near_duplicate_group TEXT,
    embedding_relative_path TEXT,
    indexed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(duplicate_of) REFERENCES photos(id)
);
CREATE INDEX IF NOT EXISTS idx_photos_sha ON photos(sha256);
CREATE TABLE IF NOT EXISTS embeddings (
    photo_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    preprocess_version TEXT NOT NULL,
    vector BLOB NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS checklist_slots (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    section TEXT,
    ordinal INTEGER NOT NULL,
    bookmark TEXT,
    item_key TEXT,
    checklist_type_id TEXT NOT NULL DEFAULT 'quality_v1',
    sheet_name TEXT,
    label_cell TEXT,
    image_cell TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    slot_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    semantic_score REAL NOT NULL,
    quality_score REAL NOT NULL,
    total_score REAL NOT NULL,
    rank INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(slot_id, photo_id),
    FOREIGN KEY(slot_id) REFERENCES checklist_slots(id) ON DELETE CASCADE,
    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS confirmations (
    slot_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'system',
    search_query TEXT,
    system_photo_id TEXT,
    PRIMARY KEY(slot_id, photo_id),
    FOREIGN KEY(slot_id) REFERENCES checklist_slots(id) ON DELETE CASCADE,
    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rejections (
    slot_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    reason TEXT,
    rejected_at TEXT NOT NULL,
    PRIMARY KEY(slot_id, photo_id)
);
CREATE TABLE IF NOT EXISTS search_cache (
    query TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ocr_results (
    photo_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    current INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    estimated_tokens INTEGER NOT NULL DEFAULT 0,
    actual_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    photo_id TEXT,
    operation TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_manifest (
    report_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bookmark TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    PRIMARY KEY(report_id, slot_id, photo_id)
);
CREATE TABLE IF NOT EXISTS report_slots (
    id TEXT PRIMARY KEY,
    template_fingerprint TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    table_index INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    cell_index INTEGER NOT NULL,
    image_kind TEXT NOT NULL,
    media_name TEXT,
    caption TEXT NOT NULL,
    section TEXT,
    width_emu INTEGER,
    height_emu INTEGER,
    checklist_slot_id TEXT,
    mapping_confidence REAL NOT NULL DEFAULT 0,
    mandatory INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(template_fingerprint, slot_key),
    FOREIGN KEY(checklist_slot_id) REFERENCES checklist_slots(id)
);
CREATE TABLE IF NOT EXISTS report_slot_candidates (
    report_slot_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    semantic_score REAL NOT NULL,
    ocr_score REAL NOT NULL DEFAULT 0,
    quality_score REAL NOT NULL,
    aspect_score REAL NOT NULL DEFAULT 0,
    total_score REAL NOT NULL,
    rank INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(report_slot_id, photo_id),
    FOREIGN KEY(report_slot_id) REFERENCES report_slots(id) ON DELETE CASCADE,
    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS report_slot_selections (
    report_slot_id TEXT PRIMARY KEY,
    photo_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    selected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    FOREIGN KEY(report_slot_id) REFERENCES report_slots(id) ON DELETE CASCADE,
    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS report_runs (
    id TEXT PRIMARY KEY,
    template_fingerprint TEXT NOT NULL,
    output_relative_path TEXT,
    qa_pdf_relative_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_slot_manifest (
    report_id TEXT NOT NULL,
    report_slot_id TEXT NOT NULL,
    checklist_slot_id TEXT,
    photo_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    caption TEXT NOT NULL,
    confidence REAL NOT NULL,
    selected_at TEXT NOT NULL,
    PRIMARY KEY(report_id, report_slot_id),
    FOREIGN KEY(report_slot_id) REFERENCES report_slots(id) ON DELETE CASCADE,
    FOREIGN KEY(photo_id) REFERENCES photos(id)
);
CREATE TABLE IF NOT EXISTS history_matches (
    id TEXT PRIMARY KEY,
    report_relative_path TEXT NOT NULL,
    media_name TEXT NOT NULL,
    photo_id TEXT,
    matched_slot_id TEXT,
    context_text TEXT,
    hash_distance INTEGER,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(photo_id) REFERENCES photos(id),
    FOREIGN KEY(matched_slot_id) REFERENCES checklist_slots(id)
);
CREATE TABLE IF NOT EXISTS preference_feedback (
    id TEXT PRIMARY KEY,
    checklist_type_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    selected_photo_id TEXT NOT NULL,
    system_photo_id TEXT NOT NULL,
    export_id TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(slot_id, export_id)
);
CREATE TABLE IF NOT EXISTS pending_aliases (
    id TEXT PRIMARY KEY,
    checklist_type_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    alias TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE TABLE IF NOT EXISTS export_batches (
    id TEXT PRIMARY KEY,
    output_relative_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_batch_items (
    export_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    selected_photo_id TEXT NOT NULL,
    system_photo_id TEXT,
    semantic_score REAL,
    quality_score REAL,
    total_score REAL,
    rank INTEGER,
    PRIMARY KEY(export_id, slot_id)
);
CREATE TABLE IF NOT EXISTS feedback_imports (
    id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL UNIQUE,
    source_filename TEXT NOT NULL,
    export_id TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback_events (
    id TEXT PRIMARY KEY,
    import_id TEXT,
    export_id TEXT,
    slot_id TEXT NOT NULL,
    system_photo_id TEXT,
    selected_photo_id TEXT,
    outcome TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(import_id, slot_id),
    UNIQUE(export_id, slot_id, source)
);
"""


@contextmanager
def connect(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_global(path: Path) -> None:
    with connect(path) as connection:
        connection.executescript(GLOBAL_SCHEMA)
        # Keep the original profile table compatible while making the type
        # identifier the stable key for the fixed checklist registry.
        default_weights = '{"semantic":0.62,"quality":0.10,"ocr":0.28}'
        connection.execute(
            "INSERT OR IGNORE INTO preference_profiles(name, weights_json, version) VALUES ('quality_v1', ?, 1)",
            (default_weights,),
        )
        # Feedback is now accumulated for a later validated training run. The
        # old fixed-step adjustment was not learned from the actual feedback,
        # so reset every existing quality_v1 profile to the stable baseline.
        connection.execute(
            "UPDATE preference_profiles SET weights_json=?, version=1, updated_at=CURRENT_TIMESTAMP WHERE name='quality_v1'",
            (default_weights,),
        )


def initialize_project(path: Path) -> None:
    with connect(path) as connection:
        connection.executescript(PROJECT_SCHEMA)
        def add_column(table: str, column: str, declaration: str) -> None:
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

        add_column("project", "checklist_type_id", "TEXT NOT NULL DEFAULT 'quality_v1'")
        add_column("project", "schema_version", "INTEGER NOT NULL DEFAULT 2")
        add_column("checklist_slots", "item_key", "TEXT")
        add_column("checklist_slots", "checklist_type_id", "TEXT NOT NULL DEFAULT 'quality_v1'")
        add_column("checklist_slots", "sheet_name", "TEXT")
        add_column("checklist_slots", "label_cell", "TEXT")
        add_column("checklist_slots", "image_cell", "TEXT")
        add_column("confirmations", "source", "TEXT NOT NULL DEFAULT 'system'")
        add_column("confirmations", "search_query", "TEXT")
        add_column("confirmations", "system_photo_id", "TEXT")
