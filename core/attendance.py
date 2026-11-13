"""Sesi, scan QR, konfirmasi tanpa QR (fallback), submit absensi, input manual, void."""

from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core import audit, tokens
from core.geo import check_location
from core.models import AppError, Attempt, Attendance, SessionDef, SessionInstance, Settings, User
from core.payroll import assert_not_final, rate_on
from core.repo.base import AttendanceFilter, DuplicateAttendanceError, Repository
from core.timeutil import Clock, parse_hhmm, wib_date, wib_to_utc


def compute_status(scanned_at: datetime, scheduled_start: datetime, grace_min: int) -> tuple[str, int]:
    """diff_min = floor((scanned_at - scheduled_start)/60 dtk); telat jika diff_min > grace."""
    diff_min = math.floor((scanned_at - scheduled_start).total_seconds() / 60)
    if diff_min > grace_min:
        return "late", diff_min
    return "on_time", 0


def scan_window(s: SessionInstance, settings: Settings) -> tuple[datetime, datetime]:
    start = s.scheduled_start - timedelta(minutes=settings.early_open_min)
    end = s.scheduled_end if s.closed_at is None else min(s.scheduled_end, s.closed_at)
    return start, end


def check_window(s: SessionInstance, settings: Settings, now: datetime) -> None:
    start, end = scan_window(s, settings)
    if s.opened_at is None or now < start:
        raise AppError("SESSION_CLOSED", "Sesi belum dibuka untuk absen.", 409, detail="not_started")
    if now > end:
        raise AppError("SESSION_CLOSED", "Sesi sudah ditutup.", 409, detail="closed")


@dataclass
class ScanResult:
    ticket: str
    expires_at: datetime
    session: SessionInstance
    scanned_at: datetime
    distance_m: float
    accuracy_m: float
    method: str = "scan"


@dataclass
class QrPayload:
    token: str
    expires_at: datetime
    rotate_sec: int
    slot: int


class AttendanceService:
    def __init__(self, repo: Repository, clock: Clock, qr_master_key: str, jwt_secret: str) -> None:
        self.repo = repo
        self.clock = clock
        self.qr_master_key = qr_master_key
        self.jwt_secret = jwt_secret
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- util ----------------------------------------------------------------

    def _lock(self, session_id: str, user_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault((session_id, user_id), threading.Lock())

    def _def(self, code: str) -> SessionDef:
        for d in self.repo.meta.list_session_defs():
            if d.code == code:
                return d
        raise AppError("SESSION_DEF_NOT_FOUND", f"Sesi {code} tidak dikenal.", 404)

    def _log_attempt(self, user_id: str, session_id: str, err: AppError) -> None:
        extra = {k: v for k, v in err.extra.items() if v is not None}
        self.repo.attempts.add(
            Attempt(
                ts=self.clock(),
                user_id=user_id,
                session_id=session_id,
                reason=err.code,
                distance_m=extra.get("distance_m"),
                accuracy_m=extra.get("accuracy_m"),
                detail=json.dumps(extra, ensure_ascii=False, sort_keys=True) if extra else "",
            )
        )

    def _validate_kelas_mapel(self, kelas: str, mapel: str) -> tuple[str, str]:
        k = kelas.strip()
        m = mapel.strip()
        if k not in {i.name for i in self.repo.meta.list_items("kelas") if i.active}:
            raise AppError("INVALID_KELAS", "Kelas tidak dikenal.", 422)
        if m not in {i.name for i in self.repo.meta.list_items("mapel") if i.active}:
            raise AppError("INVALID_MAPEL", "Mata pelajaran tidak dikenal.", 422)
        return k, m

    def _valid_rows(self, session_id: str, user_id: str) -> list[Attendance]:
        return [
            a for a in self.repo.attendance.list_for_session_fresh(session_id)
            if a.user_id == user_id and not a.voided
        ]

    def _rate_for(self, user_id: str, d: date) -> int:
        r = rate_on(self.repo.rates.list_for(user_id), d)
        return r.rate_per_meeting if r else 0

    def _insert(self, a: Attendance) -> Attendance:
        """Tulis baris. Keunikan dijamin storage (Postgres: partial unique index), lock hanya mengurangi balapan.

        Jika kalah balapan: ticket sama → kembalikan baris pemenang (idempoten); selain itu ALREADY_ATTENDED.
        """
        try:
            self.repo.attendance.add(a)
            return a
        except DuplicateAttendanceError:
            for row in self._valid_rows(a.session_id, a.user_id):
                if a.ticket_id and row.ticket_id == a.ticket_id:
                    return row
            raise AppError("ALREADY_ATTENDED", "Anda sudah absen di sesi ini.", 409) from None

    # -- sesi ----------------------------------------------------------------

    def open_session(self, actor: User, code: str) -> SessionInstance:
        settings = self.repo.settings.get()
        if not settings.location_set:
            raise AppError("LOCATION_NOT_SET", "Isi koordinat madrasah di Pengaturan sebelum membuka sesi.", 409)
        d = self._def(code)
        now = self.clock()
        today = wib_date(now)
        existing = self.repo.sessions.find(today, code)
        if existing is not None:
            if existing.is_open:
                return existing
            if now > existing.scheduled_end:
                raise AppError("SESSION_OVER", "Jam sesi ini sudah lewat.", 409)
            reopened = existing.model_copy(update={"closed_at": None, "opened_at": existing.opened_at or now})
            self.repo.sessions.update(reopened)
            audit.record(self.repo, now, actor.user_id, "session.reopen", "session", existing.session_id,
                         existing, reopened)
            return reopened
        start = wib_to_utc(today, d.start_hhmm)
        end = wib_to_utc(today, d.end_hhmm)
        if now > end:
            raise AppError("SESSION_OVER", "Jam sesi ini sudah lewat. Ubah jam sesi di Pengaturan bila perlu.", 409)
        s = SessionInstance(
            session_id=str(uuid.uuid4()),
            date=today,
            code=code,
            scheduled_start=start,
            scheduled_end=end,
            opened_at=now,
            opened_by=actor.user_id,
            closed_at=None,
        )
        self.repo.sessions.create(s)
        audit.record(self.repo, now, actor.user_id, "session.open", "session", s.session_id, None, s)
        return s

    def close_session(self, actor: User, session_id: str) -> SessionInstance:
        s = self.repo.sessions.get(session_id)
        if s is None:
            raise AppError("SESSION_NOT_FOUND", "Sesi tidak ditemukan.", 404)
        if s.closed_at is not None:
            return s
        now = self.clock()
        closed = s.model_copy(update={"closed_at": now})
        self.repo.sessions.update(closed)
        audit.record(self.repo, now, actor.user_id, "session.close", "session", s.session_id, s, closed)
        return closed

    def qr(self, session_id: str) -> QrPayload:
        s = self.repo.sessions.get(session_id)
        if s is None:
            raise AppError("SESSION_NOT_FOUND", "Sesi tidak ditemukan.", 404)
        if not s.is_open:
            raise AppError("SESSION_CLOSED", "Sesi sudah ditutup.", 409, detail="closed")
        rotate = self.repo.settings.get().qr_rotate_sec
        now = self.clock()
        slot = tokens.current_slot(now, rotate)
        return QrPayload(
            token=tokens.make_qr_token(self.qr_master_key, session_id, slot),
            expires_at=tokens.slot_expires_at(slot, rotate),
            rotate_sec=rotate,
            slot=slot,
        )

    def sessions_today(self) -> list[SessionInstance]:
        return sorted(self.repo.sessions.list_by_date(wib_date(self.clock())), key=lambda s: s.code)

    def active_sessions(self) -> list[SessionInstance]:
        return [s for s in self.sessions_today() if s.is_open]

    # -- guru ----------------------------------------------------------------

    def scan(
        self,
        user: User,
        token: str,
        lat: float,
        lng: float,
        accuracy_m: float,
        position_ts_ms: float,
        client_ts_ms: float | None = None,
    ) -> ScanResult:
        session_id = ""
        try:
            now = self.clock()
            settings = self.repo.settings.get()
            session_id = tokens.verify_qr_token(self.qr_master_key, token, now, settings.qr_rotate_sec)
            s = self.repo.sessions.get(session_id)
            if s is None:
                raise AppError("TOKEN_INVALID", "QR tidak dikenali. Scan QR di layar admin.", 400)
            return self._issue_ticket(user, s, settings, now, lat, lng, accuracy_m, position_ts_ms, client_ts_ms,
                                      "scan")
        except AppError as e:
            self._log_attempt(user.user_id, session_id, e)
            raise

    def confirm(
        self,
        user: User,
        session_id: str,
        lat: float,
        lng: float,
        accuracy_m: float,
        position_ts_ms: float,
        client_ts_ms: float | None = None,
    ) -> ScanResult:
        """Fallback tanpa QR: hanya jika diizinkan admin. Jam sesi & geofence tetap sama dengan scan."""
        sid = ""
        try:
            now = self.clock()
            settings = self.repo.settings.get()
            if not settings.allow_button_checkin:
                raise AppError("BUTTON_DISABLED", "Absen tanpa QR sedang dinonaktifkan admin. Silakan scan QR.", 403)
            s = self.repo.sessions.get(session_id)
            if s is None:
                raise AppError("SESSION_NOT_FOUND", "Sesi tidak ditemukan.", 404)
            sid = s.session_id
            return self._issue_ticket(user, s, settings, now, lat, lng, accuracy_m, position_ts_ms, client_ts_ms,
                                      "button")
        except AppError as e:
            self._log_attempt(user.user_id, sid, e)
            raise

    def _issue_ticket(
        self,
        user: User,
        s: SessionInstance,
        settings: Settings,
        now: datetime,
        lat: float,
        lng: float,
        accuracy_m: float,
        position_ts_ms: float,
        client_ts_ms: float | None,
        method: str,
    ) -> ScanResult:
        check_window(s, settings, now)
        if any(
            not a.voided
            for a in self.repo.attendance.list(AttendanceFilter(session_id=s.session_id, user_id=user.user_id))
        ):
            raise AppError("ALREADY_ATTENDED", "Anda sudah absen di sesi ini.", 409)
        loc = check_location(settings, lat, lng, accuracy_m, position_ts_ms, now, client_ts_ms)
        t = tokens.Ticket(
            ticket_id=str(uuid.uuid4()),
            session_id=s.session_id,
            user_id=user.user_id,
            scanned_at=now,
            distance_m=loc.distance_m,
            accuracy_m=accuracy_m,
            lat=lat,
            lng=lng,
            method=method,
        )
        jwt_str, exp = tokens.issue_ticket(self.jwt_secret, t)
        return ScanResult(ticket=jwt_str, expires_at=exp, session=s, scanned_at=now,
                          distance_m=loc.distance_m, accuracy_m=accuracy_m, method=method)

    def submit(self, user: User, ticket: str, kelas: str, mapel: str) -> Attendance:
        session_id = ""
        try:
            now = self.clock()
            t = tokens.decode_ticket(self.jwt_secret, ticket, now)
            session_id = t.session_id
            if t.user_id != user.user_id:
                raise AppError("TICKET_INVALID", "Tiket absen bukan milik Anda.", 403)
            k, m = self._validate_kelas_mapel(kelas, mapel)
            s = self.repo.sessions.get(t.session_id)
            if s is None:
                raise AppError("SESSION_NOT_FOUND", "Sesi tidak ditemukan.", 404)
            settings = self.repo.settings.get()
            with self._lock(t.session_id, user.user_id):
                existing = self._valid_rows(t.session_id, user.user_id)
                for a in existing:
                    if a.ticket_id == t.ticket_id:
                        return a  # idempoten
                if existing:
                    raise AppError("ALREADY_ATTENDED", "Anda sudah absen di sesi ini.", 409)
                assert_not_final(self.repo, s.date, user.user_id)
                status, late = compute_status(t.scanned_at, s.scheduled_start, settings.grace_min)
                a = Attendance(
                    attendance_id=str(uuid.uuid4()),
                    session_id=s.session_id,
                    date=s.date,
                    code=s.code,
                    user_id=user.user_id,
                    teacher_name=user.name,
                    kelas=k,
                    mapel=m,
                    scanned_at=t.scanned_at,
                    submitted_at=now,
                    lat=t.lat,
                    lng=t.lng,
                    accuracy_m=t.accuracy_m,
                    distance_m=t.distance_m,
                    status=status,
                    late_min=late,
                    rate_snapshot=self._rate_for(user.user_id, s.date),
                    source=t.method,
                    ticket_id=t.ticket_id,
                )
                return self._insert(a)
        except AppError as e:
            self._log_attempt(user.user_id, session_id, e)
            raise

    # -- admin ---------------------------------------------------------------

    def manual_entry(
        self,
        actor: User,
        user_id: str,
        d: date,
        code: str,
        kelas: str,
        mapel: str,
        reason: str,
        time_hhmm: str | None = None,
    ) -> Attendance:
        if not reason.strip():
            raise AppError("REASON_REQUIRED", "Alasan wajib diisi.", 422)
        guru = self.repo.users.get(user_id)
        if guru is None or guru.role != "guru":
            raise AppError("USER_NOT_FOUND", "Guru tidak ditemukan.", 404)
        now = self.clock()
        if d > wib_date(now):
            raise AppError("DATE_IN_FUTURE", "Tanggal tidak boleh di masa depan.", 422)
        k, m = self._validate_kelas_mapel(kelas, mapel)
        assert_not_final(self.repo, d, user_id)
        s = self.repo.sessions.find(d, code)
        if s is None:
            sd = self._def(code)
            s = SessionInstance(
                session_id=str(uuid.uuid4()),
                date=d,
                code=code,
                scheduled_start=wib_to_utc(d, sd.start_hhmm),
                scheduled_end=wib_to_utc(d, sd.end_hhmm),
                opened_at=now,
                opened_by=actor.user_id,
                closed_at=now,
            )
            self.repo.sessions.create(s)
            audit.record(self.repo, now, actor.user_id, "session.create_manual", "session", s.session_id,
                         None, s, reason.strip())
        if time_hhmm:
            parse_hhmm(time_hhmm)
            scanned_at = wib_to_utc(d, time_hhmm)
        else:
            scanned_at = s.scheduled_start
        settings = self.repo.settings.get()
        with self._lock(s.session_id, user_id):
            if self._valid_rows(s.session_id, user_id):
                raise AppError("ALREADY_ATTENDED", "Guru ini sudah tercatat hadir di sesi tersebut.", 409)
            status, late = compute_status(scanned_at, s.scheduled_start, settings.grace_min)
            a = Attendance(
                attendance_id=str(uuid.uuid4()),
                session_id=s.session_id,
                date=d,
                code=s.code,
                user_id=user_id,
                teacher_name=guru.name,
                kelas=k,
                mapel=m,
                scanned_at=scanned_at,
                submitted_at=now,
                status=status,
                late_min=late,
                rate_snapshot=self._rate_for(user_id, d),
                source="manual",
            )
            a = self._insert(a)
        audit.record(self.repo, now, actor.user_id, "attendance.manual", "attendance", a.attendance_id,
                     None, a, reason.strip())
        return a

    def void(self, actor: User, attendance_id: str, reason: str) -> Attendance:
        if not reason.strip():
            raise AppError("REASON_REQUIRED", "Alasan wajib diisi.", 422)
        a = self.repo.attendance.get(attendance_id)
        if a is None:
            raise AppError("ATTENDANCE_NOT_FOUND", "Data absensi tidak ditemukan.", 404)
        if a.voided:
            raise AppError("ALREADY_VOIDED", "Data absensi ini sudah di-void.", 409)
        assert_not_final(self.repo, a.date, a.user_id)
        now = self.clock()
        voided = a.model_copy(update={"voided": True, "void_reason": reason.strip(), "voided_by": actor.user_id})
        self.repo.attendance.update(voided)
        audit.record(self.repo, now, actor.user_id, "attendance.void", "attendance", a.attendance_id, a, voided,
                     reason.strip())
        return voided
