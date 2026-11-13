from datetime import UTC, date, datetime

import pytest

from core import payroll
from core.models import AppError, Rate, SessionDef
from core.repo.base import DEFAULT_SESSION_DEFS
from tests.conftest import TODAY
from tests.helpers import scan_submit


def set_rate(repo, user, amount, eff, set_at=datetime(2026, 1, 2, tzinfo=UTC)):
    repo.rates.add(Rate(user_id=user.user_id, rate_per_meeting=amount, effective_from=eff,
                        set_by="admin", set_at=set_at))


def attend(svc, clock, admin, user, d, code="S1", hhmm="13:25"):
    clock.set_wib(d, hhmm)
    s = svc.open_session(admin, code)
    a = scan_submit(svc, clock, user, s)
    svc.close_session(admin, s.session_id)
    return a


def test_rate_change_mid_month_keeps_old_rate(svc, clock, admin, guru, repo):
    a1 = attend(svc, clock, admin, guru, date(2026, 11, 3))
    set_rate(repo, guru, 75000, date(2026, 11, 10), datetime(2026, 11, 9, tzinfo=UTC))
    a2 = attend(svc, clock, admin, guru, date(2026, 11, 10))
    a3 = attend(svc, clock, admin, guru, date(2026, 11, 11), code="S2", hhmm="16:10")
    assert a1.rate_snapshot == 50000 and a2.rate_snapshot == 75000 and a3.rate_snapshot == 75000
    line = payroll.compute_line(repo, "2026-11", guru)
    assert line.meetings == 3 and line.gross == 200000 and line.take_home == 200000
    assert [(g.rate, g.meetings, g.subtotal) for g in line.rate_groups] == [(50000, 1, 50000), (75000, 2, 150000)]
    # mengubah tarif lagi tidak mengubah periode lalu
    set_rate(repo, guru, 100000, date(2026, 11, 1), datetime(2026, 11, 20, tzinfo=UTC))
    assert payroll.compute_line(repo, "2026-11", guru).gross == 200000


def test_rate_on_tie_breaker():
    r1 = Rate(user_id="u", rate_per_meeting=1, effective_from=date(2026, 1, 1), set_by="a",
              set_at=datetime(2026, 1, 1, tzinfo=UTC))
    r2 = r1.model_copy(update={"rate_per_meeting": 2, "set_at": datetime(2026, 1, 2, tzinfo=UTC)})
    assert payroll.rate_on([r1, r2], date(2026, 1, 1)).rate_per_meeting == 2
    assert payroll.rate_on([r1], date(2025, 12, 31)) is None


def test_void_reduces_meetings(svc, clock, admin, guru, repo):
    a = attend(svc, clock, admin, guru, date(2026, 11, 3))
    attend(svc, clock, admin, guru, date(2026, 11, 4))
    svc.void(admin, a.attendance_id, "salah")
    line = payroll.compute_line(repo, "2026-11", guru)
    assert line.meetings == 1 and line.take_home == 50000


def test_month_boundary_wib(svc, clock, admin, guru, repo):
    """23:30 WIB hari terakhir → bulan itu; 00:30 WIB tgl 1 (UTC masih bulan lalu) → bulan baru."""
    repo.meta.save_session_defs(DEFAULT_SESSION_DEFS + [
        SessionDef(code="M", name="Malam", start_hhmm="23:00", end_hhmm="23:59"),
        SessionDef(code="D", name="Dini", start_hhmm="00:15", end_hhmm="01:00"),
    ])
    a = attend(svc, clock, admin, guru, date(2026, 11, 30), code="M", hhmm="23:30")
    b = attend(svc, clock, admin, guru, date(2026, 12, 1), code="D", hhmm="00:30")
    assert a.scanned_at.month == 11 and a.date == date(2026, 11, 30)
    assert b.scanned_at.month == 11 and b.scanned_at.day == 30  # UTC masih November
    assert b.date == date(2026, 12, 1)
    clock.set_wib(date(2026, 12, 5), "10:00")
    assert payroll.compute_line(repo, "2026-11", guru).meetings == 1
    assert payroll.compute_line(repo, "2026-12", guru).meetings == 1


def test_final_period_blocks_void_and_manual(svc, clock, admin, guru, repo):
    a = attend(svc, clock, admin, guru, date(2026, 11, 3))
    clock.set_wib(date(2026, 12, 1), "09:00")
    p = payroll.finalize(repo, "2026-11", guru.user_id, admin, clock())
    assert p.status == "final" and p.take_home == 50000
    with pytest.raises(AppError) as e:
        svc.void(admin, a.attendance_id, "x")
    assert e.value.code == "PERIOD_FINAL"
    with pytest.raises(AppError) as e:
        svc.manual_entry(admin, guru.user_id, date(2026, 11, 5), "S1", "Umar", "Fikih", "x")
    assert e.value.code == "PERIOD_FINAL"
    with pytest.raises(AppError) as e:
        payroll.reopen(repo, "2026-11", guru.user_id, admin, "", clock())
    assert e.value.code == "REASON_REQUIRED"
    payroll.reopen(repo, "2026-11", guru.user_id, admin, "koreksi", clock())
    svc.void(admin, a.attendance_id, "koreksi")
    assert payroll.compute_line(repo, "2026-11", guru).take_home == 0
    actions = [e.action for e in repo.audit.recent()]
    assert "payroll.finalize" in actions and "payroll.reopen" in actions


def test_compute_period_lists_teachers(svc, clock, admin, guru, repo):
    attend(svc, clock, admin, guru, TODAY)
    lines = payroll.compute_period(repo, "2026-11")
    assert [ln.user.user_id for ln in lines] == [guru.user_id]
    assert lines[0].status == "draft"


def test_missing_rate_flag(svc, clock, admin, repo):
    from tests.conftest import make_user

    g = make_user(repo, "Tanpa Tarif", rate=None)
    a = attend(svc, clock, admin, g, TODAY)
    assert a.rate_snapshot == 0
    assert payroll.compute_line(repo, "2026-11", g).missing_rate
