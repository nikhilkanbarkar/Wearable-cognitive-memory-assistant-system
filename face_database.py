#!/usr/bin/env python3

import csv
from pathlib import Path

import numpy as np

from config import (
    EMBEDDINGS_FILE,
    METADATA_FILE,
    THRESHOLD,
)


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Required file not found: {path}")


def load_database():
    require_file(EMBEDDINGS_FILE)
    require_file(METADATA_FILE)

    embeddings = np.asarray(
        np.load(EMBEDDINGS_FILE, allow_pickle=False),
        dtype=np.float32,
    )

    with METADATA_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames or "person" not in reader.fieldnames:
            raise ValueError(
                "metadata_clean.csv must contain a 'person' column."
            )

        labels = np.asarray(
            [str(row["person"]).strip() for row in reader],
            dtype=str,
        )

    if embeddings.ndim != 2 or embeddings.shape[1] != 512:
        raise ValueError(
            f"Expected embeddings with shape (N, 512), "
            f"got {embeddings.shape}"
        )

    if len(embeddings) != len(labels):
        raise ValueError(
            f"Embedding/metadata row mismatch: "
            f"{len(embeddings)} vs {len(labels)}"
        )

    if len(labels) == 0:
        raise ValueError("The embedding database is empty.")

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, 1e-10)

    print(
        f"[DB] Loaded {len(labels)} embeddings "
        f"for {len(set(labels.tolist()))} people."
    )

    return embeddings, labels


def recognize_embedding(embedding, db_embeddings, db_labels):
    embedding = np.asarray(
        embedding,
        dtype=np.float32,
    ).reshape(-1)

    norm = float(np.linalg.norm(embedding))

    if norm < 1e-10:
        return "UNKNOWN", 0.0

    similarities = db_embeddings @ (embedding / norm)

    index = int(np.argmax(similarities))
    score = float(similarities[index])

    if score >= THRESHOLD:
        return str(db_labels[index]), score

    return "UNKNOWN", score