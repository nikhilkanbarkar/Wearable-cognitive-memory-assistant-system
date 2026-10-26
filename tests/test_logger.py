import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from recognition_logger import RecognitionLogger


class LoggerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "database" / "recognition.db"
        self.faces_dir = self.root / "logs" / "unknown_faces"
        self.embs_dir = self.root / "unknown_embeddings"
        self.logger = RecognitionLogger(
            db_path=self.db_path,
            unknown_faces_dir=self.faces_dir,
            unknown_embeddings_dir=self.embs_dir,
            project_root=self.root,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch(self, event_id):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM recognition_events WHERE id = ?", (event_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


class TestKnownLogging(LoggerTestBase):
    def test_log_known(self):
        eid = self.logger.log_known("alice", 0.87)
        self.assertIsNotNone(eid)
        row = self._fetch(eid)
        self.assertEqual(row["status"], "KNOWN")
        self.assertEqual(row["person_name"], "alice")
        self.assertAlmostEqual(row["similarity_score"], 0.87)
        self.assertIsNone(row["image_path"])
        self.assertIsNone(row["embedding_path"])

    def test_log_known_without_name(self):
        self.assertIsNone(self.logger.log_known("", 0.5))

    def test_log_known_links_person_id_when_present(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO people (name, created_at) VALUES (?, ?)",
                ("alice", "2025-01-01T00:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()
        eid = self.logger.log_known("alice", 0.9)
        row = self._fetch(eid)
        self.assertIsNotNone(row["person_id"])

    def test_log_known_unregistered_person_still_logs(self):
        eid = self.logger.log_known("stranger", 0.81)
        row = self._fetch(eid)
        self.assertIsNotNone(eid)
        self.assertIsNone(row["person_id"])
        self.assertEqual(row["person_name"], "stranger")


class TestUnknownLogging(LoggerTestBase):
    def _crop(self):
        return np.full((112, 112, 3), 128, dtype=np.uint8)

    def _embedding(self):
        v = np.random.randn(512).astype(np.float32)
        return v / np.linalg.norm(v)

    def test_log_unknown_full(self):
        eid = self.logger.log_unknown(0.42, self._crop(), self._embedding())
        self.assertIsNotNone(eid)
        row = self._fetch(eid)
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(row["review_status"], "PENDING")
        self.assertAlmostEqual(row["similarity_score"], 0.42)
        self.assertIsNotNone(row["image_path"])
        self.assertIsNotNone(row["embedding_path"])
        self.assertTrue((self.root / row["image_path"]).is_file())
        self.assertTrue((self.root / row["embedding_path"]).is_file())

        loaded = np.load(self.root / row["embedding_path"])
        self.assertEqual(loaded.shape, (512,))
        self.assertEqual(loaded.dtype, np.float32)

    def test_log_unknown_without_embedding(self):
        eid = self.logger.log_unknown(0.42, self._crop(), None)
        row = self._fetch(eid)
        self.assertIsNotNone(row["image_path"])
        self.assertIsNone(row["embedding_path"])

    def test_log_unknown_invalid_embedding_wrong_size(self):
        eid = self.logger.log_unknown(0.42, self._crop(), np.zeros(256, dtype=np.float32))
        row = self._fetch(eid)
        self.assertIsNone(row["embedding_path"])

    def test_log_unknown_invalid_embedding_nan(self):
        eid = self.logger.log_unknown(0.42, self._crop(), np.full(512, np.nan, dtype=np.float32))
        row = self._fetch(eid)
        self.assertIsNone(row["embedding_path"])

    def test_log_unknown_invalid_crop_dtype(self):
        bad = np.zeros((112, 112, 3), dtype=np.float64)
        eid = self.logger.log_unknown(0.42, bad, self._embedding())
        row = self._fetch(eid)
        self.assertIsNone(row["image_path"])
        self.assertIsNotNone(row["embedding_path"])

    def test_log_unknown_invalid_crop_shape(self):
        bad = np.zeros((112, 112), dtype=np.uint8)
        eid = self.logger.log_unknown(0.42, bad, None)
        row = self._fetch(eid)
        self.assertIsNone(row["image_path"])

    def test_log_unknown_imwrite_false(self):
        with mock.patch("recognition_logger.cv2.imwrite", return_value=False):
            eid = self.logger.log_unknown(0.42, self._crop(), self._embedding())
        row = self._fetch(eid)
        self.assertIsNone(row["image_path"])
        self.assertIsNotNone(row["embedding_path"])

    def test_log_unknown_imwrite_raises(self):
        with mock.patch("recognition_logger.cv2.imwrite", side_effect=RuntimeError("disk full")):
            eid = self.logger.log_unknown(0.42, self._crop(), None)
        self.assertIsNotNone(eid)
        row = self._fetch(eid)
        self.assertIsNone(row["image_path"])

    def test_log_unknown_npy_save_raises(self):
        with mock.patch("recognition_logger.np.save", side_effect=OSError("nope")):
            eid = self.logger.log_unknown(0.42, None, self._embedding())
        row = self._fetch(eid)
        self.assertIsNone(row["embedding_path"])

    def test_log_unknown_no_crop_no_embedding(self):
        eid = self.logger.log_unknown(0.42, None, None)
        self.assertIsNotNone(eid)
        row = self._fetch(eid)
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertIsNone(row["image_path"])
        self.assertIsNone(row["embedding_path"])


class TestNoFaceLogging(LoggerTestBase):
    def test_log_no_face(self):
        eid = self.logger.log_no_face()
        self.assertIsNotNone(eid)
        row = self._fetch(eid)
        self.assertEqual(row["status"], "NO_FACE")
        self.assertIsNone(row["person_name"])
        self.assertIsNone(row["image_path"])


class TestErrorLogging(LoggerTestBase):
    def test_log_error(self):
        eid = self.logger.log_error("Camera failed")
        self.assertIsNotNone(eid)
        row = self._fetch(eid)
        self.assertEqual(row["status"], "ERROR")
        self.assertEqual(row["error_message"], "Camera failed")

    def test_log_error_truncates(self):
        eid = self.logger.log_error("x" * 1000)
        row = self._fetch(eid)
        self.assertLessEqual(len(row["error_message"]), 500)

    def test_log_error_empty_message(self):
        eid = self.logger.log_error("")
        row = self._fetch(eid)
        self.assertIsNotNone(row["error_message"])


class TestFailures(LoggerTestBase):
    def test_db_error_returns_none(self):
        with mock.patch(
            "recognition_logger._connect", side_effect=sqlite3.OperationalError("locked")
        ):
            self.assertIsNone(self.logger.log_known("alice", 0.8))

    def test_db_error_does_not_raise(self):
        with mock.patch(
            "recognition_logger._connect", side_effect=sqlite3.OperationalError("locked")
        ):
            try:
                self.logger.log_no_face()
                self.logger.log_error("test")
                self.logger.log_unknown(0.3, None, None)
            except Exception as exc:
                self.fail(f"Logger raised unexpectedly: {exc}")

    def test_not_ready_returns_none(self):
        self.logger._ready = False
        self.assertIsNone(self.logger.log_no_face())
        self.assertIsNone(self.logger.log_known("alice", 0.9))
        self.assertIsNone(self.logger.log_error("x"))


class TestPersistence(LoggerTestBase):
    def test_reopen_persists(self):
        eid = self.logger.log_known("carol", 0.75)
        RecognitionLogger(  # second instance, fresh connection
            db_path=self.db_path,
            unknown_faces_dir=self.faces_dir,
            unknown_embeddings_dir=self.embs_dir,
            project_root=self.root,
        )
        row = self._fetch(eid)
        self.assertIsNotNone(row)
        self.assertEqual(row["person_name"], "carol")


if __name__ == "__main__":
    unittest.main()