"""Slows down guessing. A manager password, a 4-digit staff PIN or a 6-digit pairing code can be tried many times a
minute by a script, so after a few wrong tries the same account (or device) is locked for a while, even when a later
try is right.

The key names the account and where the tries come from (account + address), so a stranger guessing the manager's
password from one address locks out that address, not the manager.

Kept in memory: it resets when the app restarts, and it is per process. That is enough for one store's server; with
several processes it would move to the database."""
import threading
import time

from fastapi import HTTPException

MAX_FAILS = 5
WINDOW_SECONDS = 15 * 60  # failures older than this are forgotten, and a lock lasts this long


class Throttle:
    def __init__(self, max_fails: int = MAX_FAILS, window: float = WINDOW_SECONDS, clock=time.monotonic):
        self.max_fails, self.window, self.clock = max_fails, window, clock
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = self.clock() - self.window
        fails = [t for t in self._fails.get(key, []) if t > cutoff]
        if fails:
            self._fails[key] = fails
        else:
            self._fails.pop(key, None)
        return fails

    def check(self, key: str) -> None:
        """Raises 429 with the minutes left while `key` is locked."""
        with self._lock:
            fails = self._recent(key)
            if len(fails) >= self.max_fails:
                wait = max(1, round((fails[0] + self.window - self.clock()) / 60))
                raise HTTPException(429, f"Too many wrong tries. Try again in {wait} minute{'s' if wait != 1 else ''}.")

    def fail(self, key: str) -> None:
        with self._lock:
            self._recent(key)
            self._fails.setdefault(key, []).append(self.clock())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
