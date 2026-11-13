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


PG_TABLES = ["audit_log", "payslips", "attempts", "attendance", "session_instances", "rates", "users",
             "kelas", "mapel", "session_defs", "settings"]


@pytest.fixture(scope="session")
def pg_db():
    """Postgres sungguhan untuk test: TEST_DATABASE_URL, atau Postgres lokal sementara via pgserver.

    Tidak butuh internet. Jika keduanya tidak tersedia, test backend Postgres di-skip.
    """
    import os
    import tempfile

    from core.repo.postgres import Database

    dsn = os.environ.get("TEST_DATABASE_URL", "").strip()
    server = None
    if not dsn:
        try:
            import pgserver
        except ImportError:
            pytest.skip("pgserver tidak terpasang dan TEST_DATABASE_URL kosong")
        server = pgserver.get_server(tempfile.mkdtemp(prefix="absensi-pg-"), cleanup_mode="delete")
        dsn = server.get_uri()
    db = Database(dsn, max_size=4)
    db.migrate()
    db.migrate()  # idempoten
    yield db
    db.close()
    if server is not None:
        server.cleanup()


@pytest.fixture(params=["memory", "postgres"])
def repo(request):
    if request.param == "memory":
        r = InMemoryRepository()
    else:
        from core.repo.postgres import PostgresRepository
        from core.repo.seed import seed_defaults

        db = request.getfixturevalue("pg_db")
        db.run("truncate " + ", ".join(f"absensi.{t}" for t in PG_TABLES) + " restart identity cascade")
        r = PostgresRepository(db=db)
        seed_defaults(r)
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
