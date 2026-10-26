#!/usr/bin/env python3

import time

import cv2
import numpy as np
import onnxruntime as ort

from insightface.model_zoo.arcface_onnx import ArcFaceONNX

from config import (
    ARCFACE_MODEL,
    ORT_INTRA_OP_THREADS,
    ORT_INTER_OP_THREADS,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    CAMERA_HEIGHT,
    CAPTURE_SECONDS,
    DETECT_EVERY_N_FRAMES,
    MIN_FACE_SIZE,
)


def create_arcface():
    """Create ArcFace with bounded ONNX Runtime CPU settings."""

    options = ort.SessionOptions()

    options.intra_op_num_threads = ORT_INTRA_OP_THREADS
    options.inter_op_num_threads = ORT_INTER_OP_THREADS

    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    options.graph_optimization_level = (
        ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    )

    options.log_severity_level = 3

    try:
        options.add_session_config_entry(
            "session.intra_op.allow_spinning",
            "0",
        )
        options.add_session_config_entry(
            "session.inter_op.allow_spinning",
            "0",
        )
    except Exception:
        pass

    session = ort.InferenceSession(
        str(ARCFACE_MODEL),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )

    model = ArcFaceONNX(
        model_file=str(ARCFACE_MODEL),
        session=session,
    )

    model.prepare(ctx_id=-1)

    print(
        "[MODEL] ArcFace ready:",
        f"provider={session.get_providers()[0]},",
        f"intra_op_threads={ORT_INTRA_OP_THREADS},",
        f"inter_op_threads={ORT_INTER_OP_THREADS}",
    )

    return model


def open_camera():
    camera = cv2.VideoCapture(
        CAMERA_INDEX,
        cv2.CAP_V4L2,
    )

    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        raise RuntimeError(
            "Cannot open camera. Check camera connection and CAMERA_INDEX."
        )

    camera.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        CAMERA_WIDTH,
    )

    camera.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        CAMERA_HEIGHT,
    )

    camera.set(
        cv2.CAP_PROP_BUFFERSIZE,
        1,
    )

    camera.set(
        cv2.CAP_PROP_FPS,
        15,
    )

    ok, frame = camera.read()

    if not ok or frame is None:
        camera.release()
        raise RuntimeError(
            "Camera opened but did not return a frame."
        )

    print(
        f"[CAMERA] Ready at "
        f"{frame.shape[1]}x{frame.shape[0]}."
    )

    return camera


def capture_best_face(camera, yunet):
    """Capture briefly and retain the best detected face."""

    best = None

    checked = 0
    detection_runs = 0

    deadline = time.monotonic() + CAPTURE_SECONDS

    while time.monotonic() < deadline:

        ok, frame = camera.read()

        if not ok or frame is None:
            time.sleep(0.01)
            continue

        checked += 1

        if checked % DETECT_EVERY_N_FRAMES:
            continue

        height, width = frame.shape[:2]

        yunet.setInputSize((width, height))

        _, detections = yunet.detect(frame)

        detection_runs += 1

        if detections is None or len(detections) == 0:
            continue

        for det in detections:

            x, y, face_w, face_h = map(
                float,
                det[:4],
            )

            x1 = max(0, int(x))
            y1 = max(0, int(y))

            x2 = min(width, int(x + face_w))
            y2 = min(height, int(y + face_h))

            actual_w = x2 - x1
            actual_h = y2 - y1

            if (
                actual_w < MIN_FACE_SIZE
                or actual_h < MIN_FACE_SIZE
            ):
                continue

            detector_score = (
                float(det[14])
                if len(det) > 14
                else 0.5
            )

            quality = (
                float(actual_w * actual_h)
                * detector_score
            )

            if best is None or quality > best[0]:

                landmarks = (
                    det[4:14]
                    .reshape(5, 2)
                    .astype(np.float32)
                    .copy()
                )

                best = (
                    quality,
                    frame.copy(),
                    landmarks,
                    detector_score,
                )

    print(
        f"[CAPTURE] Read {checked} frames; "
        f"ran detector {detection_runs} times."
    )

    return best