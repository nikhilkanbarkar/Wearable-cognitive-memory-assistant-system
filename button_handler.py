
#!/usr/bin/env python3

import threading
import time

import lgpio

from config import (
    GPIO_CHIP,
    BUTTON_GPIO,
    DEBOUNCE_SECONDS,
    BUTTON_COOLDOWN_SECONDS,
)


class ButtonHandler:
    """Event-driven GPIO button handler using lgpio."""

    def __init__(self, stop_event, scan_requested):
        self.stop_event = stop_event
        self.scan_requested = scan_requested

        self.gpio_handle = None
        self.gpio_callback = None

        self.button_lock = threading.Lock()
        self.scan_in_progress = False
        self.last_accepted_press = None
        self.debounce_timer = None
        self.closed = False

    def _on_gpio_edge(self, chip, gpio, level, timestamp):
        """Request one scan when the button is pressed."""
        if self.stop_event.is_set():
            return

        with self.button_lock:
            if self.closed:
                return

            if self.debounce_timer is not None:
                self.debounce_timer.cancel()
                self.debounce_timer = None

            # LOW means pressed. Confirm it remains low after contact bounce.
            if level == 0:
                timer = threading.Timer(
                    DEBOUNCE_SECONDS,
                    lambda: self._confirm_press(timer),
                )
                self.debounce_timer = timer
                timer.daemon = True
                timer.start()

    def _confirm_press(self, timer):
        with self.button_lock:
            if self.closed or self.debounce_timer is not timer:
                return

            self.debounce_timer = None

            if self.stop_event.is_set() or self.gpio_handle is None:
                return

            try:
                if lgpio.gpio_read(self.gpio_handle, BUTTON_GPIO) != 0:
                    return
            except Exception as exc:
                print(f"[BUTTON] Could not confirm press: {exc}")
                return

            now = time.monotonic()

            if self.scan_in_progress:
                return

            if (
                self.last_accepted_press is not None
                and now - self.last_accepted_press < BUTTON_COOLDOWN_SECONDS
            ):
                return

            self.scan_in_progress = True
            self.last_accepted_press = now

        self.scan_requested.set()

    def start(self):
        """Initialize GPIO and register the edge callback."""

        if self.gpio_handle is not None:
            return

        try:
            self.gpio_handle = lgpio.gpiochip_open(GPIO_CHIP)

            lgpio.gpio_claim_alert(
                self.gpio_handle,
                BUTTON_GPIO,
                lgpio.BOTH_EDGES,
                lgpio.SET_PULL_UP,
            )

            self.gpio_callback = lgpio.callback(
                self.gpio_handle,
                BUTTON_GPIO,
                lgpio.BOTH_EDGES,
                self._on_gpio_edge,
            )

            print(
                f"[BUTTON] Ready on GPIO{BUTTON_GPIO}. "
                "Press the button to start recognition."
            )

        except Exception:
            self.close()
            raise

    def finish_scan(self):
        """Allow another scan after the current scan finishes."""

        with self.button_lock:
            self.scan_in_progress = False

    def close(self):
        """Release the callback and GPIO chip handle."""

        with self.button_lock:
            self.closed = True
            timer = self.debounce_timer
            self.debounce_timer = None
            callback = self.gpio_callback
            self.gpio_callback = None
            handle = self.gpio_handle
            self.gpio_handle = None

        if timer is not None:
            timer.cancel()

        if callback is not None:
            try:
                callback.cancel()
            except Exception:
                pass

        if handle is not None:
            try:
                lgpio.gpiochip_close(handle)
            except Exception:
                pass
