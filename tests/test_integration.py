"""Integration tests for the recognition -> logger pipeline.

These tests exercise the real `process_scan` function from face_recognition.py
with mocked hardware (camera, models, GPIO, Bluetooth, OLED) so they can run
on any machine that has the project's Python dependencies (cv2, numpy,
insightface). No real camera, GPIO, Bluetooth, or model files are required.

`lgpio` is stubbed in sys.modules before importing face_recognition, because
face_recognition imports button_handler which imports lgpio.

Run:
    python -m unittest tests.test_integration -v
"""

import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

# Stub `lgpio` before importing face_recognition.
if "lgpio" not in sys.modules:
    _lgpio_stub = types.ModuleType("lgpio")
    _lgpio_stub.gpiochip_open = lambda *a, **k: 0
    _lgpio_stub.gpio_claim_alert = lambda *a, **k: None
    _lgpio_stub.callback = lambda *a, **k: mock.MagicMock()
    _lgpio_stub.gpio_read = lambda *a, **k: 1
    _lgpio_stub.gpiochip_close = lambda *a, **k: None
    _lgpio_stub.BOTH_EDGES = 0
    _lgpio_stub.SET_PULL_UP = 0
    sys.modules["lgpio"] = _lgpio_stub

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import face_recognition  # noqa: E402
from recognition_logger import RecognitionLogger  # noqa: E402


# ----------------------------------------------------------------- helpers

class FakeArcFace:
    """Deterministic stand-in for ArcFaceONNX.get_feat()."""

    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32).reshape(-1)

    def get_feat(self, aligned_img):
        # Real API returns (1, 512) or (512,); process_scan flattens with
        # .reshape(-1), so (1, 512) is safe.
        return self.vector.reshape(1, -1)


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    return v / np.linalg.norm(v)


# ----------------------------------------------------------------- base

class IntegrationTestBase(unittest.TestCase):
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

        # Two registered people with orthogonal embeddings.
        alice = np.zeros(512, dtype=np.float32)
        alice[0] = 1.0
        bob = np.zeros(512, dtype=np.float32)
        bob[1] = 1.0
        self.db_embeddings = np.stack([alice, bob])
        self.db_labels = np.asarray(["alice", "bob"], dtype=str)

        self.alice_vec = alice
        self.bob_vec = bob
        # Orthogonal to both alice and bob -> similarity ~0 -> UNKNOWN.
        stranger = np.zeros(512, dtype=np.float32)
        stranger[2] = 1.0
        self.stranger_vec = stranger

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM recognition_events ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()

    def _fake_frame(self):
        return np.full((240, 320, 3), 128, dtype=np.uint8)

    def _fake_landmarks(self):
        # A realistic, non-degenerate 5-point layout (two eyes, nose, two
        # mouth corners), so insightface.utils.face_align.norm_crop can
        # produce a valid 112x112 aligned crop.
        return np.array(
            [
                [100.0, 120.0],  # left eye
                [140.0, 120.0],  # right eye
                [120.0, 140.0],  # nose
                [105.0, 160.0],  # left mouth corner
                [135.0, 160.0],  # right mouth corner
            ],
            dtype=np.float32,
        )

    def _run_scan(self, arcface_vec, best):
        """Call the real process_scan once, with hardware mocked."""
        arcface = FakeArcFace(arcface_vec)

        with mock.patch.object(
            face_recognition, "capture_best_face", return_value=best
        ), mock.patch.object(
            face_recognition, "announce", return_value=None
        ), mock.patch.object(
            face_recognition, "oled_status", return_value=None
        ):
            face_recognition.process_scan(
                camera=None,
                yunet=None,
                arcface=arcface,
                db_embeddings=self.db_embeddings,
                db_labels=self.db_labels,
                display=None,
                recognition_logger=self.logger,
            )


# ---------------------------------------------------------- known face

class TestKnownFace(IntegrationTestBase):
    def test_known_face_creates_one_known_event(self):
        best = (1.0, self._fake_frame(), self._fake_landmarks(), 0.95)

        self._run_scan(self.alice_vec, best)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "KNOWN")
        self.assertEqual(rows[0]["person_name"], "alice")
        self.assertIsNotNone(rows[0]["similarity_score"])
        self.assertGreaterEqual(rows[0]["similarity_score"], 0.99)
        self.assertIsNone(rows[0]["image_path"])
        self.assertIsNone(rows[0]["embedding_path"])
        self.assertIsNone(rows[0]["review_status"])

    def test_known_face_matches_bob(self):
        best = (1.0, self._fake_frame(), self._fake_landmarks(), 0.9)
        self._run_scan(self.bob_vec, best)
        row = self._rows()[0]
        self.assertEqual(row["status"], "KNOWN")
        self.assertEqual(row["person_name"], "bob")


# -------------------------------------------------------- unknown face

class TestUnknownFace(IntegrationTestBase):
    def test_unknown_face_creates_one_unknown_event_with_files(self):
        best = (1.0, self._fake_frame(), self._fake_landmarks(), 0.9)

        self._run_scan(self.stranger_vec, best)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertEqual(row["review_status"], "PENDING")
        self.assertIsNotNone(row["image_path"])
        self.assertIsNotNone(row["embedding_path"])
        self.assertTrue((self.root / row["image_path"]).is_file())
        self.assertTrue((self.root / row["embedding_path"]).is_file())

        # The saved embedding must equal the one produced by arcface,
        # normalised by recognize_embedding's L2 dot-product path.
        loaded = np.load(self.root / row["embedding_path"])
        self.assertEqual(loaded.shape, (512,))
        self.assertEqual(loaded.dtype, np.float32)
        np.testing.assert_allclose(
            loaded, _unit(self.stranger_vec), rtol=1e-5, atol=1e-5
        )


# ------------------------------------------------------------- no face

class TestNoFace(IntegrationTestBase):
    def test_no_face_creates_no_face_event(self):
        self._run_scan(self.alice_vec, None)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "NO_FACE")

    def test_no_face_does_not_create_unknown_row(self):
        self._run_scan(self.alice_vec, None)
        statuses = [r["status"] for r in self._rows()]
        self.assertNotIn("UNKNOWN", statuses)


# -------------------------------------------------------------- error

class TestError(IntegrationTestBase):
    def test_capture_exception_creates_error_event(self):
        with mock.patch.object(
            face_recognition,
            "capture_best_face",
            side_effect=RuntimeError("camera disconnected"),
        ), mock.patch.object(
            face_recognition, "announce", return_value=None
        ), mock.patch.object(
            face_recognition, "oled_status", return_value=None
        ):
            face_recognition.process_scan(
                camera=None,
                yunet=None,
                arcface=FakeArcFace(self.alice_vec),
                db_embeddings=self.db_embeddings,
                db_labels=self.db_labels,
                display=None,
                recognition_logger=self.logger,
            )

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ERROR")
        self.assertIn("camera disconnected", rows[0]["error_message"])


# ------------------------------------------------------- deduplication

class TestDeduplication(IntegrationTestBase):
    def test_one_scan_one_event(self):
        """capture_best_face samples many internal frames but returns one
        result. process_scan is therefore called once per button press, and
        must produce exactly one DB row regardless of how many internal
        frames the capture loop examined.
        """
        best = (1.0, self._fake_frame(), self._fake_landmarks(), 0.9)

        self._run_scan(self.alice_vec, best)   # scan 1
        self._run_scan(self.alice_vec, best)   # scan 2
        self._run_scan(self.alice_vec, best)   # scan 3

        rows = self._rows()
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertEqual(r["status"], "KNOWN")


# ----------------------------------------------- logger failure safety

class TestLoggerIsolation(IntegrationTestBase):
    def test_logger_failure_does_not_break_scan(self):
        """If the logger raises (simulated catastrophic failure), process_scan
        must still complete and still call announce/oled as usual."""
        best = (1.0, self._fake_frame(), self._fake_landmarks(), 0.9)

        with mock.patch.object(
            self.logger, "log_known", side_effect=RuntimeError("boom")
        ), mock.patch.object(
            face_recognition, "capture_best_face", return_value=best
        ), mock.patch.object(
            face_recognition, "announce"
        ) as announce_mock, mock.patch.object(
            face_recognition, "oled_status", return_value=None
        ):
            face_recognition.process_scan(
                camera=None,
                yunet=None,
                arcface=FakeArcFace(self.alice_vec),
                db_embeddings=self.db_embeddings,
                db_labels=self.db_labels,
                display=None,
                recognition_logger=self.logger,
            )

        self.assertTrue(announce_mock.called)
        # log_known raised before insert; no rows written.
        self.assertEqual(len(self._rows()), 0)

    def test_process_scan_without_logger_still_works(self):
        """Backward compatibility: process_scan(recognition_logger=None)
        must not raise."""
        best = (1.0, self._fake_frame(), self._fake_landmarks(), 0.9)

        with mock.patch.object(
            face_recognition, "capture_best_face", return_value=best
        ), mock.patch.object(
            face_recognition, "announce", return_value=None
        ), mock.patch.object(
            face_recognition, "oled_status", return_value=None
        ):
            try:
                face_recognition.process_scan(
                    camera=None,
                    yunet=None,
                    arcface=FakeArcFace(self.alice_vec),
                    db_embeddings=self.db_embeddings,
                    db_labels=self.db_labels,
                    display=None,
                    recognition_logger=None,
                )
            except Exception as exc:
                self.fail(f"process_scan raised without a logger: {exc}")


# ------------------------------------------ concurrency / persistence

class TestConcurrency(IntegrationTestBase):
    def test_two_loggers_can_write_independently(self):
        """A second logger instance (the dashboard's future read/write
        connection) and the recognition logger must coexist without
        lock errors under WAL mode."""
        logger2 = RecognitionLogger(
            db_path=self.db_path,
            unknown_faces_dir=self.faces_dir,
            unknown_embeddings_dir=self.embs_dir,
            project_root=self.root,
        )

        self.assertIsNotNone(self.logger.log_known("alice", 0.9))
        self.assertIsNotNone(logger2.log_known("bob", 0.85))

        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["person_name"] for r in rows}, {"alice", "bob"})


# ------------------------------------------ structural compatibility

class TestStructuralCompatibility(unittest.TestCase):
    def test_public_api_unchanged(self):
        for name in (
            "main",
            "process_scan",
            "announce",
            "speech_worker",
            "init_oled",
            "oled_status",
        ):
            self.assertTrue(
                hasattr(face_recognition, name),
                f"face_recognition.{name} is missing",
            )

    def test_process_scan_accepts_logger_kwarg(self):
        import inspect

        params = inspect.signature(
            face_recognition.process_scan
        ).parameters
        self.assertIn("recognition_logger", params)
        self.assertIsNone(params["recognition_logger"].default)

    def test_recognition_logger_imported(self):
        self.assertTrue(hasattr(face_recognition, "RecognitionLogger"))


if __name__ == "__main__":
    unittest.main()