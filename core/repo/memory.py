"""InMemoryRepository — untuk test & mode dev. Thread-safe."""

from __future__ import annotations

import threading

from core.repo.base import SCHEMA, Repository
from core.repo.seed import seed_defaults
from core.repo.tables import Row, TableBackend, build_repository, to_row


class MemoryBackend(TableBackend):
    def __init__(self) -> None:
        self._tabs: dict[str, list[dict[str, str]]] = {t: [] for t in SCHEMA}
        self._lock = threading.RLock()

    def rows(self, tab: str, fresh: bool = False) -> list[Row]:
        with self._lock:
            return [(i + 2, dict(r)) for i, r in enumerate(self._tabs[tab])]

    def write_lock(self) -> threading.RLock:
        return self._lock

    def append(self, tab: str, values: dict[str, str]) -> int:
        with self._lock:
            row = {c: values.get(c, "") for c in SCHEMA[tab]}
            self._tabs[tab].append(row)
            return len(self._tabs[tab]) + 1

    def update(self, tab: str, rownum: int, values: dict[str, str], key_col: str) -> None:
        with self._lock:
            idx = rownum - 2
            cur = self._tabs[tab][idx]
            if cur.get(key_col) != values.get(key_col):
                raise RuntimeError(f"{tab} baris {rownum}: kunci berubah, update dibatalkan")
            self._tabs[tab][idx] = {c: values.get(c, "") for c in SCHEMA[tab]}


def InMemoryRepository(seed: bool = True) -> Repository:  # noqa: N802 — nama sesuai spesifikasi
    repo = build_repository(MemoryBackend())
    if seed:
        seed_defaults(repo)
    return repo


__all__ = ["InMemoryRepository", "MemoryBackend", "seed_defaults", "to_row"]
