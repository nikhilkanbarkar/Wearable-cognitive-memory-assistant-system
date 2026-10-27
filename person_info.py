#!/usr/bin/env python3
"""Person profile loader for voice announcements.

Maps each registered person's label (from Embeddings/metadata_clean.csv)
to a relationship, pronoun, and custom message that is spoken aloud after
recognition.

The CSV is reloaded automatically when its mtime changes, so caregivers
can edit relationships/messages without restarting the recognition service.

CSV format (UTF-8, with or without BOM):

    person_name,relationship,pronoun,message
    Nikhil_Kanbarkar,brother,he,He is your primary emergency contact.
    Priya_Sharma,daughter,she,She visits every Sunday.
    Alice,friend,they,Alice is your college friend.

Field meanings:

- person_name : exact label from Embeddings/metadata_clean.csv
                (e.g. "Nikhil_Kanbarkar", not "Nikhil Kanbarkar")
- relationship: free text, e.g. "brother", "daughter", "primary caregiver"
- pronoun     : "he", "she", "they", or blank (blank = neutral form)
- message     : any free-form text; spoken after "Message is: ..."

Nothing in this file is loaded by the web dashboard. It is used only by
face_recognition.py when constructing spoken announcements.
"""

import csv
import sys
from pathlib import Path
from typing import Optional


class PersonInfoStore:
    """Loads person profiles from a CSV file.

    Thread-safety note: this class is intentionally lock-free because it
    is only called from the single recognition thread (process_scan is
    invoked once per button press by the main loop).
    """

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        self._cache: dict = {}
        self._mtime: Optional[float] = None
        self._reload_if_needed()

    # ------------------------------------------------------------ loading

    def _read_csv(self) -> dict:
        if not self.csv_path.is_file():
            print(
                f"[CONTACTS] {self.csv_path} not found; only names will be spoken.",
                file=sys.stderr,
            )
            return {}

        result: dict = {}
        try:
            with self.csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or "person_name" not in reader.fieldnames:
                    print(
                        f"[CONTACTS] {self.csv_path} is missing 'person_name' "
                        "column; only names will be spoken.",
                        file=sys.stderr,
                    )
                    return {}
                for row in reader:
                    name = (row.get("person_name") or "").strip()
                    if not name:
                        continue
                    pronoun = (row.get("pronoun") or "").strip().lower()
                    if pronoun not in ("he", "she", "they"):
                        pronoun = ""
                    result[name] = {
                        "relationship": (row.get("relationship") or "").strip(),
                        "pronoun": pronoun,
                        "message": (row.get("message") or "").strip(),
                    }
        except (OSError, csv.Error) as exc:
            print(
                f"[CONTACTS] Failed to read {self.csv_path}: {exc}",
                file=sys.stderr,
            )
            return {}

        return result

    def _reload_if_needed(self) -> None:
        try:
            mtime = self.csv_path.stat().st_mtime
        except FileNotFoundError:
            mtime = None

        if self._mtime == mtime:
            return

        self._cache = self._read_csv()
        self._mtime = mtime
        print(f"[CONTACTS] Loaded {len(self._cache)} person profile(s).")

    # ----------------------------------------------------------- accessors

    def get(self, name: str) -> Optional[dict]:
        """Return the profile dict for a person, or None if not found."""
        self._reload_if_needed()
        return self._cache.get(name)

    def build_announcement(self, name: str) -> str:
        """Build the full spoken sentence for a recognized person.

        Examples of the resulting sentence:

        - pronoun=he,  relationship=brother  -> "He is Nikhil Kanbarkar.
                                                 He is your brother.
                                                 Message is: ..."
        - pronoun=she, relationship=daughter -> "She is Priya Sharma.
                                                 She is your daughter.
                                                 Message is: ..."
        - pronoun=they                       -> "They are Alice.
                                                 They are your friend.
                                                 Message is: ..."
        - no pronoun,    relationship=friend -> "Alice, your friend.
                                                 Message is: ..."
        - nothing filled in                  -> "Alice detected."
        """
        self._reload_if_needed()
        spoken_name = name.replace("_", " ")

        info = self._cache.get(name)
        if not info:
            return f"{spoken_name} detected."

        relationship = info["relationship"]
        pronoun = info["pronoun"]
        message = info["message"]

        parts = []

        if pronoun in ("he", "she"):
            p = pronoun.capitalize()
            parts.append(f"{p} is {spoken_name}.")
            if relationship:
                parts.append(f"{p} is your {relationship}.")
        elif pronoun == "they":
            parts.append(f"They are {spoken_name}.")
            if relationship:
                parts.append(f"They are your {relationship}.")
        elif relationship:
            parts.append(f"{spoken_name}, your {relationship}.")
        elif message:
            parts.append(f"{spoken_name}.")
        else:
            return f"{spoken_name} detected."

        if message:
            parts.append(f"Message is: {message}")

        return " ".join(parts)
