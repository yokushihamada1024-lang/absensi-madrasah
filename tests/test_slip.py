import io
import zipfile
from datetime import UTC, date, datetime, timedelta

from pypdf import PdfReader

from core import payroll
from core.models import Attendance, Rate
from core.slip import build_slip_pdf, build_slips_zip
from tests.conftest import make_user
from tests.helpers import scan_submit

PRINTED = datetime(2026, 12, 1, 2, 0, tzinfo=UTC)
NAMES = {"S1": "Sesi 1", "S2": "Sesi 2"}


def pdf_text(data: bytes) -> tuple[str, int]:
    r = PdfReader(io.BytesIO(data))
    return "\n".join(p.extract_text() for p in r.pages), len(r.pages)


def attend(svc, clock, admin, user, d, code="S1", hhmm="13:25"):
    clock.set_wib(d, hhmm)
    s = svc.open_session(admin, code)
    a = scan_submit(svc, clock, user, s)
    svc.close_session(admin, s.session_id)
    return a


def test_slip_pdf_contains_name_and_total(svc, clock, admin, repo):
    g = make_user(repo, "Ustadzah Fatimah Az-Zahra", rate=75000)
    attend(svc, clock, admin, g, date(2026, 11, 3))
    attend(svc, clock, admin, g, date(2026, 11, 4), hhmm="13:40")  # telat
    attend(svc, clock, admin, g, date(2026, 11, 4), code="S2", hhmm="16:10")
    line = payroll.compute_line(repo, "2026-11", g)
    pdf = build_slip_pdf(line, "MDA Test", NAMES, PRINTED)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    text, pages = pdf_text(pdf)
    assert "Ustadzah Fatimah Az-Zahra" in text
    assert "SLIP GAJI GURU" in text and "November 2026" in text and "MDA Test" in text
    assert "Rp 225.000" in text  # 3 × 75.000
    assert "TAKE HOME PAY" in text
    assert "Terlambat 10 mnt" in text
    assert "DRAFT" in text
    assert pages == 1


def test_slip_final_label_and_rate_groups(svc, clock, admin, repo):
    g = make_user(repo, "Guru Tarif Ganda", rate=50000)
    attend(svc, clock, admin, g, date(2026, 11, 3))
    repo.rates.add(Rate(user_id=g.user_id, rate_per_meeting=60000, effective_from=date(2026, 11, 10),
                        set_by="a", set_at=datetime(2026, 11, 9, tzinfo=UTC)))
    attend(svc, clock, admin, g, date(2026, 11, 10))
    clock.set_wib(date(2026, 12, 1), "09:00")
    payroll.finalize(repo, "2026-11", g.user_id, admin, clock())
    line = payroll.compute_line(repo, "2026-11", g)
    text, _ = pdf_text(build_slip_pdf(line, "MDA", NAMES, PRINTED))
    assert "FINAL" in text and "DRAFT" not in text.replace("DRAFT dan", "")
    assert "1 × Rp 50.000" in text and "1 × Rp 60.000" in text
    assert "Rp 110.000" in text


def test_slip_multi_page_repeats_header(repo):
    from core.models import SessionInstance

    g = make_user(repo, "Guru Banyak", rate=10000)
    # 60 baris → lebih dari satu halaman
    base = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    for i in range(60):
        d = date(2026, 11, 1) + timedelta(days=i % 30)
        repo.sessions.create(SessionInstance(session_id=f"s{i}", date=d, code="S1" if i < 30 else "S2",
                                             scheduled_start=base, scheduled_end=base, opened_at=base, closed_at=base))
        repo.attendance.add(Attendance(
            attendance_id=f"a{i}", session_id=f"s{i}", date=d, code="S1" if i < 30 else "S2", user_id=g.user_id,
            teacher_name=g.name, kelas="Umar", mapel="Fikih", scanned_at=base + timedelta(days=i % 30),
            submitted_at=base, status="on_time", rate_snapshot=10000, source="manual"))
    line = payroll.compute_line(repo, "2026-11", g)
    assert line.meetings == 60
    text, pages = pdf_text(build_slip_pdf(line, "MDA", NAMES, PRINTED))
    assert pages >= 2
    # header tabel berulang di setiap halaman yang memuat tabel (ringkasan boleh pindah ke halaman sendiri)
    assert text.count("MATA PELAJARAN") >= 2
    assert "Rp 600.000" in text


def test_slip_empty_period(repo):
    g = make_user(repo, "Guru Kosong")
    text, _ = pdf_text(build_slip_pdf(payroll.compute_line(repo, "2026-11", g), "MDA", NAMES, PRINTED))
    assert "Tidak ada pertemuan" in text and "Rp 0" in text


def test_zip_contains_all_slips(svc, clock, admin, repo):
    g1, g2 = make_user(repo, "Guru Satu"), make_user(repo, "Guru Dua")
    attend(svc, clock, admin, g1, date(2026, 11, 3))
    lines = payroll.compute_period(repo, "2026-11")
    z = zipfile.ZipFile(io.BytesIO(build_slips_zip(lines, "MDA", NAMES, PRINTED)))
    names = sorted(z.namelist())
    assert names == sorted([f"slip-2026-11-{g1.username}.pdf", f"slip-2026-11-{g2.username}.pdf"])
    text, _ = pdf_text(z.read(f"slip-2026-11-{g1.username}.pdf"))
    assert "Guru Satu" in text and "Rp 50.000" in text


def test_slip_endpoints(clock):
    from fastapi.testclient import TestClient

    from api.config import AppConfig
    from api.main import create_app
    from core.repo.memory import InMemoryRepository
    from scripts.create_admin import create_admin
    from tests.conftest import JWT_SECRET, QR_KEY

    repo = InMemoryRepository()
    app = create_app(AppConfig(env="dev", repo_backend="memory", jwt_secret=JWT_SECRET, qr_master_key=QR_KEY,
                               allowed_origins=["https://a.example"]), repo=repo, clock=clock)
    c = TestClient(app)
    create_admin(repo, "admin", "Admin", "123456")
    def auth(u):
        tok = c.post("/api/auth/login", json={"username": u, "pin": "123456"}).json()["token"]
        return {"Authorization": f"Bearer {tok}"}

    h = auth("admin")
    uid = c.post("/api/admin/users", headers=h, json={"username": "gurux", "name": "Guru X", "pin": "123456",
                                                      "rate_per_meeting": 40000}).json()["user_id"]
    c.post("/api/admin/attendance/manual", headers=h, json={"user_id": uid, "date": "2026-11-10", "code": "S1",
                                                            "kelas": "Ali", "mapel": "Iqra", "reason": "uji"})
    r = c.get(f"/api/admin/payroll/2026-11/{uid}/slip.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    text, _ = pdf_text(r.content)
    assert "Guru X" in text and "Rp 40.000" in text
    z = c.get("/api/admin/payroll/2026-11/slips.zip", headers=h)
    assert z.status_code == 200 and zipfile.ZipFile(io.BytesIO(z.content)).namelist() == ["slip-2026-11-gurux.pdf"]
    # guru tidak boleh mengunduh slip
    hg = auth("gurux")
    assert c.get(f"/api/admin/payroll/2026-11/{uid}/slip.pdf", headers=hg).status_code == 403
