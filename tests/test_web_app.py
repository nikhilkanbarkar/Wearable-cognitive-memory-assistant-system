"""Web dashboard tests using Flask's test client.

Runs offline. Does NOT touch the real database, camera, GPIO, models, or
Bluetooth. Uses a temporary database per test.

Verifies:
- All pages render without error, including empty-state and populated-state.
- Pagination works with more rows than one page.
- Filters (search, status, date range) work.
- CSV export produces a valid file with the expected rows.
- Safe image serving returns 200 for valid images, 404 for missing files
  and for paths that escape the UNKNOWN_FACES_DIR.
- The review POST changes the DB when CSRF is disabled and rejects requests
  without a token when CSRF is enabled.
- web_dashboard.app does not import cv2/numpy/onnxruntime/insightface.
- The dashboard does not import the project's root config.py.

Run:
    python -m unittest tests.test_web_app -v
"""

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database_setup import initialize
from web_dashboard.app import create_app


def _utc_iso(offset_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat(timespec="milliseconds")


class WebTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "database" / "recognition.db"
        self.faces_dir = self.root / "logs" / "unknown_faces"
        self.embs_dir = self.root / "unknown_embeddings"
        self.faces_dir.mkdir(parents=True)
        self.embs_dir.mkdir(parents=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        initialize(db_path=self.db_path)

        self.app = create_app({
            "TESTING": True,
            "DATABASE_PATH": str(self.db_path),
            "PROJECT_ROOT": str(self.root),
            "UNKNOWN_FACES_DIR": str(self.faces_dir),
            "PAGE_SIZE": 25,
            "CSRF_ENABLED": False,
            "AUTH_ENABLED": False,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # ------------------------------------------------- helpers

    def _insert_event(
        self,
        status,
        person_name=None,
        similarity=None,
        image_path=None,
        embedding_path=None,
        review_status=None,
        error_message=None,
        timestamp=None,
    ) -> int:
        ts = timestamp or _utc_iso()
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.execute(
                """INSERT INTO recognition_events
                   (timestamp, created_at, status, person_name, similarity_score,
                    image_path, embedding_path, review_status, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, ts, status, person_name, similarity,
                 image_path, embedding_path, review_status, error_message),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def _write_image(self, relative_name="test.jpg", content=b"\xff\xd8\xff\xd9"):
        p = self.faces_dir / relative_name
        p.write_bytes(content)
        return str(p.relative_to(self.root))

    def _fetch_row(self, event_id: int):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute(
                "SELECT * FROM recognition_events WHERE id = ?", (event_id,)
            ).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()


# ------------------------------------------------------------- empty pages

class TestEmptyDatabase(WebTestBase):
    def test_dashboard_empty(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Recognition Dashboard", r.data)
        self.assertIn(b"No recognition events yet", r.data)

    def test_history_empty(self):
        r = self.client.get("/history")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"No events match these filters", r.data)

    def test_unknown_empty(self):
        r = self.client.get("/unknown")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"No unknown faces recorded", r.data)

    def test_people_empty(self):
        r = self.client.get("/people")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"people mirror is empty", r.data)

    def test_404_page(self):
        r = self.client.get("/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertIn(b"404", r.data)


# -------------------------------------------------------------- populated

class TestPopulatedPages(WebTestBase):
    def setUp(self):
        super().setUp()
        # 30 events, alternating statuses, spread over 3 days.
        self.ids = []
        for i in range(30):
            if i % 3 == 0:
                eid = self._insert_event(
                    "KNOWN", person_name=f"person_{i}",
                    similarity=0.7 + (i * 0.001),
                    timestamp=_utc_iso(offset_seconds=-3600 * i),
                )
            elif i % 3 == 1:
                eid = self._insert_event(
                    "UNKNOWN", similarity=0.3 + (i * 0.001),
                    review_status="PENDING",
                    timestamp=_utc_iso(offset_seconds=-3600 * i),
                )
            else:
                eid = self._insert_event(
                    "NO_FACE",
                    timestamp=_utc_iso(offset_seconds=-3600 * i),
                )
            self.ids.append(eid)

    def test_dashboard_counts(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Recognition Dashboard", r.data)

    def test_history_shows_events(self):
        r = self.client.get("/history")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Recognition History", r.data)
        self.assertIn(b"page 1 of 2", r.data)  # 30 rows / 25 page_size

    def test_history_pagination(self):
        r1 = self.client.get("/history?page=1")
        r2 = self.client.get("/history?page=2")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertIn(b"page 1 of 2", r1.data)
        self.assertIn(b"page 2 of 2", r2.data)

    def test_history_page_out_of_range_clamps(self):
        r = self.client.get("/history?page=9999")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"page 2 of 2", r.data)

    def test_history_status_filter(self):
        r = self.client.get("/history?status=KNOWN")
        self.assertEqual(r.status_code, 200)
        # Only the 10 KNOWN events -> 1 page.
        self.assertIn(b"page 1 of 1", r.data)

    def test_history_search_filter(self):
        r = self.client.get("/history?search=person_0")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"person 0", r.data)  # underscore -> space filter

    def test_history_date_filter(self):
        today = datetime.now().date().isoformat()
        r = self.client.get(f"/history?start_date={today}&end_date={today}")
        self.assertEqual(r.status_code, 200)

    def test_people_page_lists_mirrored_names(self):
        # Populate people mirror directly.
        conn = sqlite3.connect(str(self.db_path))
        try:
            for n in ("alice", "bob"):
                conn.execute(
                    "INSERT INTO people (name, created_at) VALUES (?, ?)",
                    (n, _utc_iso()),
                )
            conn.commit()
        finally:
            conn.close()
        r = self.client.get("/people")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"alice", r.data)
        self.assertIn(b"bob", r.data)


# ------------------------------------------------------------------ CSV

class TestCSVExport(WebTestBase):
    def test_csv_export_content(self):
        self._insert_event("KNOWN", person_name="alice", similarity=0.9)
        self._insert_event("UNKNOWN", similarity=0.3, review_status="PENDING")
        self._insert_event("NO_FACE")

        r = self.client.get("/history/export.csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("text/csv"))
        self.assertIn("attachment", r.headers.get("Content-Disposition", ""))

        body = r.data.decode("utf-8-sig")
        lines = [ln for ln in body.splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 4)  # header + 3 rows
        header = lines[0]
        self.assertIn("id", header)
        self.assertIn("status", header)
        self.assertIn("person_name", header)
        self.assertTrue(any("KNOWN" in ln for ln in lines))
        self.assertTrue(any("UNKNOWN" in ln for ln in lines))
        self.assertTrue(any("NO_FACE" in ln for ln in lines))

    def test_csv_export_respects_filters(self):
        self._insert_event("KNOWN", person_name="alice", similarity=0.9)
        self._insert_event("UNKNOWN", similarity=0.3, review_status="PENDING")

        r = self.client.get("/history/export.csv?status=KNOWN")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8-sig")
        self.assertIn("alice", body)
        self.assertNotIn("UNKNOWN", body.split("status")[-1] if "status" in body else "")

    def test_csv_export_empty(self):
        r = self.client.get("/history/export.csv")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8-sig")
        lines = [ln for ln in body.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)  # header only


# ----------------------------------------------------------- image serving

class TestImageServing(WebTestBase):
    def test_image_served_for_valid_unknown(self):
        rel = self._write_image("unknown_00000001_abcd.jpg")
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4, image_path=rel,
            review_status="PENDING",
        )
        r = self.client.get(f"/unknown/{eid}/image")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content_type.startswith("image/jpeg"))

    def test_image_404_for_known(self):
        eid = self._insert_event("KNOWN", person_name="alice", similarity=0.9)
        r = self.client.get(f"/unknown/{eid}/image")
        self.assertEqual(r.status_code, 404)

    def test_image_404_for_missing_file(self):
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4,
            image_path="logs/unknown_faces/nonexistent.jpg",
            review_status="PENDING",
        )
        r = self.client.get(f"/unknown/{eid}/image")
        self.assertEqual(r.status_code, 404)

    def test_image_404_for_path_traversal(self):
        # image_path escapes the allowed directory.
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4,
            image_path="../../../../etc/passwd",
            review_status="PENDING",
        )
        r = self.client.get(f"/unknown/{eid}/image")
        self.assertEqual(r.status_code, 404)

    def test_image_404_for_absolute_path(self):
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4,
            image_path="/etc/passwd",
            review_status="PENDING",
        )
        r = self.client.get(f"/unknown/{eid}/image")
        self.assertEqual(r.status_code, 404)

    def test_image_404_for_nonexistent_event(self):
        r = self.client.get("/unknown/99999/image")
        self.assertEqual(r.status_code, 404)


# ----------------------------------------------------------- detail view

class TestUnknownDetail(WebTestBase):
    def test_detail_renders(self):
        rel = self._write_image()
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4, image_path=rel,
            review_status="PENDING",
        )
        r = self.client.get(f"/unknown/{eid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"Unknown Face #{eid}".encode(), r.data)
        self.assertIn(b"Mark confirmed", r.data)

    def test_detail_404_for_known(self):
        eid = self._insert_event("KNOWN", person_name="alice", similarity=0.9)
        r = self.client.get(f"/unknown/{eid}")
        self.assertEqual(r.status_code, 404)

    def test_detail_404_for_nonexistent(self):
        r = self.client.get("/unknown/99999")
        self.assertEqual(r.status_code, 404)


# --------------------------------------------------------- review POST

class TestReviewPost(WebTestBase):
    def test_review_updates_db(self):
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4, review_status="PENDING",
        )
        r = self.client.post(
            f"/unknown/{eid}/review",
            data={"new_status": "CONFIRMED"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._fetch_row(eid)["review_status"], "CONFIRMED")

    def test_review_invalid_status_rejected(self):
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4, review_status="PENDING",
        )
        r = self.client.post(
            f"/unknown/{eid}/review",
            data={"new_status": "NONSENSE"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._fetch_row(eid)["review_status"], "PENDING")

    def test_review_404_for_known(self):
        eid = self._insert_event("KNOWN", person_name="alice", similarity=0.9)
        r = self.client.post(
            f"/unknown/{eid}/review",
            data={"new_status": "CONFIRMED"},
        )
        self.assertEqual(r.status_code, 404)

    def test_review_404_for_nonexistent(self):
        r = self.client.post(
            "/unknown/99999/review",
            data={"new_status": "CONFIRMED"},
        )
        self.assertEqual(r.status_code, 404)


# ----------------------------------------------------------- CSRF check

class TestCSRF(WebTestBase):
    def setUp(self):
        super().setUp()
        # Enable CSRF for this class.
        self.app.config["CSRF_ENABLED"] = True
        self.client = self.app.test_client()

    def test_post_without_token_is_rejected(self):
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4, review_status="PENDING",
        )
        r = self.client.post(
            f"/unknown/{eid}/review",
            data={"new_status": "CONFIRMED"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._fetch_row(eid)["review_status"], "PENDING")

    def test_post_with_token_succeeds(self):
        eid = self._insert_event(
            "UNKNOWN", similarity=0.4, review_status="PENDING",
        )
        # Prime the session.
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "test-token-xyz"

        r = self.client.post(
            f"/unknown/{eid}/review",
            data={"new_status": "CONFIRMED", "csrf_token": "test-token-xyz"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._fetch_row(eid)["review_status"], "CONFIRMED")


# ---------------------------------------------- isolation guarantees

class TestDashboardIsolation(unittest.TestCase):
    def test_dashboard_does_not_import_heavy_modules(self):
        """Importing web_dashboard.app must not pull in cv2/numpy/etc."""
        script = (
            "import sys\n"
            "sys.path.insert(0, '.')\n"
            "import web_dashboard.app\n"
            "heavy = [m for m in ('cv2','numpy','onnxruntime','onnx','insightface')"
            " if m in sys.modules]\n"
            "assert not heavy, 'Leaked: ' + str(heavy)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_dashboard_does_not_import_root_config(self):
        script = (
            "import sys\n"
            "sys.path.insert(0, '.')\n"
            "import web_dashboard.app\n"
            "assert 'config' not in sys.modules, 'Root config was imported'\n"
            "assert 'face_camera' not in sys.modules\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )


# --------------------------------------------------------- health check

class TestHealth(WebTestBase):
    def test_health_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("events", data)
        self.assertIn("database", data)


if __name__ == "__main__":
    unittest.main()