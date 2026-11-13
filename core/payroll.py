"""Penggajian: tarif berlaku, rekap periode, finalisasi & buka kembali."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from core import audit
from core.models import AppError, Attendance, Payslip, Rate, User
from core.repo.base import AttendanceFilter, Repository
from core.timeutil import parse_period, period_bounds, period_of, wib_date


def rate_on(rates: list[Rate], d: date) -> Rate | None:
    """Tarif berlaku pada tanggal d: effective_from <= d terbaru, seri diputus set_at terbaru."""
    eligible = [r for r in rates if r.effective_from <= d]
    if not eligible:
        return None
    return max(eligible, key=lambda r: (r.effective_from, r.set_at))


@dataclass
class RateGroup:
    rate: int
    meetings: int
    subtotal: int


@dataclass
class PayrollLine:
    user: User
    period: str
    rows: list[Attendance]
    meetings: int
    gross: int
    take_home: int
    status: str  # draft | final
    rate_groups: list[RateGroup] = field(default_factory=list)
    current_rate: int | None = None
    missing_rate: bool = False
    finalized_at: datetime | None = None
    finalized_by: str = ""


def _sort_key(a: Attendance) -> tuple:
    return (a.date, a.code, a.scanned_at)


def compute_line(repo: Repository, period: str, user: User, today: date | None = None) -> PayrollLine:
    first, last = period_bounds(period)
    rows = repo.attendance.list(
        AttendanceFilter(date_from=first, date_to=last, user_id=user.user_id, include_voided=False)
    )
    rows.sort(key=_sort_key)
    groups: dict[int, RateGroup] = {}
    for a in rows:
        g = groups.setdefault(a.rate_snapshot, RateGroup(rate=a.rate_snapshot, meetings=0, subtotal=0))
        g.meetings += 1
        g.subtotal += a.rate_snapshot
    gross = sum(a.rate_snapshot for a in rows)
    cur = rate_on(repo.rates.list_for(user.user_id), today or last)
    slip = repo.payslips.get(period, user.user_id)
    final = slip is not None and slip.status == "final"
    return PayrollLine(
        user=user,
        period=period,
        rows=rows,
        meetings=len(rows),
        gross=gross,
        take_home=gross,  # MVP: tanpa potongan/bonus
        status="final" if final else "draft",
        rate_groups=sorted(groups.values(), key=lambda g: g.rate),
        current_rate=cur.rate_per_meeting if cur else None,
        missing_rate=cur is None or any(a.rate_snapshot == 0 for a in rows),
        finalized_at=slip.finalized_at if final else None,
        finalized_by=slip.finalized_by if final else "",
    )


def compute_period(repo: Repository, period: str, today: date | None = None) -> list[PayrollLine]:
    parse_period(period)
    first, last = period_bounds(period)
    with_rows = {
        a.user_id
        for a in repo.attendance.list(AttendanceFilter(date_from=first, date_to=last, include_voided=False))
    }
    users = [u for u in repo.users.list() if u.role == "guru" and (u.active or u.user_id in with_rows)]
    users.sort(key=lambda u: u.name.lower())
    return [compute_line(repo, period, u, today) for u in users]


def is_final(repo: Repository, period: str, user_id: str) -> bool:
    p = repo.payslips.get(period, user_id)
    return p is not None and p.status == "final"


def assert_not_final(repo: Repository, d: date, user_id: str) -> None:
    period = period_of(d)
    if is_final(repo, period, user_id):
        raise AppError(
            "PERIOD_FINAL",
            f"Periode {period} untuk guru ini sudah final. Buka kembali dulu (dengan alasan).",
            409,
            period=period,
        )


def _get_guru(repo: Repository, user_id: str) -> User:
    u = repo.users.get(user_id)
    if u is None or u.role != "guru":
        raise AppError("USER_NOT_FOUND", "Guru tidak ditemukan.", 404)
    return u


def finalize(repo: Repository, period: str, user_id: str, actor: User, now: datetime) -> Payslip:
    parse_period(period)
    if period > period_of(wib_date(now)):
        raise AppError("PERIOD_IN_FUTURE", "Periode di masa depan tidak bisa difinalisasi.", 409)
    user = _get_guru(repo, user_id)
    if is_final(repo, period, user_id):
        raise AppError("ALREADY_FINAL", "Periode ini sudah final.", 409)
    line = compute_line(repo, period, user)
    before = repo.payslips.get(period, user_id)
    snapshot = {
        "teacher_name": user.name,
        "username": user.username,
        "meetings": line.meetings,
        "gross": line.gross,
        "take_home": line.take_home,
        "rate_groups": [g.__dict__ for g in line.rate_groups],
        "attendance_ids": [a.attendance_id for a in line.rows],
    }
    p = Payslip(
        period=period,
        user_id=user_id,
        meetings=line.meetings,
        gross=line.gross,
        take_home=line.take_home,
        status="final",
        finalized_at=now,
        finalized_by=actor.user_id,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
    )
    repo.payslips.upsert(p)
    audit.record(repo, now, actor.user_id, "payroll.finalize", "payslip", f"{period}/{user_id}", before, p)
    return p


def reopen(repo: Repository, period: str, user_id: str, actor: User, reason: str, now: datetime) -> Payslip:
    if not reason.strip():
        raise AppError("REASON_REQUIRED", "Alasan wajib diisi.", 422)
    _get_guru(repo, user_id)
    before = repo.payslips.get(period, user_id)
    if before is None or before.status != "final":
        raise AppError("NOT_FINAL", "Periode ini belum final.", 409)
    p = before.model_copy(update={"status": "draft"})
    repo.payslips.upsert(p)
    audit.record(repo, now, actor.user_id, "payroll.reopen", "payslip", f"{period}/{user_id}", before, p,
                 reason.strip())
    return p
