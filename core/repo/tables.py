"""Implementasi entitas repository di atas *table backend* generik (baris = dict[str, str]).

Dipakai oleh InMemoryRepository (test & mode dev). Produksi memakai core/repo/postgres.py.
"""

from __future__ import annotations

import types
import typing
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from core.models import (
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
    SCHEMA,
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
from core.timeutil import to_iso

Row = tuple[int, dict[str, str]]  # (nomor baris di sheet, nilai)
M = TypeVar("M", bound=BaseModel)

class TableBackend(ABC):
    @abstractmethod
    def rows(self, tab: str, fresh: bool = False) -> list[Row]: ...

    @abstractmethod
    def write_lock(self) -> AbstractContextManager:
        """Lock untuk operasi baca-lalu-tulis yang harus atomik."""

    @abstractmethod
    def append(self, tab: str, values: dict[str, str]) -> int:
        """Tambah baris; kembalikan nomor baris."""

    @abstractmethod
    def update(self, tab: str, rownum: int, values: dict[str, str], key_col: str) -> None:
        """Tulis ulang baris rownum. Wajib memverifikasi values[key_col] masih sama di baris itu."""


# --- Serialisasi ----------------------------------------------------------


def _ser(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, datetime):
        return to_iso(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return repr(round(v, 7))
    return str(v)


def to_row(m: BaseModel) -> dict[str, str]:
    return {k: _ser(getattr(m, k)) for k in type(m).model_fields}


def _optional(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return type(None) in typing.get_args(annotation)
    return False


def from_row(cls: type[M], row: dict[str, str]) -> M:
    data: dict[str, Any] = {}
    for name, field in cls.model_fields.items():
        raw = row.get(name, "")
        raw = "" if raw is None else str(raw)
        if raw == "":
            if _optional(field.annotation):
                data[name] = None
            elif field.is_required():
                data[name] = raw
            continue
        data[name] = raw
    return cls.model_validate(data)


# --- Implementasi entitas -------------------------------------------------


class _Base:
    def __init__(self, b: TableBackend) -> None:
        self.b = b


class TSettingsRepo(_Base, SettingsRepo):
    def get(self) -> Settings:
        kv = {r["key"]: r["value"] for _, r in self.b.rows("settings") if r.get("key")}
        return from_row(Settings, kv)

    def save(self, settings: Settings) -> None:
        existing = {r["key"]: (n, r) for n, r in self.b.rows("settings", fresh=True) if r.get("key")}
        for k, v in to_row(settings).items():
            vals = {"key": k, "value": v}
            if k in existing:
                n, old = existing[k]
                if old.get("value") != v:
                    self.b.update("settings", n, vals, "key")
            else:
                self.b.append("settings", vals)


class TMetaRepo(_Base, MetaRepo):
    def list_items(self, kind: str) -> list[NamedItem]:
        assert kind in ("kelas", "mapel")
        return [from_row(NamedItem, r) for _, r in self.b.rows(kind) if r.get("name")]

    def save_items(self, kind: str, items: list[NamedItem]) -> None:
        assert kind in ("kelas", "mapel")
        existing = {r["name"]: (n, r) for n, r in self.b.rows(kind, fresh=True) if r.get("name")}
        for it in items:
            vals = to_row(it)
            if it.name in existing:
                n, old = existing[it.name]
                if old.get("active") != vals["active"]:
                    self.b.update(kind, n, vals, "name")
            else:
                self.b.append(kind, vals)

    def list_session_defs(self) -> list[SessionDef]:
        return [from_row(SessionDef, r) for _, r in self.b.rows("session_defs") if r.get("code")]

    def save_session_defs(self, defs: list[SessionDef]) -> None:
        existing = {r["code"]: (n, r) for n, r in self.b.rows("session_defs", fresh=True) if r.get("code")}
        for d in defs:
            vals = to_row(d)
            if d.code in existing:
                n, old = existing[d.code]
                if old != vals:
                    self.b.update("session_defs", n, vals, "code")
            else:
                self.b.append("session_defs", vals)


class _Keyed(_Base):
    tab: str
    key: str
    model: type[BaseModel]

    def _all(self, fresh: bool = False) -> list[tuple[int, Any]]:
        return [(n, from_row(self.model, r)) for n, r in self.b.rows(self.tab, fresh) if r.get(self.key)]

    def _find_row(self, key_val: str) -> int:
        for n, r in self.b.rows(self.tab):
            if r.get(self.key) == key_val:
                return n
        for n, r in self.b.rows(self.tab, fresh=True):
            if r.get(self.key) == key_val:
                return n
        raise KeyError(f"{self.tab}: {key_val} tidak ditemukan")

    def _update(self, m: BaseModel) -> None:
        key_val = getattr(m, self.key)
        self.b.update(self.tab, self._find_row(key_val), to_row(m), self.key)


class TUserRepo(_Keyed, UserRepo):
    tab, key, model = "users", "user_id", User

    def list(self) -> list[User]:
        return [u for _, u in self._all()]

    def get(self, user_id: str) -> User | None:
        return next((u for u in self.list() if u.user_id == user_id), None)

    def get_by_username(self, username: str) -> User | None:
        un = username.strip().lower()
        return next((u for u in self.list() if u.username.lower() == un), None)

    def create(self, user: User) -> None:
        self.b.append(self.tab, to_row(user))

    def update(self, user: User) -> None:
        self._update(user)


class TRateRepo(_Base, RateRepo):
    def list_all(self) -> list[Rate]:
        return [from_row(Rate, r) for _, r in self.b.rows("rates") if r.get("user_id")]

    def list_for(self, user_id: str) -> list[Rate]:
        return [r for r in self.list_all() if r.user_id == user_id]

    def add(self, rate: Rate) -> None:
        self.b.append("rates", to_row(rate))


class TSessionRepo(_Keyed, SessionRepo):
    tab, key, model = "session_instances", "session_id", SessionInstance

    def _list(self) -> list[SessionInstance]:
        return [s for _, s in self._all()]

    def get(self, session_id: str) -> SessionInstance | None:
        return next((s for s in self._list() if s.session_id == session_id), None)

    def find(self, d: date, code: str) -> SessionInstance | None:
        return next((s for s in self._list() if s.date == d and s.code == code), None)

    def list_by_date(self, d: date) -> list[SessionInstance]:
        return [s for s in self._list() if s.date == d]

    def create(self, s: SessionInstance) -> None:
        self.b.append(self.tab, to_row(s))

    def update(self, s: SessionInstance) -> None:
        self._update(s)


class TAttendanceRepo(_Keyed, AttendanceRepo):
    tab, key, model = "attendance", "attendance_id", Attendance

    def get(self, attendance_id: str) -> Attendance | None:
        return next((a for _, a in self._all() if a.attendance_id == attendance_id), None)

    def list(self, f: AttendanceFilter | None = None) -> list[Attendance]:
        f = f or AttendanceFilter()
        out = []
        for _, a in self._all():
            if f.date_from and a.date < f.date_from:
                continue
            if f.date_to and a.date > f.date_to:
                continue
            if f.user_id and a.user_id != f.user_id:
                continue
            if f.session_id and a.session_id != f.session_id:
                continue
            if not f.include_voided and a.voided:
                continue
            out.append(a)
        return out

    def list_for_session_fresh(self, session_id: str) -> list[Attendance]:
        return [from_row(Attendance, r) for _, r in self.b.rows(self.tab, fresh=True)
                if r.get("session_id") == session_id and r.get(self.key)]

    def add(self, a: Attendance) -> None:
        # Meniru constraint unik Postgres (partial unique index + ticket_id unik).
        with self.b.write_lock():
            for _, r in self.b.rows(self.tab, fresh=True):
                same_slot = r.get("session_id") == a.session_id and r.get("user_id") == a.user_id
                if same_slot and r.get("voided") != "TRUE" and not a.voided:
                    raise DuplicateAttendanceError(a.session_id)
                if a.ticket_id and r.get("ticket_id") == a.ticket_id:
                    raise DuplicateAttendanceError(a.ticket_id)
            self.b.append(self.tab, to_row(a))

    def update(self, a: Attendance) -> None:
        self._update(a)


class TAttemptRepo(_Base, AttemptRepo):
    def add(self, a: Attempt) -> None:
        self.b.append("attempts", to_row(a))

    def recent(self, limit: int = 200) -> list[Attempt]:
        rows = self.b.rows("attempts")[-limit:]
        return [from_row(Attempt, r) for _, r in reversed(rows) if r.get("ts")]


class TPayslipRepo(_Base, PayslipRepo):
    def _rows(self, fresh: bool = False) -> list[tuple[int, Payslip]]:
        return [(n, from_row(Payslip, r)) for n, r in self.b.rows("payslips", fresh) if r.get("period")]

    def get(self, period: str, user_id: str) -> Payslip | None:
        return next((p for _, p in self._rows() if p.period == period and p.user_id == user_id), None)

    def list(self, period: str) -> list[Payslip]:
        return [p for _, p in self._rows() if p.period == period]

    def upsert(self, p: Payslip) -> None:
        for n, old in self._rows(fresh=True):
            if old.period == p.period and old.user_id == p.user_id:
                self.b.update("payslips", n, to_row(p), "period")
                return
        self.b.append("payslips", to_row(p))


class TAuditRepo(_Base, AuditRepo):
    def add(self, e: AuditEntry) -> None:
        self.b.append("audit_log", to_row(e))

    def recent(self, limit: int = 200) -> list[AuditEntry]:
        rows = self.b.rows("audit_log")[-limit:]
        return [from_row(AuditEntry, r) for _, r in reversed(rows) if r.get("ts")]


def build_repository(backend: TableBackend) -> Repository:
    return Repository(
        settings=TSettingsRepo(backend),
        meta=TMetaRepo(backend),
        users=TUserRepo(backend),
        rates=TRateRepo(backend),
        sessions=TSessionRepo(backend),
        attendance=TAttendanceRepo(backend),
        attempts=TAttemptRepo(backend),
        payslips=TPayslipRepo(backend),
        audit=TAuditRepo(backend),
    )


__all__ = ["SCHEMA", "TableBackend", "build_repository", "from_row", "to_row"]
