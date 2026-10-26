#!/usr/bin/env python3
"""Low-overhead SH1106 OLED status display for the cognitive assistant."""

from threading import Lock

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106


class OLEDStatusDisplay:
    """Display system status and retain the most recent recognition result."""

    def __init__(self, port=1, address=0x3C):
        serial = i2c(port=port, address=address)
        self.device = sh1106(serial, width=128, height=64, rotate=0)
        self.lock = Lock()
        self.last_person = "--"
        self.last_score = None
        self.status = "STARTING"
        self._render()

    @staticmethod
    def _short(text, max_len=19):
        text = str(text).replace("\n", " ").strip()
        return text if len(text) <= max_len else text[:max_len - 3] + "..."

    def _render(self):
        with canvas(self.device) as draw:
            draw.rectangle((0, 0, 127, 63), outline="white", fill="black")
            draw.text((4, 3), "COGNITIVE ASSIST", fill="white")
            draw.line((3, 14, 124, 14), fill="white")
            draw.text((4, 18), "STATUS: " + self._short(self.status, 13), fill="white")
            draw.text((4, 32), "LAST PERSON:", fill="white")
            draw.text((4, 44), self._short(self.last_person, 19), fill="white")
            if self.last_score is not None:
                draw.text((4, 54), f"Similarity: {self.last_score:.2f}", fill="white")
            else:
                draw.text((4, 54), "Press button to scan", fill="white")

    def set_status(self, status):
        with self.lock:
            self.status = str(status)
            self._render()

    def show_result(self, person, score=None, status="READY"):
        """Replace the retained result for known and UNKNOWN recognition results."""
        with self.lock:
            self.last_person = str(person).replace("_", " ")
            self.last_score = float(score) if score is not None else None
            self.status = str(status)
            self._render()

    def close(self):
        with self.lock:
            try:
                self.device.clear()
            finally:
                self.device.cleanup()
