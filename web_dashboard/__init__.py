"""Cognitive Assist web dashboard package.

The dashboard runs as its own process and reads the SQLite database
produced by recognition_logger.py. It must never be imported from
face_recognition.py, and it must never import cv2, insightface, or any
model / camera code.

Launch with:

    python -m web_dashboard.app
"""

__all__ = []