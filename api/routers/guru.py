"""Endpoint login & guru."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from api.auth import client_ip, ctx, current_user, issue_access_token, require_guru
from api.schemas import PERIOD_RE, LoginIn, ScanIn, SubmitIn, attendance_out, session_out, user_out
from api.state import AppContext
from core.attendance import compute_status, scan_window
from core.models import AppError, User
from core.payroll import compute_line, rate_on
from core.security import verify_pin
from core.timeutil import period_label, period_of, to_iso, wib_date

router = APIRouter(prefix="/api")


def _def_names(c: AppContext) -> dict[str, str]:
    return {d.code: d.name for d in c.repo.meta.list_session_defs()}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, c: AppContext = Depends(ctx)) -> dict:
    ip = client_ip(request)
    wait = c.limiter.retry_after(body.username, ip)
    if wait:
        raise AppError("RATE_LIMITED", f"Terlalu banyak percobaan. Coba lagi dalam {wait} detik.", 429,
                       retry_after=wait)
    user = c.repo.users.get_by_username(body.username)
    ok = verify_pin(user.pin_hash if user else None, body.pin)
    if not ok or user is None or not user.active:
        c.limiter.fail(body.username, ip)
        raise AppError("INVALID_CREDENTIALS", "Username atau PIN salah.", 401)
    c.limiter.success(body.username, ip)
    token, exp = issue_access_token(c.config.jwt_secret, user, c.clock())
    return {"token": token, "expires_at": to_iso(exp), "user": user_out(user)}


@router.post("/auth/logout", status_code=204)
def logout() -> Response:
    # Token stateless; klien menghapus token (DECISIONS D5).
    return Response(status_code=204)


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_out(user)


@router.get("/me/summary")
def me_summary(
    month: str | None = Query(default=None),
    user: User = Depends(current_user),
    c: AppContext = Depends(ctx),
) -> dict:
    today = wib_date(c.clock())
    period = month or period_of(today)
    if not PERIOD_RE.match(period):
        raise AppError("VALIDATION_ERROR", "Format bulan harus YYYY-MM.", 422)
    line = compute_line(c.repo, period, user, today=today)
    cur = rate_on(c.repo.rates.list_for(user.user_id), today)
    names = _def_names(c)
    todays = {s.session_id: s for s in c.repo.sessions.list_by_date(today)}
    today_rows = [a for a in line.rows if a.date == today] if period == period_of(today) else []
    by_code = {a.code: a for a in today_rows}
    today_sessions = []
    for code, name in sorted(names.items()):
        a = by_code.get(code)
        inst = next((s for s in todays.values() if s.code == code), None)
        today_sessions.append({
            "code": code,
            "name": name,
            "is_open": bool(inst and inst.is_open),
            "attended": a is not None,
            "status": a.status if a else None,
            "late_min": a.late_min if a else 0,
            "time_hhmm": attendance_out(a)["time_hhmm"] if a else None,
        })
    return {
        "user": user_out(user),
        "period": period,
        "period_label": period_label(period),
        "period_status": line.status,
        "attendance": [attendance_out(a) for a in line.rows],
        "dates": sorted({a.date.isoformat() for a in line.rows}),
        "meetings": line.meetings,
        "current_rate": cur.rate_per_meeting if cur else None,
        "estimated_gross": line.gross,
        "today": {"date": today.isoformat(), "sessions": today_sessions},
    }


@router.get("/sessions/active")
def sessions_active(user: User = Depends(current_user), c: AppContext = Depends(ctx)) -> list[dict]:
    settings = c.repo.settings.get()
    names = _def_names(c)
    out = []
    for s in c.svc.active_sessions():
        w0, w1 = scan_window(s, settings)
        d = session_out(s, names)
        d.update(window_start=to_iso(w0), window_end=to_iso(w1))
        out.append(d)
    return out


@router.get("/meta")
def meta(user: User = Depends(current_user), c: AppContext = Depends(ctx)) -> dict:
    return {
        "madrasah_name": c.repo.settings.get().madrasah_name,
        "kelas": [i.name for i in c.repo.meta.list_items("kelas") if i.active],
        "mapel": [i.name for i in c.repo.meta.list_items("mapel") if i.active],
        "session_defs": [d.model_dump() for d in c.repo.meta.list_session_defs()],
    }


@router.post("/attendance/scan")
def attendance_scan(body: ScanIn, user: User = Depends(require_guru), c: AppContext = Depends(ctx)) -> dict:
    r = c.svc.scan(user, body.token, body.lat, body.lng, body.accuracy_m, body.position_ts, body.client_ts)
    status, late = compute_status(r.scanned_at, r.session.scheduled_start, c.repo.settings.get().grace_min)
    return {
        "ticket": r.ticket,
        "expires_at": to_iso(r.expires_at),
        "scanned_at": to_iso(r.scanned_at),
        "session": session_out(r.session, _def_names(c)),
        "distance_m": r.distance_m,
        "accuracy_m": r.accuracy_m,
        "status_preview": status,
        "late_min_preview": late,
    }


@router.post("/attendance/submit")
def attendance_submit(body: SubmitIn, user: User = Depends(require_guru), c: AppContext = Depends(ctx)) -> dict:
    a = c.svc.submit(user, body.ticket, body.kelas, body.mapel)
    out = attendance_out(a)
    out["session_name"] = _def_names(c).get(a.code, a.code)
    return out
