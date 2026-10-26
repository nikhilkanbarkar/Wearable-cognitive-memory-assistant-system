#!/usr/bin/env python3
"""Initialize the recognition database schema and optionally sync the people mirror.

Usage:
    python database_setup.py
    python database_setup.py --resync-people

Safe to run repeatedly: only uses CREATE ... IF NOT EXISTS and INSERT OR IGNORE.
Never deletes or resets existing data. Exits non-zero on failure.
"""

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import (
    DATABASE_PATH,
    METADATA_FILE,
    DB_BUSY_TIMEOUT_MS,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recognition_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL,
    person_id INTEGER,
    person_name TEXT,
    status TEXT NOT NULL CHECK (status IN ('KNOWN','UNKNOWN','NO_FACE','ERROR')),
    similarity_score REAL,
    image_path TEXT,
    embedding_path TEXT,
    review_status TEXT CHECK (
        review_status IN ('PENDING','CONFIRMED','DISMISSED') OR review_status IS NULL
    ),
    error_message TEXT,
    FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp
    ON recognition_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_status
    ON recognition_events(status);
CREATE INDEX IF NOT EXISTS idx_events_person_id
    ON recognition_events(person_id);
CREATE INDEX IF NOT EXISTS idx_events_review_status
    ON recognition_events(review_status) WHERE review_status IS NOT NULL;
"""

REQUIRED_EVENT_COLUMNS = {
    "id", "timestamp", "created_at", "person_id", "person_name",
    "status", "similarity_score", "image_path", "embedding_path",
    "review_status", "error_message",
}
REQUIRED_PEOPLE_COLUMNS = {"id", "name", "created_at"}


def _connect(db_path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=busy_timeout_ms / 1000.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        pass
    return conn


def initialize(
    db_path: Optional[Path] = None,
    busy_timeout_ms: Optional[int] = None,
) -> Path:
    """Create the database directory, schema, and indexes. Idempotent."""
    db_path = Path(db_path) if db_path else Path(DATABASE_PATH)
    busy_timeout_ms = (
        int(busy_timeout_ms) if busy_timeout_ms is not None else int(DB_BUSY_TIMEOUT_MS)
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _connect(db_path, busy_timeout_ms)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

    verify_schema(db_path, busy_timeout_ms)
    return db_path


def verify_schema(db_path: Path, busy_timeout_ms: int) -> None:
    conn = _connect(db_path, busy_timeout_ms)
    try:
        event_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(recognition_events)").fetchall()
        }
        missing = REQUIRED_EVENT_COLUMNS - event_cols
        if missing:
            raise RuntimeError(
                f"recognition_events missing columns: {sorted(missing)}"
            )

        people_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(people)").fetchall()
        }
        missing = REQUIRED_PEOPLE_COLUMNS - people_cols
        if missing:
            raise RuntimeError(f"people missing columns: {sorted(missing)}")
    finally:
        conn.close()


def sync_people(
    db_path: Optional[Path] = None,
    metadata_file: Optional[Path] = None,
    busy_timeout_ms: Optional[int] = None,
) -> int:
    """Mirror the distinct person names from the metadata CSV into people.name.

    Returns the number of rows actually inserted (existing rows are untouched).
    """
    db_path = Path(db_path) if db_path else Path(DATABASE_PATH)
    metadata_file = Path(metadata_file) if metadata_file else Path(METADATA_FILE)
    busy_timeout_ms = (
        int(busy_timeout_ms) if busy_timeout_ms is not None else int(DB_BUSY_TIMEOUT_MS)
    )

    if not metadata_file.is_file():
        raise FileNotFoundError(f"Metadata file not found: {metadata_file}")

    names = set()
    with metadata_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "person" not in reader.fieldnames:
            raise ValueError("metadata CSV must contain a 'person' column.")
        for row in reader:
            name = str(row["person"]).strip()
            if name:
                names.add(name)

    created = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    inserted = 0

    conn = _connect(db_path, busy_timeout_ms)
    try:
        for name in sorted(names):
            cur = conn.execute(
                "INSERT OR IGNORE INTO people (name, created_at) VALUES (?, ?)",
                (name, created),
            )
            if cur.rowcount:
                inserted += 1
        conn.commit()
    finally:
        conn.close()

    return inserted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the recognition database (safe to re-run)."
    )
    parser.add_argument(
        "--resync-people", action="store_true",
        help="Also sync people names from Embeddings/metadata_clean.csv.",
    )
    parser.add_argument("--database", type=Path, default=None,
                        help="Override database path (default from config).")
    parser.add_argument("--metadata", type=Path, default=None,
                        help="Override metadata CSV path (default from config).")
    args = parser.parse_args(argv)

    try:
        db_path = initialize(db_path=args.database)
        print(f"[SETUP] Database initialized: {db_path}")

        if args.resync_people:
            inserted = sync_people(db_path=db_path, metadata_file=args.metadata)
            print(f"[SETUP] Synced people: {inserted} new row(s) inserted.")
    except Exception as exc:
        print(f"[SETUP] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())