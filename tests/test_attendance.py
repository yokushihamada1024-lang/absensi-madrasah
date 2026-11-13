import threading
from datetime import timedelta

import pytest

from core.attendance import compute_status
from core.models import AppError
from tests.conftest import MADRASAH, TODAY, make_user
from tests.helpers import scan, scan_submit, stale_token


def open_s1(svc, clock, admin):
    clock.set_wib(TODAY, "13:20")
    return svc.open_session(admin, "S1")


# --- status telat --------------------------------------------------------


def test_compute_status_grace_boundary(svc, clock):
    from core.timeutil import wib_to_utc

    start = wib_to_utc(TODAY, "13:30")
    assert compute_status(start + timedelta(minutes=5, seconds=59), start, 5) == ("on_time", 0)
    assert compute_status(start + timedelta(minutes=6), start, 5) == ("late", 6)
    assert compute_status(start - timedelta(minutes=15), start, 5) == ("on_time", 0)


def test_minute_5_on_time_minute_6_late(svc, clock, admin, repo):
    s = open_s1(svc, clock, admin)
    g1, g2 = make_user(repo, "Guru B"), make_user(repo, "Guru C")
    clock.set_wib(TODAY, "13:35", seconds=30)
    a1 = scan_submit(svc, clock, g1, s)
    clock.set_wib(TODAY, "13:36")
    a2 = scan_submit(svc, clock, g2, s)
    assert (a1.status, a1.late_min) == ("on_time", 0)
    assert (a2.status, a2.late_min) == ("late", 6)


def test_scan_before_schedule_on_time(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "13:12")
    a = scan_submit(svc, clock, guru, s)
    assert a.status == "on_time" and a.late_min == 0


# --- jendela -------------------------------------------------------------


def test_scan_too_early_rejected(svc, clock, admin, guru):
    clock.set_wib(TODAY, "13:00")
    s = svc.open_session(admin, "S1")
    clock.set_wib(TODAY, "13:09")  # jendela mulai 13:10 (early_open 20)
    with pytest.raises(AppError) as e:
        scan(svc, clock, guru, s)
    assert e.value.code == "SESSION_CLOSED" and e.value.extra["detail"] == "not_started"


def test_scan_after_end_rejected(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "15:45")
    tok = svc.qr(s.session_id).token  # QR terakhir tepat di jam selesai
    clock.advance(seconds=10)
    with pytest.raises(AppError) as e:
        scan(svc, clock, guru, s, token=tok)
    assert e.value.code == "SESSION_CLOSED"


def test_session_auto_closed_after_end(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "15:45")
    assert [x.session_id for x in svc.active_sessions()] == [s.session_id]  # tepat jam selesai: masih terbuka
    clock.set_wib(TODAY, "15:46")
    assert svc.active_sessions() == []
    closed = repo.sessions.get(s.session_id)
    assert closed.closed_at == s.scheduled_end  # dicatat jam selesai terjadwal, bukan jam sekarang
    a = repo.audit.recent()[0]
    assert a.action == "session.auto_close" and a.actor == "sistem"
    with pytest.raises(AppError) as e:
        svc.qr(s.session_id)  # layar QR admin berhenti
    assert e.value.code == "SESSION_CLOSED"
    svc.active_sessions()  # tidak menutup/mencatat dua kali
    assert sum(1 for x in repo.audit.recent() if x.action == "session.auto_close") == 1
    with pytest.raises(AppError) as e:
        svc.open_session(admin, "S1")  # tidak bisa dibuka lagi setelah jam lewat
    assert e.value.code == "SESSION_OVER"


def test_auto_close_keeps_ticket_submit_valid(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "15:44")
    r = scan(svc, clock, guru, s)
    clock.set_wib(TODAY, "15:47")
    svc.active_sessions()  # memicu auto-close
    a = svc.submit(guru, r.ticket, "Umar", "Fikih")  # tiket dari sebelum jam selesai tetap sah
    assert a.session_id == s.session_id


def test_scan_after_close_rejected(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "13:40")
    tok = svc.qr(s.session_id).token
    svc.close_session(admin, s.session_id)
    clock.advance(seconds=1)
    with pytest.raises(AppError) as e:
        scan(svc, clock, guru, s, token=tok)
    assert e.value.code == "SESSION_CLOSED"


def test_open_requires_location(svc, clock, admin, repo):
    repo.settings.save(repo.settings.get().model_copy(update={"lat": None, "lng": None}))
    with pytest.raises(AppError) as e:
        svc.open_session(admin, "S1")
    assert e.value.code == "LOCATION_NOT_SET"


def test_open_is_idempotent_and_reopen(svc, clock, admin):
    s = open_s1(svc, clock, admin)
    assert svc.open_session(admin, "S1").session_id == s.session_id
    svc.close_session(admin, s.session_id)
    again = svc.open_session(admin, "S1")
    assert again.session_id == s.session_id and again.is_open


def test_submit_after_close_with_valid_ticket(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    r = scan(svc, clock, guru, s)
    svc.close_session(admin, s.session_id)
    clock.advance(minutes=2)
    a = svc.submit(guru, r.ticket, "Ali", "Iqra")
    assert a.session_id == s.session_id


# --- duplikat & idempoten -------------------------------------------------


def test_duplicate_scan_rejected(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    scan_submit(svc, clock, guru, s)
    with pytest.raises(AppError) as e:
        scan(svc, clock, guru, s)
    assert e.value.code == "ALREADY_ATTENDED"


def test_resubmit_same_ticket_idempotent(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    r = scan(svc, clock, guru, s)
    a1 = svc.submit(guru, r.ticket, "Umar", "Fikih")
    a2 = svc.submit(guru, r.ticket, "Umar", "Fikih")
    assert a1.attendance_id == a2.attendance_id
    assert len(repo.attendance.list()) == 1


def test_second_ticket_rejected(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    r1 = scan(svc, clock, guru, s)
    r2 = scan(svc, clock, guru, s)  # dua scan sebelum submit
    svc.submit(guru, r1.ticket, "Umar", "Fikih")
    with pytest.raises(AppError) as e:
        svc.submit(guru, r2.ticket, "Umar", "Fikih")
    assert e.value.code == "ALREADY_ATTENDED"
    assert len(repo.attendance.list()) == 1


def test_submit_uses_scanned_at_not_submit_time(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "13:34")
    r = scan(svc, clock, guru, s)
    clock.set_wib(TODAY, "13:38", seconds=50)  # submit 4 menit kemudian
    a = svc.submit(guru, r.ticket, "Umar", "Fikih")
    assert a.status == "on_time"
    assert a.scanned_at == r.scanned_at and a.submitted_at > a.scanned_at


def test_parallel_double_tap_one_row(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    tickets = [scan(svc, clock, guru, s).ticket for _ in range(2)]
    results, errors = [], []
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()
        try:
            results.append(svc.submit(guru, tickets[i % 2], "Umar", "Fikih"))
        except AppError as e:
            errors.append(e.code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    valid = [a for a in repo.attendance.list() if not a.voided]
    assert len(valid) == 1
    assert len(repo.attendance.list()) == 1
    assert {a.attendance_id for a in results} == {valid[0].attendance_id}
    assert set(errors) <= {"ALREADY_ATTENDED"}


def test_storage_rejects_duplicate_row(svc, clock, admin, guru, repo):
    """Lapisan terakhir: storage menolak baris valid kedua walau service dilewati."""
    from core.repo.base import DuplicateAttendanceError

    s = open_s1(svc, clock, admin)
    a = scan_submit(svc, clock, guru, s)
    with pytest.raises(DuplicateAttendanceError):
        repo.attendance.add(a.model_copy(update={"attendance_id": "dup-1", "ticket_id": "other"}))
    with pytest.raises(DuplicateAttendanceError):  # ticket_id dipakai ulang
        repo.attendance.add(a.model_copy(update={"attendance_id": "dup-2", "voided": True}))


def test_lost_race_same_ticket_returns_winner(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    r = scan(svc, clock, guru, s)
    a = svc.submit(guru, r.ticket, "Umar", "Fikih")
    clone = a.model_copy(update={"attendance_id": "x"})
    assert svc._insert(clone).attendance_id == a.attendance_id


def test_ticket_of_other_user_rejected(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    other = make_user(repo, "Guru Z")
    r = scan(svc, clock, guru, s)
    with pytest.raises(AppError) as e:
        svc.submit(other, r.ticket, "Umar", "Fikih")
    assert e.value.code == "TICKET_INVALID"


def test_invalid_kelas_rejected(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    r = scan(svc, clock, guru, s)
    with pytest.raises(AppError) as e:
        svc.submit(guru, r.ticket, "Kelas Fiktif", "Fikih")
    assert e.value.code == "INVALID_KELAS"


# --- token & lokasi di alur scan ----------------------------------------------


def test_stale_qr_rejected_and_logged(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    with pytest.raises(AppError) as e:
        scan(svc, clock, guru, s, token=stale_token(svc, s, clock))
    assert e.value.code == "TOKEN_EXPIRED"
    att = repo.attempts.recent()
    assert att[0].reason == "TOKEN_EXPIRED" and att[0].user_id == guru.user_id


def test_out_of_range_logged_with_distance(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    with pytest.raises(AppError) as e:
        scan(svc, clock, guru, s, lat=MADRASAH[0] + 0.0015)  # ±167 m
    assert e.value.code == "OUT_OF_RANGE"
    att = repo.attempts.recent()[0]
    assert att.reason == "OUT_OF_RANGE" and 160 < att.distance_m < 175
    assert att.session_id == s.session_id


def test_void_then_reattend_allowed(svc, clock, admin, guru):
    s = open_s1(svc, clock, admin)
    a = scan_submit(svc, clock, guru, s)
    svc.void(admin, a.attendance_id, "salah kelas")
    b = scan_submit(svc, clock, guru, s, kelas="Ali")
    assert b.attendance_id != a.attendance_id


def test_void_requires_reason_and_audits(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    a = scan_submit(svc, clock, guru, s)
    with pytest.raises(AppError) as e:
        svc.void(admin, a.attendance_id, "  ")
    assert e.value.code == "REASON_REQUIRED"
    svc.void(admin, a.attendance_id, "dobel")
    entry = repo.audit.recent()[0]
    assert entry.action == "attendance.void" and entry.reason == "dobel"
    assert '"voided": false' in entry.before_json and '"voided": true' in entry.after_json


def test_manual_entry_creates_closed_session(svc, clock, admin, guru, repo):
    d = TODAY - timedelta(days=3)
    a = svc.manual_entry(admin, guru.user_id, d, "S2", "Hafsah", "Tahfidz", "lupa scan", "16:30")
    assert a.source == "manual" and a.status == "late" and a.late_min == 15
    s = repo.sessions.find(d, "S2")
    assert s is not None and not s.is_open
    with pytest.raises(AppError) as e:
        svc.manual_entry(admin, guru.user_id, d, "S2", "Hafsah", "Tahfidz", "lagi")
    assert e.value.code == "ALREADY_ATTENDED"
    assert repo.audit.recent()[0].action == "attendance.manual"


# --- konfirmasi tanpa QR (fallback tombol) --------------------------------------


def allow_button(repo, on=True):
    repo.settings.save(repo.settings.get().model_copy(update={"allow_button_checkin": on}))


def confirm(svc, clock, user, session, lat=MADRASAH[0], lng=MADRASAH[1], acc=10.0):
    ms = clock().timestamp() * 1000
    return svc.confirm(user, session.session_id, lat, lng, acc, ms, ms)


def test_button_disabled_by_default_and_logged(svc, clock, admin, guru, repo):
    s = open_s1(svc, clock, admin)
    with pytest.raises(AppError) as e:
        confirm(svc, clock, guru, s)
    assert e.value.code == "BUTTON_DISABLED" and e.value.status == 403
    assert repo.attempts.recent()[0].reason == "BUTTON_DISABLED"


def test_button_checkin_records_source_button(svc, clock, admin, guru, repo):
    allow_button(repo)
    s = open_s1(svc, clock, admin)
    clock.set_wib(TODAY, "13:37")
    r = confirm(svc, clock, guru, s)
    assert r.method == "button"
    a = svc.submit(guru, r.ticket, "Umar", "Fikih")
    assert a.source == "button" and a.status == "late" and a.late_min == 7
    assert a.distance_m is not None and a.distance_m < 1
    assert repo.attendance.get(a.attendance_id).source == "button"


def test_button_checkin_enforces_radius(svc, clock, admin, guru, repo):
    allow_button(repo)
    s = open_s1(svc, clock, admin)
    with pytest.raises(AppError) as e:
        confirm(svc, clock, guru, s, lat=MADRASAH[0] + 0.0015)  # ±167 m
    assert e.value.code == "OUT_OF_RANGE"
    att = repo.attempts.recent()[0]
    assert att.reason == "OUT_OF_RANGE" and att.session_id == s.session_id


def test_button_checkin_enforces_accuracy_window_and_duplicate(svc, clock, admin, guru, repo):
    allow_button(repo)
    s = open_s1(svc, clock, admin)
    with pytest.raises(AppError) as e:
        confirm(svc, clock, guru, s, acc=200)
    assert e.value.code == "LOW_ACCURACY"
    scan_submit(svc, clock, guru, s)  # sudah absen lewat QR
    with pytest.raises(AppError) as e:
        confirm(svc, clock, guru, s)
    assert e.value.code == "ALREADY_ATTENDED"
    svc.close_session(admin, s.session_id)
    clock.advance(seconds=1)
    g2 = make_user(repo, "Guru Z")
    with pytest.raises(AppError) as e:
        confirm(svc, clock, g2, s)
    assert e.value.code == "SESSION_CLOSED"


def test_button_unknown_session(svc, clock, admin, guru, repo):
    allow_button(repo)
    open_s1(svc, clock, admin)
    ms = clock().timestamp() * 1000
    with pytest.raises(AppError) as e:
        svc.confirm(guru, "00000000-0000-0000-0000-000000000000", MADRASAH[0], MADRASAH[1], 10, ms, ms)
    assert e.value.code == "SESSION_NOT_FOUND"


def test_qr_scan_still_source_scan(svc, clock, admin, guru, repo):
    allow_button(repo)
    s = open_s1(svc, clock, admin)
    assert scan_submit(svc, clock, guru, s).source == "scan"


# --- buka sesi otomatis (fallback admin lupa) -------------------------------------


def auto_open(repo, on=True):
    repo.settings.save(repo.settings.get().model_copy(update={"auto_open_sessions": on}))


def test_auto_open_off_by_default(svc, clock, repo):
    clock.set_wib(TODAY, "13:30")
    assert svc.active_sessions() == []
    assert repo.sessions.find(TODAY, "S1") is None


def test_auto_open_respects_window(svc, clock, repo):
    auto_open(repo)
    clock.set_wib(TODAY, "13:09")  # jendela S1 mulai 13:10 (early_open 20)
    assert svc.active_sessions() == []
    clock.set_wib(TODAY, "13:10")
    [s] = svc.active_sessions()
    assert s.code == "S1" and s.opened_by == "sistem" and s.is_open
    assert svc.active_sessions()[0].session_id == s.session_id  # tidak dobel
    assert len(repo.sessions.list_by_date(TODAY)) == 1
    a = repo.audit.recent()[0]
    assert a.action == "session.auto_open" and a.actor == "sistem"
    clock.set_wib(TODAY, "17:31")  # setelah S2 selesai: S2 tidak dibuat
    svc.active_sessions()
    assert repo.sessions.find(TODAY, "S2") is None


def test_auto_open_then_attend_status_from_schedule(svc, clock, guru, repo):
    auto_open(repo)
    clock.set_wib(TODAY, "13:40")
    [s] = svc.active_sessions()
    a = scan_submit(svc, clock, guru, s)
    assert a.status == "late" and a.late_min == 10


def test_auto_open_does_not_reopen_closed_session(svc, clock, admin, repo):
    auto_open(repo)
    clock.set_wib(TODAY, "13:20")
    [s] = svc.active_sessions()
    svc.close_session(admin, s.session_id)
    clock.set_wib(TODAY, "13:30")
    assert svc.active_sessions() == []
    assert repo.sessions.get(s.session_id).closed_at is not None


def test_auto_open_requires_location(svc, clock, repo):
    auto_open(repo)
    repo.settings.save(repo.settings.get().model_copy(update={"lat": None, "lng": None}))
    clock.set_wib(TODAY, "13:30")
    assert svc.active_sessions() == []


def test_auto_open_with_button_checkin(svc, clock, guru, repo):
    auto_open(repo)
    allow_button(repo)
    clock.set_wib(TODAY, "16:15")
    [s] = svc.active_sessions()
    assert s.code == "S2"
    r = confirm(svc, clock, guru, s)
    assert svc.submit(guru, r.ticket, "Umar", "Fikih").source == "button"
