"""Read-only SQLite access helpers for the dashboard.

All functions accept an optional `db_path` so tests can point them at a
temporary database. Every query is parameterised. SQLite errors are
caught and result in empty/zero data — the dashboard never raises a 500
because of a transient lock or a missing schema.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from . import config as wcfg


VALID_STATUSES = ("KNOWN", "UNKNOWN", "NO_FACE", "ERROR")
VALID_REVIEW_STATUSES = ("PENDING", "CONFIRMED", "DISMISSED")


@contextmanager
def _db(db_path: Optional[Path]):
    """Yield a sqlite3 connection, or yield None if the DB file is missing."""
    path = Path(db_path) if db_path else Path(wcfg.DATABASE_PATH)
    if not path.is_file():
        yield None
        return

    conn = sqlite3.connect(str(path), timeout=wcfg.DB_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout={int(wcfg.DB_BUSY_TIMEOUT_MS)}")
    except sqlite3.Error:
        pass

    try:
        yield conn
    finally:
        conn.close()


def _local_midnight_utc_iso() -> str:
    """Today's local midnight expressed as a UTC ISO-8601 string."""
    now_local = datetime.now().astimezone()
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _date_str_to_utc_iso(date_str: str, end_of_day: bool) -> Optional[str]:
    """Parse a YYYY-MM-DD string as *local* date; return UTC ISO-8601 or None.

    For end_of_day=True, the result is the exclusive upper bound: the
    next-day local midnight in UTC.
    """
    try:
        d = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None
    if end_of_day:
        d = d + timedelta(days=1)
    # Naive datetime -> local timezone -> UTC
    return d.astimezone().astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _build_events_filter(filters: Optional[dict]) -> tuple[str, list]:
    """Translate a filter dict into (WHERE clause, params list)."""
    f = filters or {}
    clauses: list[str] = []
    params: list = []

    search = str(f.get("search") or "").strip()
    if search:
        like_raw = f"%{search}%"
        like_spaced = f"%{search.replace('_', ' ')}%"
        clauses.append(
            "(person_name LIKE ? "
            "OR REPLACE(person_name, '_', ' ') LIKE ? "
            "OR CAST(id AS TEXT) = ?)"
        )
        params.extend([like_raw, like_spaced, search])

    status = str(f.get("status") or "").strip().upper()
    if status in VALID_STATUSES:
        clauses.append("status = ?")
        params.append(status)

    start = str(f.get("start_date") or "").strip()
    if start:
        iso = _date_str_to_utc_iso(start, end_of_day=False)
        if iso:
            clauses.append("timestamp >= ?")
            params.append(iso)

    end = str(f.get("end_date") or "").strip()
    if end:
        iso = _date_str_to_utc_iso(end, end_of_day=True)  # exclusive upper bound
        if iso:
            clauses.append("timestamp < ?")
            params.append(iso)

    review = str(f.get("review_status") or "").strip().upper()
    if review in VALID_REVIEW_STATUSES:
        clauses.append("review_status = ?")
        params.append(review)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


# ------------------------------------------------------------------ stats

def get_summary_stats(db_path: Optional[Path] = None) -> dict:
    stats = {
        "total": 0,
        "known": 0,
        "unknown": 0,
        "no_face": 0,
        "error": 0,
        "today": 0,
    }
    with _db(db_path) as conn:
        if conn is None:
            return stats
        try:
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM recognition_events GROUP BY status"
            ).fetchall():
                key = str(row["status"]).lower()
                if key in stats:
                    stats[key] = int(row["n"])
                stats["total"] += int(row["n"])
        except sqlite3.Error:
            return stats
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM recognition_events WHERE timestamp >= ?",
                (_local_midnight_utc_iso(),),
            ).fetchone()
            stats["today"] = int(row["n"]) if row else 0
        except sqlite3.Error:
            pass
    return stats


def get_recent_events(limit: int = 10, db_path: Optional[Path] = None) -> list[dict]:
    rows_out: list[dict] = []
    try:
        limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit = 10
    with _db(db_path) as conn:
        if conn is None:
            return rows_out
        try:
            rows = conn.execute(
                """
                SELECT id, timestamp, status, person_name, similarity_score,
                       image_path, embedding_path, review_status
                FROM recognition_events
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.Error:
            return rows_out
        for r in rows:
            rows_out.append(dict(r))
    return rows_out


# ---------------------------------------------------------- history page

def get_events_paginated(
    filters: Optional[dict] = None,
    page: int = 1,
    page_size: int = wcfg.PAGE_SIZE,
    db_path: Optional[Path] = None,
) -> tuple[list[dict], int]:
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(wcfg.MAX_PAGE_SIZE, int(page_size)))
    except (TypeError, ValueError):
        page_size = wcfg.PAGE_SIZE
    offset = (page - 1) * page_size

    where, params = _build_events_filter(filters)

    with _db(db_path) as conn:
        if conn is None:
            return [], 0
        try:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM recognition_events" + where, params
            ).fetchone()
            total = int(total_row["n"]) if total_row else 0
            rows = conn.execute(
                "SELECT * FROM recognition_events"
                + where
                + " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        except sqlite3.Error:
            return [], 0
        return [dict(r) for r in rows], total


def iter_events_for_csv(
    filters: Optional[dict] = None,
    db_path: Optional[Path] = None,
) -> Iterator[dict]:
    where, params = _build_events_filter(filters)
    conn = None
    path = Path(db_path) if db_path else Path(wcfg.DATABASE_PATH)
    if not path.is_file():
        return
    conn = sqlite3.connect(str(path), timeout=wcfg.DB_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout={int(wcfg.DB_BUSY_TIMEOUT_MS)}")
    except sqlite3.Error:
        pass
    try:
        cur = conn.execute(
            "SELECT id, timestamp, status, person_name, similarity_score, "
            "image_path, embedding_path, review_status, error_message "
            "FROM recognition_events"
            + where
            + " ORDER BY timestamp DESC, id DESC",
            params,
        )
        for r in cur:
            yield dict(r)
    except sqlite3.Error:
        return
    finally:
        conn.close()


# ------------------------------------------------------ unknown-faces page

def get_unknown_faces_paginated(
    filters: Optional[dict] = None,
    page: int = 1,
    page_size: int = wcfg.PAGE_SIZE,
    db_path: Optional[Path] = None,
) -> tuple[list[dict], int]:
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(wcfg.MAX_PAGE_SIZE, int(page_size)))
    except (TypeError, ValueError):
        page_size = wcfg.PAGE_SIZE
    offset = (page - 1) * page_size

    where_parts = ["status = 'UNKNOWN'", "image_path IS NOT NULL"]
    params: list = []
    review = str((filters or {}).get("review_status") or "").strip().upper()
    if review in VALID_REVIEW_STATUSES:
        where_parts.append("review_status = ?")
        params.append(review)
    where = " WHERE " + " AND ".join(where_parts)

    with _db(db_path) as conn:
        if conn is None:
            return [], 0
        try:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM recognition_events" + where, params
            ).fetchone()
            total = int(total_row["n"]) if total_row else 0
            rows = conn.execute(
                "SELECT id, timestamp, similarity_score, image_path, "
                "embedding_path, review_status "
                "FROM recognition_events"
                + where
                + " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        except sqlite3.Error:
            return [], 0
        return [dict(r) for r in rows], total


def get_event_by_id(event_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return None
    with _db(db_path) as conn:
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM recognition_events WHERE id = ?", (eid,)
            ).fetchone()
        except sqlite3.Error:
            return None
        return dict(row) if row else None


def update_review_status(
    event_id: int,
    new_status: str,
    db_path: Optional[Path] = None,
) -> bool:
    if new_status not in VALID_REVIEW_STATUSES:
        return False
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return False

    path = Path(db_path) if db_path else Path(wcfg.DATABASE_PATH)
    if not path.is_file():
        return False

    conn = sqlite3.connect(str(path), timeout=wcfg.DB_BUSY_TIMEOUT_MS / 1000.0)
    try:
        conn.execute(f"PRAGMA busy_timeout={int(wcfg.DB_BUSY_TIMEOUT_MS)}")
    except sqlite3.Error:
        pass
    try:
        cur = conn.execute(
            "UPDATE recognition_events SET review_status = ? "
            "WHERE id = ? AND status = 'UNKNOWN'",
            (new_status, eid),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return False
    finally:
        conn.close()


# --------------------------------------------------------- people page

def get_people_with_counts(db_path: Optional[Path] = None) -> list[dict]:
    with _db(db_path) as conn:
        if conn is None:
            return []
        try:
            rows = conn.execute(
                """
                SELECT p.id, p.name, p.created_at,
                       SUM(CASE WHEN e.status = 'KNOWN' THEN 1 ELSE 0 END) AS known_count,
                       COUNT(e.id) AS total_events
                FROM people p
                LEFT JOIN recognition_events e
                  ON e.person_id = p.id
                  OR (e.person_id IS NULL AND e.person_name = p.name)
                GROUP BY p.id
                ORDER BY p.name COLLATE NOCASE
                """
            ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]