#!/usr/bin/env python3
"""Persist recognition events to SQLite and store unknown-face crops/embeddings.

This module is imported by face_recognition.py and is called synchronously
inside the recognition workflow. It never raises to the caller; failures are
reported to stderr and methods return None.

Schema, path conventions and file-write ordering are documented in README.md.
"""

import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import (
    DATABASE_PATH,
    UNKNOWN_FACES_DIR,
    UNKNOWN_EMBEDDINGS_DIR,
    DB_BUSY_TIMEOUT_MS,
)


_SCHEMA = """
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ensure_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        print(f"[LOGGER] Cannot create directory {path}: {exc}", file=sys.stderr)
        return False


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


class RecognitionLogger:
    """Synchronous, best-effort logger for recognition events.

    Construct once at startup and reuse. Every public method returns an
    integer event id on success, or None on failure. No method raises.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        unknown_faces_dir: Optional[Path] = None,
        unknown_embeddings_dir: Optional[Path] = None,
        busy_timeout_ms: Optional[int] = None,
        project_root: Optional[Path] = None,
    ):
        self.db_path = Path(db_path) if db_path else Path(DATABASE_PATH)
        self.unknown_faces_dir = (
            Path(unknown_faces_dir) if unknown_faces_dir else Path(UNKNOWN_FACES_DIR)
        )
        self.unknown_embeddings_dir = (
            Path(unknown_embeddings_dir)
            if unknown_embeddings_dir
            else Path(UNKNOWN_EMBEDDINGS_DIR)
        )
        self.busy_timeout_ms = (
            int(busy_timeout_ms) if busy_timeout_ms is not None else int(DB_BUSY_TIMEOUT_MS)
        )
        if project_root is not None:
            self.project_root = Path(project_root)
        else:
            # Production layout: <root>/database/recognition.db
            self.project_root = self.db_path.parent.parent

        self._ready = (
            _ensure_dir(self.db_path.parent)
            and _ensure_dir(self.unknown_faces_dir)
            and _ensure_dir(self.unknown_embeddings_dir)
            and self._ensure_schema()
        )

    # ------------------------------------------------------------------ setup

    def _ensure_schema(self) -> bool:
        try:
            conn = _connect(self.db_path, self.busy_timeout_ms)
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()
            return True
        except sqlite3.Error as exc:
            print(f"[LOGGER] Schema setup failed: {exc}", file=sys.stderr)
            return False

    # ------------------------------------------------------------- internals

    def _relative_to_root(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root.resolve()))
        except (ValueError, OSError):
            return str(path)

    def _insert_event(
        self,
        status: str,
        person_name: Optional[str],
        similarity: Optional[float],
        review_status: Optional[str] = None,
        error_message: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Optional[int]:
        if not self._ready:
            print(f"[LOGGER] Not ready; skipping {status} event.", file=sys.stderr)
            return None

        ts = timestamp or _utc_now_iso()
        created = _utc_now_iso()

        try:
            conn = _connect(self.db_path, self.busy_timeout_ms)
        except sqlite3.Error as exc:
            print(f"[LOGGER] Connect failed ({status}): {exc}", file=sys.stderr)
            return None

        try:
            person_id = None
            if person_name is not None:
                row = conn.execute(
                    "SELECT id FROM people WHERE name = ?", (person_name,)
                ).fetchone()
                if row is not None:
                    person_id = int(row["id"])

            cur = conn.execute(
                """
                INSERT INTO recognition_events
                    (timestamp, created_at, person_id, person_name, status,
                     similarity_score, image_path, embedding_path,
                     review_status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (ts, created, person_id, person_name, status,
                 similarity, review_status, error_message),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            print(f"[LOGGER] Insert failed ({status}): {exc}", file=sys.stderr)
            return None
        finally:
            conn.close()

    def _update_paths(
        self,
        event_id: int,
        image_path: Optional[str],
        embedding_path: Optional[str],
    ) -> None:
        try:
            conn = _connect(self.db_path, self.busy_timeout_ms)
        except sqlite3.Error as exc:
            print(f"[LOGGER] Connect failed (update {event_id}): {exc}", file=sys.stderr)
            return
        try:
            conn.execute(
                "UPDATE recognition_events SET image_path=?, embedding_path=? WHERE id=?",
                (image_path, embedding_path, event_id),
            )
            conn.commit()
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            print(f"[LOGGER] Path update failed for event {event_id}: {exc}", file=sys.stderr)
        finally:
            conn.close()

    @staticmethod
    def _valid_crop(face_crop_bgr) -> bool:
        if face_crop_bgr is None or not isinstance(face_crop_bgr, np.ndarray):
            return False
        if face_crop_bgr.dtype != np.uint8:
            return False
        if face_crop_bgr.ndim != 3 or face_crop_bgr.shape[2] != 3:
            return False
        if face_crop_bgr.shape[0] < 2 or face_crop_bgr.shape[1] < 2:
            return False
        return True

    @staticmethod
    def _valid_embedding(embedding) -> bool:
        if embedding is None:
            return False
        try:
            arr = np.asarray(embedding, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            return False
        if arr.size != 512:
            return False
        if not np.all(np.isfinite(arr)):
            return False
        return True

    # ---------------------------------------------------------- public API

    def log_known(
        self,
        person_name: str,
        similarity: Optional[float],
        timestamp: Optional[str] = None,
    ) -> Optional[int]:
        try:
            if not person_name:
                print("[LOGGER] log_known called without person_name", file=sys.stderr)
                return None
            return self._insert_event(
                status="KNOWN",
                person_name=str(person_name),
                similarity=_safe_float(similarity),
                timestamp=timestamp,
            )
        except Exception as exc:
            print(f"[LOGGER] log_known error: {exc}", file=sys.stderr)
            return None

    def log_unknown(
        self,
        similarity: Optional[float],
        face_crop_bgr: Optional[np.ndarray],
        embedding: Optional[np.ndarray],
        timestamp: Optional[str] = None,
    ) -> Optional[int]:
        try:
            event_id = self._insert_event(
                status="UNKNOWN",
                person_name=None,
                similarity=_safe_float(similarity),
                review_status="PENDING",
                timestamp=timestamp,
            )
            if event_id is None:
                return None

            image_rel: Optional[str] = None
            embedding_rel: Optional[str] = None

            if self._valid_crop(face_crop_bgr):
                uid = uuid.uuid4().hex[:8]
                filename = f"unknown_{event_id:08d}_{uid}.jpg"
                full_path = self.unknown_faces_dir / filename
                try:
                    ok = bool(cv2.imwrite(str(full_path), face_crop_bgr))
                except Exception as exc:
                    ok = False
                    print(
                        f"[LOGGER] Image write raised for event {event_id}: {exc}",
                        file=sys.stderr,
                    )
                if ok:
                    image_rel = self._relative_to_root(full_path)
                else:
                    print(f"[LOGGER] Image write failed for event {event_id}", file=sys.stderr)

            if self._valid_embedding(embedding):
                filename = f"unknown_{event_id:08d}.npy"
                full_path = self.unknown_embeddings_dir / filename
                try:
                    arr = np.asarray(embedding, dtype=np.float32).reshape(512)
                    np.save(full_path, arr)
                    embedding_rel = self._relative_to_root(full_path)
                except (OSError, ValueError) as exc:
                    print(
                        f"[LOGGER] Embedding save failed for event {event_id}: {exc}",
                        file=sys.stderr,
                    )

            if image_rel is not None or embedding_rel is not None:
                self._update_paths(event_id, image_rel, embedding_rel)

            return event_id
        except Exception as exc:
            print(f"[LOGGER] log_unknown error: {exc}", file=sys.stderr)
            return None

    def log_no_face(self, timestamp: Optional[str] = None) -> Optional[int]:
        try:
            return self._insert_event(
                status="NO_FACE",
                person_name=None,
                similarity=None,
                timestamp=timestamp,
            )
        except Exception as exc:
            print(f"[LOGGER] log_no_face error: {exc}", file=sys.stderr)
            return None

    def log_error(self, message: str, timestamp: Optional[str] = None) -> Optional[int]:
        try:
            msg = str(message).strip() if message else ""
            if len(msg) > 500:
                msg = msg[:497] + "..."
            return self._insert_event(
                status="ERROR",
                person_name=None,
                similarity=None,
                error_message=msg or "unknown error",
                timestamp=timestamp,
            )
        except Exception as exc:
            print(f"[LOGGER] log_error error: {exc}", file=sys.stderr)
            return None