"""Rate-limit login in-memory (DECISIONS D13)."""

from __future__ import annotations

import threading
from collections import defaultdict, deque

from core.timeutil import Clock


class LoginRateLimiter:
    def __init__(self, clock: Clock, per_ip: tuple[int, int] = (5, 60), per_user: tuple[int, int] = (20, 900)):
        self.clock = clock
        self.per_ip = per_ip
        self.per_user = per_user
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: int, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def retry_after(self, username: str, ip: str) -> int:
        """0 jika boleh mencoba; selain itu detik sampai boleh mencoba lagi."""
        now = self.clock().timestamp()
        u = username.strip().lower()
        with self._lock:
            waits = []
            for key, (limit, window) in ((f"ip:{u}|{ip}", self.per_ip), (f"u:{u}", self.per_user)):
                q = self._prune(key, window, now)
                if len(q) >= limit:
                    waits.append(int(window - (now - q[0])) + 1)
            return max(waits, default=0)

    def fail(self, username: str, ip: str) -> None:
        now = self.clock().timestamp()
        u = username.strip().lower()
        with self._lock:
            self._fails[f"ip:{u}|{ip}"].append(now)
            self._fails[f"u:{u}"].append(now)

    def success(self, username: str, ip: str) -> None:
        u = username.strip().lower()
        with self._lock:
            self._fails.pop(f"ip:{u}|{ip}", None)
