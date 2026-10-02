"""
scheduler.py — Runs the pipeline on a repeating interval using threading.Timer.

The first run is immediate; subsequent runs fire every `interval_hours` hours.
A threading.Event is used for clean shutdown on Ctrl-C.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class Scheduler:
    """Repeating timer that calls `job` every `interval_seconds` seconds."""

    def __init__(self, job: Callable[[], None], interval_seconds: float):
        self._job = job
        self._interval = interval_seconds
        self._stop_event = threading.Event()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Run the job immediately, then schedule it to repeat."""
        logger.info("[scheduler] Starting — interval %.0fs (%.2fh)",
                    self._interval, self._interval / 3600)
        self._run_and_schedule()

    def stop(self) -> None:
        """Signal the scheduler to stop after the current run finishes."""
        logger.info("[scheduler] Stop requested.")
        self._stop_event.set()
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def wait(self) -> None:
        """Block until stop() is called."""
        self._stop_event.wait()

    # ── Internal ──────────────────────────────────────────────────────────

    def _run_and_schedule(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._job()
        except Exception as exc:
            logger.error("[scheduler] Job raised an unhandled exception: %s", exc, exc_info=True)
        if not self._stop_event.is_set():
            with self._lock:
                self._timer = threading.Timer(self._interval, self._run_and_schedule)
                self._timer.daemon = True
                self._timer.start()
            logger.info("[scheduler] Next run in %.0f seconds.", self._interval)
