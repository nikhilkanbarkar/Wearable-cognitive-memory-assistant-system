import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database_setup import initialize, sync_people, verify_schema


class TestDatabaseSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "database" / "recognition.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_initialize_creates_file(self):
        result = initialize(db_path=self.db_path)
        self.assertTrue(result.exists())

    def test_initialize_is_idempotent(self):
        initialize(db_path=self.db_path)

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO recognition_events (timestamp, created_at, status) VALUES (?, ?, ?)",
                ("2025-01-01T00:00:00.000+00:00", "2025-01-01T00:00:00.000+00:00", "NO_FACE"),
            )
            conn.commit()
        finally:
            conn.close()

        initialize(db_path=self.db_path)  # must not destroy the row

        conn = sqlite3.connect(str(self.db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM recognition_events").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_verify_schema_passes(self):
        initialize(db_path=self.db_path)
        verify_schema(self.db_path, 5000)

    def test_tables_exist(self):
        initialize(db_path=self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        self.assertIn("people", tables)
        self.assertIn("recognition_events", tables)

    def test_indexes_exist(self):
        initialize(db_path=self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            indexes = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        finally:
            conn.close()
        for name in (
            "idx_events_timestamp",
            "idx_events_status",
            "idx_events_person_id",
            "idx_events_review_status",
        ):
            self.assertIn(name, indexes)


class TestDatabaseOperations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "database" / "recognition.db"
        initialize(db_path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _insert(self, status, person_name=None, similarity=None,
                review_status=None, error_message=None, ts=None):
        conn = sqlite3.connect(str(self.db_path))
        try:
            ts = ts or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            cur = conn.execute(
                """INSERT INTO recognition_events
                   (timestamp, created_at, person_name, status,
                    similarity_score, review_status, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ts, ts, person_name, status, similarity, review_status, error_message),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _fetch_all(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM recognition_events ORDER BY timestamp DESC, id DESC"
            ).fetchall()]
        finally:
            conn.close()

    def test_insert_known(self):
        eid = self._insert("KNOWN", "alice", 0.85)
        self.assertIsNotNone(eid)
        row = self._fetch_all()[0]
        self.assertEqual(row["status"], "KNOWN")
        self.assertEqual(row["person_name"], "alice")
        self.assertAlmostEqual(row["similarity_score"], 0.85)

    def test_insert_unknown(self):
        self._insert("UNKNOWN", None, 0.35, review_status="PENDING")
        row = self._fetch_all()[0]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(row["review_status"], "PENDING")

    def test_insert_no_face(self):
        self._insert("NO_FACE")
        self.assertEqual(self._fetch_all()[0]["status"], "NO_FACE")

    def test_insert_error(self):
        self._insert("ERROR", error_message="disk full")
        row = self._fetch_all()[0]
        self.assertEqual(row["status"], "ERROR")
        self.assertEqual(row["error_message"], "disk full")

    def test_status_check_constraint(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO recognition_events (timestamp, created_at, status) VALUES (?, ?, ?)",
                    ("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00", "INVALID"),
                )
        finally:
            conn.close()

    def test_timestamp_ordering(self):
        self._insert("NO_FACE", ts="2025-01-01T10:00:00.000+00:00")
        self._insert("NO_FACE", ts="2025-01-01T12:00:00.000+00:00")
        self._insert("NO_FACE", ts="2025-01-01T11:00:00.000+00:00")
        rows = self._fetch_all()
        self.assertEqual(rows[0]["timestamp"], "2025-01-01T12:00:00.000+00:00")
        self.assertEqual(rows[2]["timestamp"], "2025-01-01T10:00:00.000+00:00")

    def test_filter_by_status(self):
        self._insert("KNOWN", "alice", 0.9)
        self._insert("UNKNOWN", None, 0.3)
        self._insert("NO_FACE")
        conn = sqlite3.connect(str(self.db_path))
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM recognition_events WHERE status = ?", ("KNOWN",)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 1)

    def test_filter_by_date_range(self):
        self._insert("NO_FACE", ts="2025-01-01T10:00:00.000+00:00")
        self._insert("NO_FACE", ts="2025-01-02T10:00:00.000+00:00")
        self._insert("NO_FACE", ts="2025-01-03T10:00:00.000+00:00")
        conn = sqlite3.connect(str(self.db_path))
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM recognition_events "
                "WHERE timestamp >= ? AND timestamp < ?",
                ("2025-01-02T00:00:00.000+00:00", "2025-01-03T00:00:00.000+00:00"),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 1)

    def test_persistence_after_reopen(self):
        self._insert("KNOWN", "bob", 0.7)
        conn = sqlite3.connect(str(self.db_path))
        try:
            n = conn.execute("SELECT COUNT(*) FROM recognition_events").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 1)


class TestSyncPeople(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "database" / "recognition.db"
        initialize(db_path=self.db_path)
        self.metadata = Path(self.tmp.name) / "metadata_clean.csv"
        self.metadata.write_text(
            "person,other\nalice,1\nbob,2\nalice,3\ncarol,4\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync_creates_rows(self):
        inserted = sync_people(db_path=self.db_path, metadata_file=self.metadata)
        self.assertEqual(inserted, 3)
        conn = sqlite3.connect(str(self.db_path))
        try:
            names = sorted(r[0] for r in conn.execute("SELECT name FROM people").fetchall())
        finally:
            conn.close()
        self.assertEqual(names, ["alice", "bob", "carol"])

    def test_sync_is_idempotent(self):
        sync_people(db_path=self.db_path, metadata_file=self.metadata)
        inserted = sync_people(db_path=self.db_path, metadata_file=self.metadata)
        self.assertEqual(inserted, 0)


if __name__ == "__main__":
    unittest.main()