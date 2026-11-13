"""Utilitas waktu. Semua timestamp disimpan UTC ISO-8601; tampilan & batas bulan di Asia/Jakarta."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")

BULAN = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime harus timezone-aware")
    return dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    """UTC ISO-8601 dengan presisi detik, akhiran Z."""
    return ensure_utc(dt).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_wib(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(WIB)


def wib_date(dt: datetime) -> date:
    return to_wib(dt).date()


def wib_hhmm(dt: datetime) -> str:
    return to_wib(dt).strftime("%H:%M")


def parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59) or len(mm) != 2:
        raise ValueError(f"format jam tidak valid: {value!r}")
    return time(h, m)


def wib_to_utc(d: date, hhmm: str) -> datetime:
    """Tanggal WIB + jam 'HH:MM' WIB → datetime UTC."""
    return datetime.combine(d, parse_hhmm(hhmm), tzinfo=WIB).astimezone(UTC)


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_period(period: str) -> tuple[int, int]:
    parts = period.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError(f"periode harus YYYY-MM: {period!r}")
    y, m = int(parts[0]), int(parts[1])
    if not 1 <= m <= 12:
        raise ValueError(f"bulan tidak valid: {period!r}")
    return y, m


def period_bounds(period: str) -> tuple[date, date]:
    """Tanggal pertama & terakhir (inklusif) periode."""
    y, m = parse_period(period)
    first = date(y, m, 1)
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return first, nxt - timedelta(days=1)


def month_name(month: int) -> str:
    return BULAN[month - 1]


def period_label(period: str) -> str:
    """'2026-11' → 'November 2026'."""
    y, m = parse_period(period)
    return f"{month_name(m)} {y}"


def format_date_id(d: date, with_day: bool = False) -> str:
    """date(2026,11,13) → '13 November 2026' (opsional diawali nama hari)."""
    s = f"{d.day} {month_name(d.month)} {d.year}"
    return f"{HARI[d.weekday()]}, {s}" if with_day else s


def format_datetime_id(dt: datetime) -> str:
    w = to_wib(dt)
    return f"{format_date_id(w.date())} {w.strftime('%H:%M')} WIB"
