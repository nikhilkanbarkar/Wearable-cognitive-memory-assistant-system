"""Self-contained configuration for the web dashboard process.

This module intentionally does NOT import the project's root config.py:
importing the root config would pull in cv2 and consume ~50-80 MB RSS in
the dashboard process. All paths are derived from this file's own location.
"""

import os
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent

DATABASE_PATH = PROJECT_ROOT / "database" / "recognition.db"
UNKNOWN_FACES_DIR = PROJECT_ROOT / "logs" / "unknown_faces"
UNKNOWN_EMBEDDINGS_DIR = PROJECT_ROOT / "unknown_embeddings"
METADATA_FILE = PROJECT_ROOT / "Embeddings" / "metadata_clean.csv"


DB_BUSY_TIMEOUT_MS = 5000

PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "5000"))


# A static SECRET_KEY is sufficient: no user sessions are stored, and the
# dashboard is designed for LAN-only use behind an optional HTTP basic auth.
SECRET_KEY = os.environ.get(
    "DASHBOARD_SECRET_KEY",
    "cognitive-assist-dashboard-static-key",
)


# Optional HTTP basic auth. Empty = disabled (default).
# Enable by exporting both env vars before starting the dashboard, e.g.:
#     export DASHBOARD_USER=pi
#     export DASHBOARD_PASSWORD='choose-a-strong-password'
USERNAME = os.environ.get("DASHBOARD_USER", "")
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")