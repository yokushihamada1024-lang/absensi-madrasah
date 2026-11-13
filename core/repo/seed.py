"""Data default (setara bootstrap)."""

from __future__ import annotations

from core.models import NamedItem
from core.repo.base import DEFAULT_KELAS, DEFAULT_MAPEL, DEFAULT_SESSION_DEFS, Repository


def seed_defaults(repo: Repository) -> None:
    """Isi default kelas, mapel, jam sesi (dipakai scripts.migrate & mode dev)."""
    if not repo.meta.list_session_defs():
        repo.meta.save_session_defs(DEFAULT_SESSION_DEFS)
    if not repo.meta.list_items("kelas"):
        repo.meta.save_items("kelas", [NamedItem(name=n) for n in DEFAULT_KELAS])
    if not repo.meta.list_items("mapel"):
        repo.meta.save_items("mapel", [NamedItem(name=n) for n in DEFAULT_MAPEL])
    repo.settings.save(repo.settings.get())
