"""Skema request/response API. Tidak pernah memuat pin_hash."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.models import Attendance, SessionInstance, User
from core.timeutil import to_iso, wib_hhmm

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
CODE_RE = re.compile(r"^[A-Z0-9]{1,6}$")
HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- request ----------------------------------------------------------------


class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=64)
    pin: str = Field(min_length=1, max_length=64)


class ScanIn(Strict):
    token: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0, le=100_000)
    position_ts: float = Field(gt=0, description="position.timestamp (ms epoch, jam HP)")
    client_ts: float | None = Field(default=None, gt=0, description="Date.now() saat kirim (ms, jam HP)")


class SubmitIn(Strict):
    ticket: str = Field(min_length=1, max_length=2000)
    kelas: str = Field(min_length=1, max_length=64)
    mapel: str = Field(min_length=1, max_length=64)


class OpenSessionIn(Strict):
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not CODE_RE.match(v):
            raise ValueError("kode sesi tidak valid")
        return v


class UserCreateIn(Strict):
    username: str
    name: str = Field(min_length=1, max_length=100)
    role: str = "guru"
    pin: str = Field(min_length=6, max_length=64)
    rate_per_meeting: int | None = Field(default=None, ge=0, le=100_000_000)
    effective_from: date | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.lower()
        if not USERNAME_RE.match(v):
            raise ValueError("username 3–32 karakter: huruf kecil, angka, titik, minus, garis bawah")
        return v

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("admin", "guru"):
            raise ValueError("role harus admin atau guru")
        return v


class UserPatchIn(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None


class ResetPinIn(Strict):
    pin: str = Field(min_length=6, max_length=64)


class RateIn(Strict):
    rate_per_meeting: int = Field(ge=0, le=100_000_000)
    effective_from: date


class SettingsIn(Strict):
    madrasah_name: str = Field(min_length=1, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float = Field(gt=0, le=5000)
    max_accuracy_m: float = Field(gt=0, le=5000)
    qr_rotate_sec: int = Field(ge=10, le=300)
    grace_min: int = Field(ge=0, le=180)
    early_open_min: int = Field(ge=0, le=180)


class NamedItemIn(Strict):
    name: str = Field(min_length=1, max_length=64)
    active: bool = True


class NamedItemsIn(Strict):
    items: list[NamedItemIn] = Field(max_length=200)


class SessionDefIn(Strict):
    code: str
    name: str = Field(min_length=1, max_length=40)
    start_hhmm: str
    end_hhmm: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not CODE_RE.match(v):
            raise ValueError("kode sesi 1–6 huruf besar/angka")
        return v

    @field_validator("start_hhmm", "end_hhmm")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM_RE.match(v):
            raise ValueError("format jam HH:MM")
        return v


class SessionDefsIn(Strict):
    items: list[SessionDefIn] = Field(min_length=1, max_length=6)


class ManualIn(Strict):
    user_id: str = Field(min_length=1, max_length=64)
    date: date
    code: str
    kelas: str = Field(min_length=1, max_length=64)
    mapel: str = Field(min_length=1, max_length=64)
    time: str | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("time")
    @classmethod
    def _time(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not HHMM_RE.match(v):
            raise ValueError("format jam HH:MM")
        return v


class ReasonIn(Strict):
    reason: str = Field(min_length=1, max_length=500)


# --- response ---------------------------------------------------------------


def user_out(u: User) -> dict:
    return {
        "user_id": u.user_id,
        "username": u.username,
        "name": u.name,
        "role": u.role,
        "active": u.active,
        "created_at": to_iso(u.created_at),
    }


def session_out(s: SessionInstance, names: dict[str, str] | None = None) -> dict:
    return {
        "session_id": s.session_id,
        "date": s.date.isoformat(),
        "code": s.code,
        "name": (names or {}).get(s.code, s.code),
        "scheduled_start": to_iso(s.scheduled_start),
        "scheduled_end": to_iso(s.scheduled_end),
        "start_hhmm": wib_hhmm(s.scheduled_start),
        "end_hhmm": wib_hhmm(s.scheduled_end),
        "opened_at": to_iso(s.opened_at) if s.opened_at else None,
        "closed_at": to_iso(s.closed_at) if s.closed_at else None,
        "is_open": s.is_open,
    }


def attendance_out(a: Attendance, admin: bool = False) -> dict:
    out = {
        "attendance_id": a.attendance_id,
        "session_id": a.session_id,
        "date": a.date.isoformat(),
        "code": a.code,
        "user_id": a.user_id,
        "teacher_name": a.teacher_name,
        "kelas": a.kelas,
        "mapel": a.mapel,
        "scanned_at": to_iso(a.scanned_at),
        "submitted_at": to_iso(a.submitted_at),
        "time_hhmm": wib_hhmm(a.scanned_at),
        "status": a.status,
        "late_min": a.late_min,
        "rate_snapshot": a.rate_snapshot,
        "source": a.source,
        "voided": a.voided,
    }
    if admin:
        out.update(
            lat=a.lat, lng=a.lng, accuracy_m=a.accuracy_m, distance_m=a.distance_m,
            void_reason=a.void_reason, voided_by=a.voided_by,
        )
    return out
