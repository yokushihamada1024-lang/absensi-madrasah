"""PostgresRepository — produksi di Supabase (free tier, lewat session pooler).

- psycopg 3 + ConnectionPool kecil (max 4): kuota koneksi pooler free tier terbatas.
- prepare_threshold=None: aman juga jika nanti dipindah ke transaction pooler (port 6543).
- Pool dibuka malas (saat query pertama) agar /healthz & start-up tidak menyentuh database.
- check_connection saat checkout: koneksi yang diputus pooler selama API tidur diganti otomatis.
- Keunikan absensi dijamin partial unique index (db/schema.sql), bukan oleh kode.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from core.models import (
    AppError,
    Attempt,
    Attendance,
    AuditEntry,
    NamedItem,
    Payslip,
    Rate,
    SessionDef,
    SessionInstance,
    Settings,
    User,
)
from core.repo.base import (
    AttemptRepo,
    AttendanceFilter,
    AttendanceRepo,
    AuditRepo,
    DuplicateAttendanceError,
    MetaRepo,
    PayslipRepo,
    RateRepo,
    Repository,
    SessionRepo,
    SettingsRepo,
    UserRepo,
)
from core.repo.tables import from_row, to_row

M = TypeVar("M", bound=BaseModel)
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
S = "absensi"


def _model(cls: type[M], row: dict[str, Any]) -> M:
    """Baris DB → model. None pada kolom string non-opsional → pakai default."""
    data = {}
    for k, v in row.items():
        if k not in cls.model_fields:
            continue
        if v is None and not _nullable(cls, k):
            continue
        data[k] = v
    return cls.model_validate(data)


def _nullable(cls: type[BaseModel], name: str) -> bool:
    f = cls.model_fields[name]
    return f.annotation is not None and "None" in str(f.annotation)


def _cols(cls: type[BaseModel], exclude: tuple[str, ...] = ()) -> list[str]:
    return [c for c in cls.model_fields if c not in exclude]


class Database:
    def __init__(self, dsn: str, max_size: int = 4) -> None:
        self._dsn = dsn
        self._max_size = max_size
        self._pool = self._new_pool()
        self._opened = False
        self._open_lock = threading.Lock()

    def _new_pool(self) -> Any:
        from psycopg_pool import ConnectionPool

        return ConnectionPool(
            self._dsn,
            min_size=1,
            max_size=self._max_size,
            open=False,
            timeout=30,
            max_idle=120,
            check=ConnectionPool.check_connection,
            kwargs={"prepare_threshold": None, "autocommit": True},
            name="absensi",
        )

    def _ensure_open(self) -> None:
        if not self._opened:
            with self._open_lock:
                if not self._opened:
                    from psycopg_pool import PoolTimeout

                    try:
                        self._pool.open(wait=True, timeout=45)
                    except PoolTimeout:
                        # Hentikan percobaan di latar belakang: login gagal berulang (mis. password salah)
                        # membuat pooler Supabase memblokir sementara (circuit breaker). Coba lagi di request
                        # berikutnya dengan pool baru.
                        self._pool.close()
                        self._pool = self._new_pool()
                        raise AppError("DB_UNAVAILABLE", "Database tidak bisa dihubungi. Coba lagi sebentar lagi.",
                                       500) from None
                    self._opened = True

    @contextmanager
    def conn(self) -> Iterator[Any]:
        from psycopg.rows import dict_row

        self._ensure_open()
        with self._pool.connection() as c:
            c.row_factory = dict_row
            yield c

    @contextmanager
    def tx(self) -> Iterator[Any]:
        with self.conn() as c, c.transaction():
            yield c

    def all(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn() as c:
            return c.execute(sql, params).fetchall()

    def one(self, sql: str, params: Any = ()) -> dict[str, Any] | None:
        with self.conn() as c:
            return c.execute(sql, params).fetchone()

    def run(self, sql: str, params: Any = ()) -> int:
        with self.conn() as c:
            return c.execute(sql, params).rowcount

    def migrate(self) -> None:
        with self.tx() as c:
            c.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    def close(self) -> None:
        if self._opened:
            self._pool.close()
            self._opened = False


def _insert_sql(table: str, cols: list[str], conflict: str = "") -> str:
    return (f"insert into {S}.{table} ({', '.join(cols)}) values ({', '.join('%s' for _ in cols)}) {conflict}")


class _R:
    def __init__(self, db: Database) -> None:
        self.db = db


class PgSettingsRepo(_R, SettingsRepo):
    def get(self) -> Settings:
        kv = {r["key"]: r["value"] for r in self.db.all(f"select key, value from {S}.settings")}
        return from_row(Settings, kv)

    def save(self, settings: Settings) -> None:
        with self.db.tx() as c:
            for k, v in to_row(settings).items():
                c.execute(
                    f"insert into {S}.settings (key, value) values (%s, %s) "
                    "on conflict (key) do update set value = excluded.value",
                    (k, v),
                )


class PgMetaRepo(_R, MetaRepo):
    def list_items(self, kind: str) -> list[NamedItem]:
        assert kind in ("kelas", "mapel")
        rows = self.db.all(f"select name, active from {S}.{kind} order by name")
        return [NamedItem(**r) for r in rows]

    def save_items(self, kind: str, items: list[NamedItem]) -> None:
        assert kind in ("kelas", "mapel")
        with self.db.tx() as c:
            for it in items:
                c.execute(
                    f"insert into {S}.{kind} (name, active) values (%s, %s) "
                    "on conflict (name) do update set active = excluded.active",
                    (it.name, it.active),
                )

    def list_session_defs(self) -> list[SessionDef]:
        return [SessionDef(**r) for r in self.db.all(f"select * from {S}.session_defs order by code")]

    def save_session_defs(self, defs: list[SessionDef]) -> None:
        with self.db.tx() as c:
            for d in defs:
                c.execute(
                    f"insert into {S}.session_defs (code, name, start_hhmm, end_hhmm) values (%s, %s, %s, %s) "
                    "on conflict (code) do update set name = excluded.name, start_hhmm = excluded.start_hhmm, "
                    "end_hhmm = excluded.end_hhmm",
                    (d.code, d.name, d.start_hhmm, d.end_hhmm),
                )


class PgUserRepo(_R, UserRepo):
    COLS = _cols(User)

    def list(self) -> list[User]:
        return [_model(User, r) for r in self.db.all(f"select * from {S}.users order by name")]

    def get(self, user_id: str) -> User | None:
        r = self.db.one(f"select * from {S}.users where user_id = %s", (user_id,))
        return _model(User, r) if r else None

    def get_by_username(self, username: str) -> User | None:
        r = self.db.one(f"select * from {S}.users where lower(username) = lower(%s)", (username.strip(),))
        return _model(User, r) if r else None

    def create(self, user: User) -> None:
        self.db.run(_insert_sql("users", self.COLS), [getattr(user, c) for c in self.COLS])

    def update(self, user: User) -> None:
        cols = [c for c in self.COLS if c != "user_id"]
        sets = ", ".join(f"{c} = %s" for c in cols)
        n = self.db.run(f"update {S}.users set {sets} where user_id = %s",
                        [getattr(user, c) for c in cols] + [user.user_id])
        if n != 1:
            raise KeyError(user.user_id)


class PgRateRepo(_R, RateRepo):
    COLS = _cols(Rate)

    def list_all(self) -> list[Rate]:
        return [_model(Rate, r) for r in self.db.all(f"select * from {S}.rates order by id")]

    def list_for(self, user_id: str) -> list[Rate]:
        rows = self.db.all(f"select * from {S}.rates where user_id = %s order by id", (user_id,))
        return [_model(Rate, r) for r in rows]

    def add(self, rate: Rate) -> None:
        self.db.run(_insert_sql("rates", self.COLS), [getattr(rate, c) for c in self.COLS])


class PgSessionRepo(_R, SessionRepo):
    COLS = _cols(SessionInstance)

    def get(self, session_id: str) -> SessionInstance | None:
        r = self.db.one(f"select * from {S}.session_instances where session_id = %s", (session_id,))
        return _model(SessionInstance, r) if r else None

    def find(self, d: date, code: str) -> SessionInstance | None:
        r = self.db.one(f"select * from {S}.session_instances where date = %s and code = %s", (d, code))
        return _model(SessionInstance, r) if r else None

    def list_by_date(self, d: date) -> list[SessionInstance]:
        rows = self.db.all(f"select * from {S}.session_instances where date = %s order by code", (d,))
        return [_model(SessionInstance, r) for r in rows]

    def create(self, s: SessionInstance) -> None:
        self.db.run(_insert_sql("session_instances", self.COLS), [getattr(s, c) for c in self.COLS])

    def update(self, s: SessionInstance) -> None:
        cols = [c for c in self.COLS if c != "session_id"]
        sets = ", ".join(f"{c} = %s" for c in cols)
        self.db.run(f"update {S}.session_instances set {sets} where session_id = %s",
                    [getattr(s, c) for c in cols] + [s.session_id])


class PgAttendanceRepo(_R, AttendanceRepo):
    COLS = _cols(Attendance)

    def _vals(self, a: Attendance, cols: list[str]) -> list[Any]:
        return [(a.ticket_id or None) if c == "ticket_id" else getattr(a, c) for c in cols]

    def get(self, attendance_id: str) -> Attendance | None:
        r = self.db.one(f"select * from {S}.attendance where attendance_id = %s", (attendance_id,))
        return _model(Attendance, r) if r else None

    def list(self, f: AttendanceFilter | None = None) -> list[Attendance]:
        f = f or AttendanceFilter()
        where, params = [], []
        for col, op, val in (("date", ">=", f.date_from), ("date", "<=", f.date_to),
                             ("user_id", "=", f.user_id), ("session_id", "=", f.session_id)):
            if val:
                where.append(f"{col} {op} %s")
                params.append(val)
        if not f.include_voided:
            where.append("not voided")
        sql = f"select * from {S}.attendance"
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by date, code, scanned_at"
        return [_model(Attendance, r) for r in self.db.all(sql, params)]

    def list_for_session_fresh(self, session_id: str) -> list[Attendance]:
        return self.list(AttendanceFilter(session_id=session_id))

    def add(self, a: Attendance) -> None:
        from psycopg import errors

        try:
            self.db.run(_insert_sql("attendance", self.COLS), self._vals(a, self.COLS))
        except errors.UniqueViolation as e:
            raise DuplicateAttendanceError(a.session_id) from e

    def update(self, a: Attendance) -> None:
        cols = [c for c in self.COLS if c != "attendance_id"]
        sets = ", ".join(f"{c} = %s" for c in cols)
        self.db.run(f"update {S}.attendance set {sets} where attendance_id = %s",
                    self._vals(a, cols) + [a.attendance_id])


class PgAttemptRepo(_R, AttemptRepo):
    COLS = _cols(Attempt)

    def add(self, a: Attempt) -> None:
        self.db.run(_insert_sql("attempts", self.COLS), [getattr(a, c) for c in self.COLS])

    def recent(self, limit: int = 200) -> list[Attempt]:
        rows = self.db.all(f"select * from {S}.attempts order by ts desc, id desc limit %s", (limit,))
        return [_model(Attempt, r) for r in rows]


class PgPayslipRepo(_R, PayslipRepo):
    COLS = _cols(Payslip)

    def get(self, period: str, user_id: str) -> Payslip | None:
        r = self.db.one(f"select * from {S}.payslips where period = %s and user_id = %s", (period, user_id))
        return _model(Payslip, r) if r else None

    def list(self, period: str) -> list[Payslip]:
        return [_model(Payslip, r) for r in self.db.all(f"select * from {S}.payslips where period = %s", (period,))]

    def upsert(self, p: Payslip) -> None:
        upd = ", ".join(f"{c} = excluded.{c}" for c in self.COLS if c not in ("period", "user_id"))
        self.db.run(_insert_sql("payslips", self.COLS, f"on conflict (period, user_id) do update set {upd}"),
                    [getattr(p, c) for c in self.COLS])


class PgAuditRepo(_R, AuditRepo):
    COLS = _cols(AuditEntry)

    def add(self, e: AuditEntry) -> None:
        self.db.run(_insert_sql("audit_log", self.COLS), [getattr(e, c) for c in self.COLS])

    def recent(self, limit: int = 200) -> list[AuditEntry]:
        rows = self.db.all(f"select * from {S}.audit_log order by ts desc, id desc limit %s", (limit,))
        return [_model(AuditEntry, r) for r in rows]


def PostgresRepository(dsn: str | None = None, db: Database | None = None) -> Repository:  # noqa: N802
    db = db or Database(dsn or "")
    return Repository(
        settings=PgSettingsRepo(db),
        meta=PgMetaRepo(db),
        users=PgUserRepo(db),
        rates=PgRateRepo(db),
        sessions=PgSessionRepo(db),
        attendance=PgAttendanceRepo(db),
        attempts=PgAttemptRepo(db),
        payslips=PgPayslipRepo(db),
        audit=PgAuditRepo(db),
    )
