from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from core.attendance import AttendanceService
from core.models import Rate, User
from core.repo.memory import InMemoryRepository
from core.timeutil import wib_to_utc

MADRASAH = (-6.200000, 106.816666)
QR_KEY = "test-qr-master-key"
JWT_SECRET = "test-jwt-secret-yang-cukup-panjang-untuk-hs256"


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set_wib(self, d: date, hhmm: str, seconds: int = 0) -> None:
        self.now = wib_to_utc(d, hhmm) + timedelta(seconds=seconds)

    def advance(self, **kw) -> None:
        self.now = self.now + timedelta(**kw)


TODAY = date(2026, 11, 13)


@pytest.fixture
def clock() -> FakeClock:
    c = FakeClock(datetime(2026, 11, 13, 6, 0, tzinfo=UTC))
    c.set_wib(TODAY, "13:20")
    return c


@pytest.fixture
def repo():
    r = InMemoryRepository()
    s = r.settings.get()
    r.settings.save(s.model_copy(update={"lat": MADRASAH[0], "lng": MADRASAH[1], "madrasah_name": "MDA Test"}))
    return r


def make_user(repo, name="Guru A", role="guru", rate: int | None = 50000,
              effective_from: date = date(2026, 1, 1)) -> User:
    u = User(
        user_id=str(uuid.uuid4()),
        username=name.lower().replace(" ", ""),
        name=name,
        role=role,
        pin_hash="x",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    repo.users.create(u)
    if rate is not None:
        repo.rates.add(Rate(user_id=u.user_id, rate_per_meeting=rate, effective_from=effective_from,
                            set_by="admin", set_at=datetime(2026, 1, 1, tzinfo=UTC)))
    return u


@pytest.fixture
def admin(repo) -> User:
    return make_user(repo, "Admin", role="admin", rate=None)


@pytest.fixture
def guru(repo) -> User:
    return make_user(repo, "Guru A")


@pytest.fixture
def svc(repo, clock) -> AttendanceService:
    return AttendanceService(repo, clock, QR_KEY, JWT_SECRET)


def pos_now(clock: FakeClock) -> float:
    return clock().timestamp() * 1000
