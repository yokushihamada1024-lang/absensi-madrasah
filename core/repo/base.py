"""Interface repository. Logika bisnis hanya bergantung pada modul ini."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

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

# Kolom per tabel (dipakai backend in-memory; skema Postgres ada di db/schema.sql).
SCHEMA: dict[str, list[str]] = {
    "settings": ["key", "value"],
    "session_defs": ["code", "name", "start_hhmm", "end_hhmm"],
    "kelas": ["name", "active"],
    "mapel": ["name", "active"],
    "users": ["user_id", "username", "name", "role", "pin_hash", "token_version", "active", "created_at"],
    "rates": ["user_id", "rate_per_meeting", "effective_from", "set_by", "set_at"],
    "session_instances": [
        "session_id", "date", "code", "scheduled_start", "scheduled_end", "opened_at", "opened_by", "closed_at",
    ],
    "attendance": [
        "attendance_id", "session_id", "date", "code", "user_id", "teacher_name", "kelas", "mapel",
        "scanned_at", "submitted_at", "lat", "lng", "accuracy_m", "distance_m", "status", "late_min",
        "rate_snapshot", "source", "voided", "void_reason", "voided_by", "ticket_id",
    ],
    "attempts": ["ts", "user_id", "session_id", "reason", "distance_m", "accuracy_m", "detail"],
    "payslips": [
        "period", "user_id", "meetings", "gross", "take_home", "status", "finalized_at", "finalized_by",
        "snapshot_json",
    ],
    "audit_log": ["ts", "actor", "action", "entity", "entity_id", "before_json", "after_json", "reason"],
}

DEFAULT_SESSION_DEFS = [
    SessionDef(code="S1", name="Sesi 1", start_hhmm="13:30", end_hhmm="15:45"),
    SessionDef(code="S2", name="Sesi 2", start_hhmm="16:15", end_hhmm="17:30"),
]
DEFAULT_KELAS = ["Utsman", "Aisyah", "Abu Bakar", "Khadijah", "Fatimah", "Hafsah", "Umar", "Ali"]
DEFAULT_MAPEL = ["Bahasa Arab", "Fikih", "Iqra", "Tahsin", "Tahfidz"]


class SettingsRepo(ABC):
    @abstractmethod
    def get(self) -> Settings: ...

    @abstractmethod
    def save(self, settings: Settings) -> None: ...


class MetaRepo(ABC):
    @abstractmethod
    def list_items(self, kind: str) -> list[NamedItem]:
        """kind = 'kelas' | 'mapel'."""

    @abstractmethod
    def save_items(self, kind: str, items: list[NamedItem]) -> None:
        """Upsert berdasarkan nama; tidak menghapus baris."""

    @abstractmethod
    def list_session_defs(self) -> list[SessionDef]: ...

    @abstractmethod
    def save_session_defs(self, defs: list[SessionDef]) -> None: ...


class UserRepo(ABC):
    @abstractmethod
    def list(self) -> list[User]: ...

    @abstractmethod
    def get(self, user_id: str) -> User | None: ...

    @abstractmethod
    def get_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    def create(self, user: User) -> None: ...

    @abstractmethod
    def update(self, user: User) -> None: ...


class RateRepo(ABC):
    @abstractmethod
    def list_all(self) -> list[Rate]: ...

    @abstractmethod
    def list_for(self, user_id: str) -> list[Rate]: ...

    @abstractmethod
    def add(self, rate: Rate) -> None: ...


class SessionRepo(ABC):
    @abstractmethod
    def get(self, session_id: str) -> SessionInstance | None: ...

    @abstractmethod
    def find(self, d: date, code: str) -> SessionInstance | None: ...

    @abstractmethod
    def list_by_date(self, d: date) -> list[SessionInstance]: ...

    @abstractmethod
    def create(self, s: SessionInstance) -> None: ...

    @abstractmethod
    def update(self, s: SessionInstance) -> None: ...


@dataclass
class AttendanceFilter:
    date_from: date | None = None
    date_to: date | None = None
    user_id: str | None = None
    session_id: str | None = None
    include_voided: bool = True


class DuplicateAttendanceError(Exception):
    """Sudah ada baris valid (voided=false) untuk (session_id, user_id), atau ticket_id sudah dipakai."""


class AttendanceRepo(ABC):
    @abstractmethod
    def get(self, attendance_id: str) -> Attendance | None: ...

    @abstractmethod
    def list(self, f: AttendanceFilter | None = None) -> list[Attendance]: ...

    @abstractmethod
    def list_for_session_fresh(self, session_id: str) -> list[Attendance]:
        """Baca langsung dari storage (bukan cache) — untuk cek duplikat."""

    @abstractmethod
    def add(self, a: Attendance) -> None:
        """Raise DuplicateAttendanceError jika melanggar keunikan."""

    @abstractmethod
    def update(self, a: Attendance) -> None: ...


class AttemptRepo(ABC):
    @abstractmethod
    def add(self, a: Attempt) -> None: ...

    @abstractmethod
    def recent(self, limit: int = 200) -> list[Attempt]:
        """Terbaru lebih dulu."""


class PayslipRepo(ABC):
    @abstractmethod
    def get(self, period: str, user_id: str) -> Payslip | None: ...

    @abstractmethod
    def list(self, period: str) -> list[Payslip]: ...

    @abstractmethod
    def upsert(self, p: Payslip) -> None: ...


class AuditRepo(ABC):
    @abstractmethod
    def add(self, e: AuditEntry) -> None: ...

    @abstractmethod
    def recent(self, limit: int = 200) -> list[AuditEntry]:
        """Terbaru lebih dulu."""


@dataclass
class Repository:
    settings: SettingsRepo
    meta: MetaRepo
    users: UserRepo
    rates: RateRepo
    sessions: SessionRepo
    attendance: AttendanceRepo
    attempts: AttemptRepo
    payslips: PayslipRepo
    audit: AuditRepo
