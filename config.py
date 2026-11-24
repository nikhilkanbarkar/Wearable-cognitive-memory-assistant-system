#!/usr/bin/env python3

import os
from pathlib import Path

# Set these before importing NumPy or ONNX Runtime.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import cv2


# ------------------------------ PATHS ------------------------------

ROOT = Path(__file__).resolve().parent

YUNET_MODEL = ROOT / "models" / "face_detection_yunet_2026may.onnx"
ARCFACE_MODEL = ROOT / "models" / "w600k_r50.onnx"

EMBEDDINGS_FILE = ROOT / "Embeddings" / "embeddings_clean.npy"
METADATA_FILE = ROOT / "Embeddings" / "metadata_clean.csv"


# ------------------------------ BUTTON ------------------------------

GPIO_CHIP = 0
BUTTON_GPIO = 17

DEBOUNCE_SECONDS = 0.050
BUTTON_COOLDOWN_SECONDS = 5.0


# ------------------------------ CAMERA ------------------------------

CAMERA_INDEX = 0
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240

CAPTURE_SECONDS = 1.0
DETECT_EVERY_N_FRAMES = 2
MIN_FACE_SIZE = 40


# ------------------------------ FACE RECOGNITION ------------------------------

THRESHOLD = 0.40

YUNET_SCORE_THRESHOLD = 0.60
YUNET_NMS_THRESHOLD = 0.30
YUNET_TOP_K = 500


# ------------------------------ ONNX RUNTIME ------------------------------

ORT_INTRA_OP_THREADS = 2
ORT_INTER_OP_THREADS = 1


# ------------------------------ OPENCV ------------------------------

cv2.setNumThreads(1)
cv2.setUseOptimized(True)


# ------------------------------ DATABASE (ADDED) ------------------------------

DATABASE_DIR = ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "recognition.db"

LOGS_DIR = ROOT / "logs"
UNKNOWN_FACES_DIR = LOGS_DIR / "unknown_faces"
UNKNOWN_EMBEDDINGS_DIR = ROOT / "unknown_embeddings"

DB_BUSY_TIMEOUT_MS = 5000


# ------------------------------ PERSON PROFILES (ADDED) ------------------------------

# CSV mapping person names (from metadata_clean.csv) to relationship,
# pronoun, and custom spoken message. Reloaded automatically when edited.
PERSON_INFO_FILE = ROOT / "person_info.csv"


# ------------------------------ DASHBOARD (ADDED) ------------------------------

DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5000
DASHBOARD_PAGE_SIZE = 25

# ------------------------------ VOICE ASSISTANT (ADDED) ------------------------------

# Get your free API key from https://console.groq.com/keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# The GPIO pin for the Assistant button (BCM numbering). 
# We are using 27 (Physical pin 13).
ASSISTANT_GPIO = 26

# Microphone device name. If "default" doesn't work, run `arecord -l` 
# to find your USB mic and use "plughw:1,0" for example.
MIC_DEVICE = "plughw:CARD=UACDemoV10,DEV=0"

# Maximum seconds to record if the button is not pressed again
MAX_RECORD_SECONDS = 7
