#!/usr/bin/env python3
"""
Button-triggered face recognition for Raspberry Pi 4B.

Button wiring:
    BCM GPIO17 / physical pin 11 -> push button -> GND / pin 9

Released = HIGH
Pressed  = LOW

Recognition runs only after an accepted button press.
"""

# Import config first so CPU-related environment settings are applied
# before NumPy and ONNX Runtime are imported.
import config as cfg

import queue
import signal
import sqlite3
import socket
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np

from insightface.utils import face_align

from config import (
    YUNET_MODEL,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
    YUNET_SCORE_THRESHOLD,
    YUNET_NMS_THRESHOLD,
    YUNET_TOP_K,
    THRESHOLD,
)

from face_database import (
    require_file,
    load_database,
    recognize_embedding,
)

from face_camera import (
    create_arcface,
    open_camera,
    capture_best_face,
)

from button_handler import ButtonHandler

from bluetooth_audio import (
    connect_bluetooth_audio,
    speak_text,
    warmup_tts,
)

from recognition_logger import RecognitionLogger

from person_info import PersonInfoStore

try:
    from oled_display import OLEDStatusDisplay
except Exception:
    OLEDStatusDisplay = None


# --------------------------- GLOBAL EVENTS ---------------------------

# Audio queue is retained. There is no button-event queue.
speech_queue = queue.Queue(maxsize=6)

stop_event = threading.Event()
scan_requested = threading.Event()


# ---------------------------- AUDIO ----------------------------------

def speech_worker():
    """Initialize audio and process speech announcements independently."""

    try:
        warmup_tts()

        connected = connect_bluetooth_audio()

        if connected:
            print("[AUDIO] Bluetooth ready.")
        else:
            print("[AUDIO] Bluetooth unavailable.")

    except Exception as exc:
        print(f"[AUDIO] Initialization warning: {exc}")

    while not stop_event.is_set():

        try:
            message = speech_queue.get(timeout=0.25)

        except queue.Empty:
            continue

        try:
            if message is None:
                return

            speak_text(message)

        except Exception as exc:
            print(f"[AUDIO] Speech failed: {exc}")

        finally:
            speech_queue.task_done()


def announce(message):
    """Print and queue a spoken announcement."""

    print(f"[VOICE] {message}")

    try:
        speech_queue.put_nowait(message)

    except queue.Full:
        print("[AUDIO] Speech queue full; announcement skipped.")


# -------------------------- SCHEDULER --------------------------------

def scheduler_worker():
    """Background thread that checks for scheduled messages in the DB."""
    db_path = cfg.DATABASE_PATH
    timeout = cfg.DB_BUSY_TIMEOUT_MS / 1000.0

    while not stop_event.is_set():
        # Interruptible sleep (checks every 15 seconds)
        if stop_event.wait(15):
            break

        # Verify internet connection to ensure system clock is synced
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)
        except OSError:
            print("[SCHEDULER] No internet connection. Waiting to sync time before executing tasks...")
            continue

        now_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        try:
            conn = sqlite3.connect(str(db_path), timeout=timeout)
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={cfg.DB_BUSY_TIMEOUT_MS}")

            # Find pending tasks that are due
            rows = conn.execute(
                "SELECT id, message FROM scheduled_messages "
                "WHERE status = 'PENDING' AND scheduled_time <= ? "
                "ORDER BY scheduled_time ASC",
                (now_utc,)
            ).fetchall()

            for row in rows:
                # Atomically claim the task so it doesn't double-play
                cur = conn.execute(
                    "UPDATE scheduled_messages SET status = 'COMPLETED', executed_at = ? "
                    "WHERE id = ? AND status = 'PENDING'",
                    (now_utc, row["id"])
                )
                conn.commit()

                if cur.rowcount > 0:
                    msg = row["message"]
                    print(f"[SCHEDULER] Executing task #{row['id']}: {msg}")
                    
                    # Play the message twice
                    announce(msg)
                    time.sleep(2)  # 2-second pause between plays
                    announce(msg)

            conn.close()

        except Exception as exc:
            print(f"[SCHEDULER] Error checking schedule: {exc}")


# ----------------------------- OLED ----------------------------------

def init_oled():
    """Initialize the optional OLED display."""

    if OLEDStatusDisplay is None:
        print("[OLED] Module unavailable; continuing without display.")
        return None

    try:
        display = OLEDStatusDisplay(
            port=1,
            address=0x3C,
        )

        display.set_status("LOADING MODELS")

        print("[OLED] Initialized.")

        return display

    except Exception as exc:
        print(
            "[OLED] Unavailable; continuing without display:",
            exc,
        )
        return None


def oled_status(display, status):
    """Update OLED status without stopping recognition if it fails."""

    if display is None:
        return

    try:
        display.set_status(status)

    except Exception as exc:
        print(f"[OLED] Update failed: {exc}")


# ------------------------- FACE RECOGNITION --------------------------

def process_scan(
    camera,
    yunet,
    arcface,
    db_embeddings,
    db_labels,
    display,
    recognition_logger=None,
    person_store=None,
):
    """Capture the best face, recognize it, and announce the result.

    Exactly one recognition event is logged per call. Logging failures are
    contained inside this function and never propagate to the caller.
    """

    oled_status(display, "SCANNING")

    started = time.monotonic()

    try:
        best = capture_best_face(
            camera,
            yunet,
        )

        if best is None:

            print("[RESULT] No usable face detected.")

            if recognition_logger is not None:
                try:
                    recognition_logger.log_no_face()
                except Exception as log_exc:
                    print(f"[LOGGER] log_no_face failed: {log_exc}")

            announce(
                "No face detected. Please face the camera and try again."
            )

            oled_status(
                display,
                "NO FACE - RETRY",
            )

            return

        _, frame, landmarks, detector_score = best

        # Align the detected face for ArcFace.
        aligned = face_align.norm_crop(
            img=frame,
            landmark=landmarks,
            image_size=112,
            mode="arcface",
        )

        # Generate the face embedding.
        embedding = np.asarray(
            arcface.get_feat(aligned),
            dtype=np.float32,
        ).reshape(-1)

        # Compare against the loaded embedding database.
        name, similarity = recognize_embedding(
            embedding,
            db_embeddings,
            db_labels,
        )

        elapsed = time.monotonic() - started

        print(
            "[TIMING] Capture + detection + recognition: "
            f"{elapsed:.2f}s"
        )

        print(
            f"[FACE] Detector confidence: {detector_score:.3f}"
        )

        if name != "UNKNOWN":

            spoken_name = name.replace("_", " ")

            print(
                f"[RESULT] {spoken_name} "
                f"(similarity {similarity:.3f})"
            )

            if recognition_logger is not None:
                try:
                    # Log the raw label (matches metadata_clean.csv 'person'
                    # column) so the events FK can resolve to people.id.
                    recognition_logger.log_known(name, similarity)
                except Exception as log_exc:
                    print(f"[LOGGER] log_known failed: {log_exc}")

            # Build the full announcement (relationship + message) if a
            # person profile is available; otherwise fall back to the
            # original name-only sentence.
            if person_store is not None:
                try:
                    announcement = person_store.build_announcement(name)
                except Exception as exc:
                    print(f"[CONTACTS] Build failed: {exc}")
                    announcement = f"{spoken_name} detected."
            else:
                announcement = f"{spoken_name} detected."

            announce(announcement)

            if display is not None:
                try:
                    display.show_result(
                        spoken_name,
                        similarity,
                        "KNOWN PERSON",
                    )

                except Exception as exc:
                    print(f"[OLED] Update failed: {exc}")

        else:

            print(
                f"[RESULT] UNKNOWN "
                f"(best similarity {similarity:.3f}; "
                f"threshold {THRESHOLD:.2f})"
            )

            if recognition_logger is not None:
                try:
                    # Reuse the already-computed aligned crop and embedding;
                    # do not re-run ArcFace or YuNet just to log the event.
                    recognition_logger.log_unknown(
                        similarity,
                        aligned,
                        embedding,
                    )
                except Exception as log_exc:
                    print(f"[LOGGER] log_unknown failed: {log_exc}")

            announce("I do not recognize this person")

            if display is not None:
                try:
                    display.show_result(
                        "UNKNOWN",
                        similarity,
                        "UNKNOWN PERSON",
                    )

                except Exception as exc:
                    print(f"[OLED] Update failed: {exc}")

    except Exception as exc:

        print(
            f"[RECOGNITION] Scan failed: "
            f"{type(exc).__name__}: {exc}"
        )

        if recognition_logger is not None:
            try:
                recognition_logger.log_error(
                    f"{type(exc).__name__}: {exc}"
                )
            except Exception as log_exc:
                print(f"[LOGGER] log_error failed: {log_exc}")

        announce(
            "Recognition failed. Please try again."
        )

        oled_status(
            display,
            "SCAN ERROR",
        )


# ------------------------------ MAIN ---------------------------------

def main():

    camera = None
    display = None
    speech_thread = None
    scheduler_thread = None
    button_handler = None
    recognition_logger = None
    person_store = None

    def stop_handler(signum, frame):
        stop_event.set()
        scan_requested.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        # Verify all required files before loading models.
        required_files = (
            cfg.YUNET_MODEL,
            cfg.ARCFACE_MODEL,
            cfg.EMBEDDINGS_FILE,
            cfg.METADATA_FILE,
        )

        for path in required_files:
            require_file(path)

        # Initialize the optional OLED.
        display = init_oled()

        oled_status(
            display,
            "LOADING DATABASE",
        )

        # Load and normalize the face database.
        db_embeddings, db_labels = load_database()

        # Initialize the event logger. A failure here must not stop
        # recognition: the logger's own methods are no-ops if the DB
        # layer is unavailable.
        try:
            recognition_logger = RecognitionLogger()
            print("[LOGGER] Recognition logger ready.")
        except Exception as exc:
            print(
                "[LOGGER] Init failed; continuing without "
                f"event logging: {exc}"
            )
            recognition_logger = None

        # Load person profiles (relationship + message) for spoken
        # announcements. A missing file or bad CSV is not fatal:
        # announcements fall back to "<Name> detected."
        try:
            person_store = PersonInfoStore(cfg.PERSON_INFO_FILE)
        except Exception as exc:
            print(
                "[CONTACTS] Init failed; only names will be spoken: "
                f"{exc}"
            )
            person_store = None

        # Initialize YuNet.
        print("[MODEL] Loading YuNet...")

        yunet = cv2.FaceDetectorYN.create(
            str(YUNET_MODEL),
            "",
            (CAMERA_WIDTH, CAMERA_HEIGHT),
            YUNET_SCORE_THRESHOLD,
            YUNET_NMS_THRESHOLD,
            YUNET_TOP_K,
        )

        # Initialize ArcFace.
        print("[MODEL] Loading ArcFace...")

        arcface = create_arcface()

        # Open and verify the camera.
        try:
            camera = open_camera()
        except Exception as exc:
            print(f"[CAMERA] Init failed: {exc}")
            print("[CAMERA] Continuing without camera. Scanning will be disabled.")
            camera = None

        # Start audio independently of recognition.
        speech_thread = threading.Thread(
            target=speech_worker,
            name="speech-worker",
            daemon=True,
        )

        speech_thread.start()

        # Start the background scheduler thread.
        scheduler_thread = threading.Thread(
            target=scheduler_worker,
            name="scheduler-worker",
            daemon=True,
        )
        scheduler_thread.start()
        print("[SCHEDULER] Background task thread active.")

        # Start the event-driven GPIO button handler.
        button_handler = ButtonHandler(
            stop_event=stop_event,
            scan_requested=scan_requested,
        )

        button_handler.start()

        oled_status(
            display,
            "READY - PRESS BTN",
        )

        print("[READY] Event-driven button listener active.")

        print(
            "[WIRING] BCM GPIO17 / physical pin 11 "
            "to button; other button side to GND / pin 9."
        )

        print(
            "[READY] Tap once to scan. "
            "Further presses are ignored during a scan "
            "and for 5 seconds after an accepted press."
        )

        # Wait efficiently for button-triggered scans.
        while not stop_event.is_set():

            if not scan_requested.wait(timeout=0.5):
                continue

            scan_requested.clear()

            if stop_event.is_set():
                break

            if camera is None:
                print("[BUTTON] Camera unavailable; cannot scan.")
                announce("Camera is not connected.")
                button_handler.finish_scan()
                continue

            print("[BUTTON] Press accepted. Starting scan.")

            try:
                process_scan(
                    camera,
                    yunet,
                    arcface,
                    db_embeddings,
                    db_labels,
                    display,
                    recognition_logger=recognition_logger,
                    person_store=person_store,
                )

            finally:
                # Always release the scan lock, including after errors.
                oled_status(
                    display,
                    "READY - PRESS BTN",
                )

                button_handler.finish_scan()

                print(
                    "[BUTTON] Scan finished. "
                    "Wait for the remaining cooldown before "
                    "the next accepted scan."
                )

    except KeyboardInterrupt:
        stop_event.set()
        print("\n[STOP] Shutting down.")

    except Exception as exc:
        print(
            f"[FATAL] {type(exc).__name__}: {exc}"
        )
        raise

    finally:
        stop_event.set()
        scan_requested.set()

        # Release GPIO resources.
        if button_handler is not None:
            button_handler.close()

        # Release camera.
        if camera is not None:
            camera.release()

        # Stop the audio worker.
        if speech_thread is not None and speech_thread.is_alive():

            try:
                speech_queue.put_nowait(None)

            except queue.Full:
                pass

            speech_thread.join(timeout=1.0)

        # Release OLED resources.
        if display is not None:
            try:
                display.close()

            except Exception:
                pass

        cv2.destroyAllWindows()

        print("[STOP] Resources released.")


if __name__ == "__main__":
    main()
