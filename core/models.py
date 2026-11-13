"""Model domain (pydantic v2) dan error aplikasi."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["admin", "guru"]
Status = Literal["on_time", "late"]
Source = Literal["scan", "manual", "button"]  # button = konfirmasi tanpa QR (fallback)


class AppError(Exception):
    """Error bisnis dengan kode stabil yang dipetakan ke HTTP oleh lapisan API."""

    def __init__(self, code: str, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


class Settings(BaseModel):
    madrasah_name: str = "Madrasah"
    lat: float | None = None
    lng: float | None = None
    radius_m: float = Field(100, gt=0, le=5000)
    max_accuracy_m: float = Field(75, gt=0, le=5000)
    qr_rotate_sec: int = Field(30, ge=10, le=300)
    grace_min: int = Field(5, ge=0, le=180)
    early_open_min: int = Field(20, ge=0, le=180)
    allow_button_checkin: bool = False  # fallback: absen tanpa QR, tetap wajib di dalam radius
    timezone: str = "Asia/Jakarta"

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: float | None) -> float | None:
        if v is not None and not -90 <= v <= 90:
            raise ValueError("lat harus di antara -90 dan 90")
        return v

    @field_validator("lng")
    @classmethod
    def _lng(cls, v: float | None) -> float | None:
        if v is not None and not -180 <= v <= 180:
            raise ValueError("lng harus di antara -180 dan 180")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if v != "Asia/Jakarta":
            raise ValueError("hanya Asia/Jakarta yang didukung")
        return v

    @property
    def location_set(self) -> bool:
        return self.lat is not None and self.lng is not None


class SessionDef(BaseModel):
    code: str
    name: str
    start_hhmm: str
    end_hhmm: str


class NamedItem(BaseModel):
    name: str
    active: bool = True


class User(BaseModel):
    user_id: str
    username: str
    name: str
    role: Role
    pin_hash: str
    token_version: int = 0
    active: bool = True
    created_at: datetime


class Rate(BaseModel):
    user_id: str
    rate_per_meeting: int
    effective_from: date
    set_by: str
    set_at: datetime


class SessionInstance(BaseModel):
    session_id: str
    date: date
    code: str
    scheduled_start: datetime
    scheduled_end: datetime
    opened_at: datetime | None = None
    opened_by: str = ""
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None and self.closed_at is None


class Attendance(BaseModel):
    attendance_id: str
    session_id: str
    date: date
    code: str
    user_id: str
    teacher_name: str
    kelas: str
    mapel: str
    scanned_at: datetime
    submitted_at: datetime
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    distance_m: float | None = None
    status: Status
    late_min: int = 0
    rate_snapshot: int = 0
    source: Source = "scan"
    voided: bool = False
    void_reason: str = ""
    voided_by: str = ""
    ticket_id: str = ""


class Attempt(BaseModel):
    ts: datetime
    user_id: str
    session_id: str = ""
    reason: str
    distance_m: float | None = None
    accuracy_m: float | None = None
    detail: str = ""


class Payslip(BaseModel):
    period: str
    user_id: str
    meetings: int
    gross: int
    take_home: int
    status: Literal["draft", "final"]
    finalized_at: datetime | None = None
    finalized_by: str = ""
    snapshot_json: str = ""


class AuditEntry(BaseModel):
    ts: datetime
    actor: str
    action: str
    entity: str
    entity_id: str
    before_json: str = ""
    after_json: str = ""
    reason: str = ""
