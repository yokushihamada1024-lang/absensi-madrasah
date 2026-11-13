"""InMemoryRepository — untuk test & mode dev. Thread-safe."""

from __future__ import annotations

import threading

from core.models import NamedItem
from core.repo.base import DEFAULT_KELAS, DEFAULT_MAPEL, DEFAULT_SESSION_DEFS, SCHEMA, Repository
from core.repo.tables import Row, TableBackend, build_repository, to_row


class MemoryBackend(TableBackend):
    def __init__(self) -> None:
        self._tabs: dict[str, list[dict[str, str]]] = {t: [] for t in SCHEMA}
        self._lock = threading.RLock()

    def rows(self, tab: str, fresh: bool = False) -> list[Row]:
        with self._lock:
            return [(i + 2, dict(r)) for i, r in enumerate(self._tabs[tab])]

    def tail(self, tab: str, n: int) -> list[Row]:
        return self.rows(tab)[-n:]

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


def seed_defaults(repo: Repository) -> None:
    """Isi default kelas, mapel, jam sesi (setara bootstrap_sheets)."""
    if not repo.meta.list_session_defs():
        repo.meta.save_session_defs(DEFAULT_SESSION_DEFS)
    if not repo.meta.list_items("kelas"):
        repo.meta.save_items("kelas", [NamedItem(name=n) for n in DEFAULT_KELAS])
    if not repo.meta.list_items("mapel"):
        repo.meta.save_items("mapel", [NamedItem(name=n) for n in DEFAULT_MAPEL])
    repo.settings.save(repo.settings.get())


def InMemoryRepository(seed: bool = True) -> Repository:  # noqa: N802 — nama sesuai spesifikasi
    repo = build_repository(MemoryBackend())
    if seed:
        seed_defaults(repo)
    return repo


__all__ = ["InMemoryRepository", "MemoryBackend", "seed_defaults", "to_row"]
