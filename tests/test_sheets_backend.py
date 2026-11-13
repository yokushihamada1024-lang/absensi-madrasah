"""SheetsBackend diuji dengan klien gspread palsu: tidak butuh internet."""

import pytest

from core.attendance import AttendanceService
from core.repo.base import SCHEMA
from core.repo.memory import seed_defaults
from core.repo.sheets import SheetsBackend
from core.repo.tables import build_repository
from tests.conftest import JWT_SECRET, MADRASAH, QR_KEY, TODAY, make_user
from tests.fake_gspread import FakeClient
from tests.helpers import scan_submit


@pytest.fixture
def backend():
    client = FakeClient()
    b = SheetsBackend("sheet-id", client=client, sleep=lambda s: None)
    b.ensure_schema()
    return b


def test_bootstrap_idempotent(backend):
    assert set(backend.spreadsheet().sheets) == set(SCHEMA)
    assert backend.ensure_schema() == []  # kedua kali tidak ada aksi
    assert backend.spreadsheet().sheets["users"].data[0] == SCHEMA["users"]


def test_header_mismatch_detected(backend):
    backend.spreadsheet().sheets["kelas"].data[0] = ["nama", "aktif"]
    with pytest.raises(RuntimeError):
        backend.rows("kelas", fresh=True)


def test_append_update_and_cache(backend):
    n = backend.append("kelas", {"name": "Umar", "active": "TRUE"})
    assert n == 2
    assert backend.rows("kelas") == [(2, {"name": "Umar", "active": "TRUE"})]
    backend.update("kelas", 2, {"name": "Umar", "active": "FALSE"}, "name")
    assert backend.spreadsheet().sheets["kelas"].data[1] == ["Umar", "FALSE"]
    assert backend.rows("kelas")[0][1]["active"] == "FALSE"


def test_update_refuses_when_key_changed(backend):
    backend.append("kelas", {"name": "Umar", "active": "TRUE"})
    backend.spreadsheet().sheets["kelas"].data[1][0] = "Diubah Manual"
    with pytest.raises(RuntimeError):
        backend.update("kelas", 2, {"name": "Umar", "active": "FALSE"}, "name")


def test_retry_on_429(backend):
    ws = backend.spreadsheet().sheets["kelas"]
    ws.fail_next = [429, 503]
    backend.append("kelas", {"name": "Ali", "active": "TRUE"})
    assert ws.data[-1] == ["Ali", "TRUE"]


def test_non_retryable_error_raises(backend):
    import gspread

    ws = backend.spreadsheet().sheets["kelas"]
    ws.fail_next = [403]
    with pytest.raises(gspread.exceptions.APIError):
        backend.append("kelas", {"name": "Ali", "active": "TRUE"})


def test_full_flow_on_sheets_backend(backend, clock):
    repo = build_repository(backend)
    seed_defaults(repo)
    repo.settings.save(repo.settings.get().model_copy(update={"lat": MADRASAH[0], "lng": MADRASAH[1]}))
    admin = make_user(repo, "Admin", role="admin", rate=None)
    guru = make_user(repo, "Guru A")
    svc = AttendanceService(repo, clock, QR_KEY, JWT_SECRET)
    clock.set_wib(TODAY, "13:25")
    s = svc.open_session(admin, "S1")
    a = scan_submit(svc, clock, guru, s)
    # baris benar-benar ada di sheet palsu, sebagai string
    att_ws = backend.spreadsheet().sheets["attendance"]
    assert att_ws.data[1][0] == a.attendance_id
    assert att_ws.data[1][SCHEMA["attendance"].index("voided")] == "FALSE"
    # cek duplikat membaca ekor secara fresh
    assert any(c.startswith("get A") for c in att_ws.calls)
    svc.void(admin, a.attendance_id, "uji")
    assert att_ws.data[1][SCHEMA["attendance"].index("voided")] == "TRUE"
    # mirror dibuang → baca ulang dari "sheet" memberi hasil sama
    backend._cache.clear()
    got = repo.attendance.get(a.attendance_id)
    assert got.voided and got.rate_snapshot == 50000 and got.scanned_at == a.scanned_at
