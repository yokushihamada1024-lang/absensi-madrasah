"""Data demo untuk mode dev (ENV=dev, REPO_BACKEND=memory). JANGAN dipakai di produksi.

Akun demo (PIN semua: 123456):
  admin  — Admin Demo
  guru1..guru5 — Guru Satu..Lima (tarif Rp 50.000–90.000)
Titik madrasah demo: Monas, Jakarta (-6.175392, 106.827153), radius 100 m.
"""

from __future__ import annotations

import uuid
from datetime import date

from core.models import Rate, User
from core.repo.base import Repository
from core.security import hash_pin
from core.timeutil import system_clock

DEMO_PIN = "123456"
DEMO_LAT, DEMO_LNG = -6.175392, 106.827153
NAMES = ["Satu", "Dua", "Tiga", "Empat", "Lima"]


def seed_demo(repo: Repository) -> None:
    if repo.users.list():
        return
    now = system_clock()
    pin_hash = hash_pin(DEMO_PIN)
    repo.settings.save(repo.settings.get().model_copy(
        update={"madrasah_name": "Madrasah Demo", "lat": DEMO_LAT, "lng": DEMO_LNG}))
    admin = User(user_id=str(uuid.uuid4()), username="admin", name="Admin Demo", role="admin",
                 pin_hash=pin_hash, created_at=now)
    repo.users.create(admin)
    for i, n in enumerate(NAMES, start=1):
        u = User(user_id=str(uuid.uuid4()), username=f"guru{i}", name=f"Guru {n}", role="guru",
                 pin_hash=pin_hash, created_at=now)
        repo.users.create(u)
        repo.rates.add(Rate(user_id=u.user_id, rate_per_meeting=40000 + i * 10000,
                            effective_from=date(2020, 1, 1), set_by=admin.user_id, set_at=now))
