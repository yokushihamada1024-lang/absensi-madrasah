"""Endpoint admin (role admin saja)."""

from __future__ import annotations

import uuid
from datetime import date

import segno
from fastapi import APIRouter, Depends, Query

from api.auth import ctx, require_admin
from api.schemas import (
    PERIOD_RE,
    ManualIn,
    NamedItemsIn,
    OpenSessionIn,
    RateIn,
    ReasonIn,
    ResetPinIn,
    SessionDefsIn,
    SettingsIn,
    UserCreateIn,
    UserPatchIn,
    attendance_out,
    session_out,
    user_out,
)
from api.state import AppContext
from core import audit, payroll
from core.models import AppError, NamedItem, Rate, SessionDef, Settings, User
from core.repo.base import AttendanceFilter
from core.security import hash_pin
from core.timeutil import parse_hhmm, period_bounds, period_label, period_of, to_iso, wib_date

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _names(c: AppContext) -> dict[str, str]:
    return {d.code: d.name for d in c.repo.meta.list_session_defs()}


def _guru_or_404(c: AppContext, user_id: str) -> User:
    u = c.repo.users.get(user_id)
    if u is None:
        raise AppError("USER_NOT_FOUND", "User tidak ditemukan.", 404)
    return u


# --- sesi -------------------------------------------------------------------


@router.post("/sessions/open")
def open_session(body: OpenSessionIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    return session_out(c.svc.open_session(admin, body.code), _names(c))


@router.post("/sessions/{session_id}/close")
def close_session(session_id: str, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    return session_out(c.svc.close_session(admin, session_id), _names(c))


@router.get("/sessions/{session_id}/qr")
def session_qr(session_id: str, c: AppContext = Depends(ctx)) -> dict:
    q = c.svc.qr(session_id)
    svg = segno.make_qr(q.token, error="m").svg_inline(scale=10, border=2, dark="#000", light="#fff")
    return {
        "token": q.token,
        "svg": svg,
        "expires_at": to_iso(q.expires_at),
        "rotate_sec": q.rotate_sec,
        "server_time": to_iso(c.clock()),
    }


@router.get("/sessions/today")
def sessions_today(c: AppContext = Depends(ctx)) -> dict:
    today = wib_date(c.clock())
    names = _names(c)
    rows = c.repo.attendance.list(AttendanceFilter(date_from=today, date_to=today, include_voided=False))
    out = []
    instances = {s.code: s for s in c.svc.sessions_today()}
    for d in c.repo.meta.list_session_defs():
        s = instances.get(d.code)
        item = {"code": d.code, "name": d.name, "start_hhmm": d.start_hhmm, "end_hhmm": d.end_hhmm,
                "session": session_out(s, names) if s else None,
                "attended": sum(1 for a in rows if s and a.session_id == s.session_id)}
        out.append(item)
    return {"date": today.isoformat(), "sessions": out,
            "location_set": c.repo.settings.get().location_set}


# --- guru/user --------------------------------------------------------------


@router.get("/users")
def list_users(c: AppContext = Depends(ctx)) -> list[dict]:
    today = wib_date(c.clock())
    rates = c.repo.rates.list_all()
    out = []
    for u in c.repo.users.list():
        d = user_out(u)
        cur = payroll.rate_on([r for r in rates if r.user_id == u.user_id], today)
        d["current_rate"] = cur.rate_per_meeting if cur else None
        out.append(d)
    return out


@router.post("/users", status_code=201)
def create_user(body: UserCreateIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    if c.repo.users.get_by_username(body.username):
        raise AppError("USERNAME_TAKEN", f"Username '{body.username}' sudah dipakai.", 409)
    if body.role == "guru" and body.rate_per_meeting is None:
        raise AppError("RATE_REQUIRED", "Tarif per pertemuan wajib diisi untuk guru.", 422)
    now = c.clock()
    u = User(user_id=str(uuid.uuid4()), username=body.username, name=body.name, role=body.role,
             pin_hash=hash_pin(body.pin), created_at=now)
    c.repo.users.create(u)
    audit.record(c.repo, now, admin.user_id, "user.create", "user", u.user_id, None, u)
    if body.role == "guru" and body.rate_per_meeting is not None:
        eff = body.effective_from or period_bounds(period_of(wib_date(now)))[0]
        r = Rate(user_id=u.user_id, rate_per_meeting=body.rate_per_meeting, effective_from=eff,
                 set_by=admin.user_id, set_at=now)
        c.repo.rates.add(r)
        audit.record(c.repo, now, admin.user_id, "rate.set", "user", u.user_id, None, r)
    return user_out(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatchIn, admin: User = Depends(require_admin),
               c: AppContext = Depends(ctx)) -> dict:
    u = _guru_or_404(c, user_id)
    changes: dict = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.active is not None and body.active != u.active:
        if u.user_id == admin.user_id and not body.active:
            raise AppError("CANNOT_DEACTIVATE_SELF", "Tidak bisa menonaktifkan akun sendiri.", 409)
        changes["active"] = body.active
        if not body.active:
            changes["token_version"] = u.token_version + 1  # token lama langsung ditolak
    if not changes:
        return user_out(u)
    new = u.model_copy(update=changes)
    c.repo.users.update(new)
    audit.record(c.repo, c.clock(), admin.user_id, "user.update", "user", u.user_id, u, new)
    return user_out(new)


@router.post("/users/{user_id}/reset-pin")
def reset_pin(user_id: str, body: ResetPinIn, admin: User = Depends(require_admin),
              c: AppContext = Depends(ctx)) -> dict:
    u = _guru_or_404(c, user_id)
    new = u.model_copy(update={"pin_hash": hash_pin(body.pin), "token_version": u.token_version + 1})
    c.repo.users.update(new)
    audit.record(c.repo, c.clock(), admin.user_id, "user.reset_pin", "user", u.user_id,
                 {"token_version": u.token_version}, {"token_version": new.token_version})
    return user_out(new)


def _rate_out(r: Rate) -> dict:
    return {"rate_per_meeting": r.rate_per_meeting, "effective_from": r.effective_from.isoformat(),
            "set_by": r.set_by, "set_at": to_iso(r.set_at)}


@router.put("/users/{user_id}/rate")
def set_rate(user_id: str, body: RateIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    u = _guru_or_404(c, user_id)
    if u.role != "guru":
        raise AppError("NOT_GURU", "Tarif hanya untuk guru.", 422)
    now = c.clock()
    r = Rate(user_id=user_id, rate_per_meeting=body.rate_per_meeting, effective_from=body.effective_from,
             set_by=admin.user_id, set_at=now)
    c.repo.rates.add(r)
    audit.record(c.repo, now, admin.user_id, "rate.set", "user", user_id, None, r)
    return _rate_out(r)


@router.get("/users/{user_id}/rates")
def list_rates(user_id: str, c: AppContext = Depends(ctx)) -> list[dict]:
    _guru_or_404(c, user_id)
    rates = sorted(c.repo.rates.list_for(user_id), key=lambda r: (r.effective_from, r.set_at), reverse=True)
    return [_rate_out(r) for r in rates]


# --- pengaturan -------------------------------------------------------------


@router.get("/settings")
def get_settings(c: AppContext = Depends(ctx)) -> dict:
    return c.repo.settings.get().model_dump()


@router.put("/settings")
def put_settings(body: SettingsIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    if (body.lat is None) != (body.lng is None):
        raise AppError("VALIDATION_ERROR", "Latitude dan longitude harus diisi berdua.", 422)
    before = c.repo.settings.get()
    new = Settings(**body.model_dump(), timezone="Asia/Jakarta")
    c.repo.settings.save(new)
    audit.record(c.repo, c.clock(), admin.user_id, "settings.update", "settings", "settings", before, new)
    return new.model_dump()


def _items(c: AppContext, kind: str) -> list[dict]:
    return [i.model_dump() for i in c.repo.meta.list_items(kind)]


def _put_items(kind: str, body: NamedItemsIn, admin: User, c: AppContext) -> list[dict]:
    names = [i.name for i in body.items]
    if len(set(names)) != len(names):
        raise AppError("VALIDATION_ERROR", "Nama tidak boleh dobel.", 422)
    before = _items(c, kind)
    c.repo.meta.save_items(kind, [NamedItem(name=i.name, active=i.active) for i in body.items])
    after = _items(c, kind)
    audit.record(c.repo, c.clock(), admin.user_id, f"{kind}.update", kind, kind, before, after)
    return after


@router.get("/kelas")
def get_kelas(c: AppContext = Depends(ctx)) -> list[dict]:
    return _items(c, "kelas")


@router.put("/kelas")
def put_kelas(body: NamedItemsIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> list[dict]:
    return _put_items("kelas", body, admin, c)


@router.get("/mapel")
def get_mapel(c: AppContext = Depends(ctx)) -> list[dict]:
    return _items(c, "mapel")


@router.put("/mapel")
def put_mapel(body: NamedItemsIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> list[dict]:
    return _put_items("mapel", body, admin, c)


@router.get("/session-defs")
def get_session_defs(c: AppContext = Depends(ctx)) -> list[dict]:
    return [d.model_dump() for d in c.repo.meta.list_session_defs()]


@router.put("/session-defs")
def put_session_defs(body: SessionDefsIn, admin: User = Depends(require_admin),
                     c: AppContext = Depends(ctx)) -> list[dict]:
    codes = [d.code for d in body.items]
    if len(set(codes)) != len(codes):
        raise AppError("VALIDATION_ERROR", "Kode sesi tidak boleh dobel.", 422)
    for d in body.items:
        if parse_hhmm(d.start_hhmm) >= parse_hhmm(d.end_hhmm):
            raise AppError("VALIDATION_ERROR", f"{d.name}: jam mulai harus sebelum jam selesai.", 422)
    before = get_session_defs(c)
    c.repo.meta.save_session_defs([SessionDef(**d.model_dump()) for d in body.items])
    after = get_session_defs(c)
    audit.record(c.repo, c.clock(), admin.user_id, "session_defs.update", "session_defs", "session_defs",
                 before, after)
    return after


# --- absensi ----------------------------------------------------------------


@router.get("/attendance")
def list_attendance(
    date_: date | None = Query(default=None, alias="date"),
    user_id: str | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    include_voided: bool = True,
    c: AppContext = Depends(ctx),
) -> list[dict]:
    if date_:
        from_, to = date_, date_
    if not (from_ or to or user_id):
        from_ = to = wib_date(c.clock())
    rows = c.repo.attendance.list(AttendanceFilter(date_from=from_, date_to=to, user_id=user_id or None,
                                                   include_voided=include_voided))
    names = _names(c)
    out = []
    for a in sorted(rows, key=lambda a: (a.date, a.code, a.scanned_at), reverse=True):
        d = attendance_out(a, admin=True)
        d["session_name"] = names.get(a.code, a.code)
        out.append(d)
    return out


@router.post("/attendance/manual", status_code=201)
def manual_attendance(body: ManualIn, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    a = c.svc.manual_entry(admin, body.user_id, body.date, body.code, body.kelas, body.mapel, body.reason, body.time)
    return attendance_out(a, admin=True)


@router.post("/attendance/{attendance_id}/void")
def void_attendance(attendance_id: str, body: ReasonIn, admin: User = Depends(require_admin),
                    c: AppContext = Depends(ctx)) -> dict:
    return attendance_out(c.svc.void(admin, attendance_id, body.reason), admin=True)


# --- penggajian -------------------------------------------------------------


def _period(period: str) -> str:
    if not PERIOD_RE.match(period):
        raise AppError("VALIDATION_ERROR", "Periode harus YYYY-MM.", 422)
    return period


def line_out(line: payroll.PayrollLine) -> dict:
    return {
        "user": user_out(line.user),
        "period": line.period,
        "meetings": line.meetings,
        "gross": line.gross,
        "take_home": line.take_home,
        "status": line.status,
        "rate_groups": [g.__dict__ for g in line.rate_groups],
        "current_rate": line.current_rate,
        "missing_rate": line.missing_rate,
        "finalized_at": to_iso(line.finalized_at) if line.finalized_at else None,
        "finalized_by": line.finalized_by,
    }


@router.get("/payroll")
def get_payroll(period: str | None = None, c: AppContext = Depends(ctx)) -> dict:
    p = _period(period or period_of(wib_date(c.clock())))
    lines = payroll.compute_period(c.repo, p, today=wib_date(c.clock()))
    return {
        "period": p,
        "period_label": period_label(p),
        "lines": [line_out(ln) for ln in lines],
        "total_meetings": sum(ln.meetings for ln in lines),
        "total_take_home": sum(ln.take_home for ln in lines),
    }


@router.post("/payroll/{period}/{user_id}/finalize")
def finalize(period: str, user_id: str, admin: User = Depends(require_admin), c: AppContext = Depends(ctx)) -> dict:
    p = payroll.finalize(c.repo, _period(period), user_id, admin, c.clock())
    return line_out(payroll.compute_line(c.repo, p.period, _guru_or_404(c, user_id)))


@router.post("/payroll/{period}/{user_id}/reopen")
def reopen(period: str, user_id: str, body: ReasonIn, admin: User = Depends(require_admin),
           c: AppContext = Depends(ctx)) -> dict:
    p = payroll.reopen(c.repo, _period(period), user_id, admin, body.reason, c.clock())
    return line_out(payroll.compute_line(c.repo, p.period, _guru_or_404(c, user_id)))


# --- log --------------------------------------------------------------------


@router.get("/attempts")
def list_attempts(
    date_: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=200, ge=1, le=1000),
    c: AppContext = Depends(ctx),
) -> list[dict]:
    users = {u.user_id: u for u in c.repo.users.list()}
    out = []
    for a in c.repo.attempts.recent(limit if not date_ else 1000):
        if date_ and wib_date(a.ts) != date_:
            continue
        u = users.get(a.user_id)
        out.append({"ts": to_iso(a.ts), "user_id": a.user_id, "teacher_name": u.name if u else a.user_id,
                    "session_id": a.session_id, "reason": a.reason, "distance_m": a.distance_m,
                    "accuracy_m": a.accuracy_m, "detail": a.detail})
    return out[:limit]


@router.get("/audit")
def list_audit(limit: int = Query(default=200, ge=1, le=1000), c: AppContext = Depends(ctx)) -> list[dict]:
    users = {u.user_id: u.name for u in c.repo.users.list()}
    return [{"ts": to_iso(e.ts), "actor": e.actor, "actor_name": users.get(e.actor, e.actor), "action": e.action,
             "entity": e.entity, "entity_id": e.entity_id, "before_json": e.before_json, "after_json": e.after_json,
             "reason": e.reason} for e in c.repo.audit.recent(limit)]
