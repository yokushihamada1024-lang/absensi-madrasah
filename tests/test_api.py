from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.config import AppConfig
from api.main import create_app
from core.repo.memory import InMemoryRepository
from core.security import hash_pin
from tests.conftest import JWT_SECRET, MADRASAH, QR_KEY, TODAY, FakeClock

GURU_ORIGIN = "https://absensi-guru.example"
ADMIN_ORIGIN = "https://absensi-admin.example"
PIN = "123456"


@pytest.fixture
def env(clock: FakeClock):
    repo = InMemoryRepository()
    repo.settings.save(repo.settings.get().model_copy(update={"lat": MADRASAH[0], "lng": MADRASAH[1]}))
    cfg = AppConfig(env="dev", repo_backend="memory", jwt_secret=JWT_SECRET, qr_master_key=QR_KEY,
                    allowed_origins=[GURU_ORIGIN, ADMIN_ORIGIN])
    app = create_app(cfg, repo=repo, clock=clock)
    client = TestClient(app)
    from scripts.create_admin import create_admin

    create_admin(repo, "admin", "Admin", PIN)
    h = login(client, "admin")
    for un, name in (("gurua", "Guru A"), ("gurub", "Guru B")):
        body = {"username": un, "name": name, "pin": PIN, "rate_per_meeting": 50000, "effective_from": "2026-01-01"}
        r = client.post("/api/admin/users", headers=h, json=body)
        assert r.status_code == 201, r.text
    return client, repo, clock


def login(client, username, pin=PIN, ip=None) -> dict:
    headers = {"x-forwarded-for": ip} if ip else {}
    r = client.post("/api/auth/login", json={"username": username, "pin": pin}, headers=headers)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def user_id(client, h) -> str:
    return client.get("/api/me", headers=h).json()["user_id"]


def open_and_scan(client, clock, h_admin, h_guru, lat=MADRASAH[0]):
    clock.set_wib(TODAY, "13:25")
    s = client.post("/api/admin/sessions/open", headers=h_admin, json={"code": "S1"}).json()
    qr = client.get(f"/api/admin/sessions/{s['session_id']}/qr", headers=h_admin).json()
    ms = clock().timestamp() * 1000
    r = client.post("/api/attendance/scan", headers=h_guru, json={
        "token": qr["token"], "lat": lat, "lng": MADRASAH[1], "accuracy_m": 12, "position_ts": ms, "client_ts": ms})
    return s, r


def test_healthz_no_auth(env):
    client, _, _ = env
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_full_flow(env):
    client, repo, clock = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    s, r = open_and_scan(client, clock, ha, hg)
    assert r.status_code == 200, r.text
    scan = r.json()
    assert scan["status_preview"] == "on_time" and scan["distance_m"] < 1
    qr = client.get(f"/api/admin/sessions/{s['session_id']}/qr", headers=ha).json()
    assert qr["svg"].startswith('<svg xmlns="http://www.w3.org/2000/svg"') and qr["rotate_sec"] == 30
    r = client.post("/api/attendance/submit", headers=hg, json={"ticket": scan["ticket"], "kelas": "Umar",
                                                                "mapel": "Fikih"})
    assert r.status_code == 200 and r.json()["kelas"] == "Umar"
    again = client.post("/api/attendance/submit", headers=hg, json={"ticket": scan["ticket"], "kelas": "Umar",
                                                                    "mapel": "Fikih"})
    assert again.json()["attendance_id"] == r.json()["attendance_id"]
    summ = client.get("/api/me/summary", headers=hg).json()
    assert summ["meetings"] == 1 and summ["estimated_gross"] == 50000 and summ["current_rate"] == 50000
    assert summ["today"]["sessions"][0]["attended"] is True
    assert summ["dates"] == [TODAY.isoformat()]
    today = client.get("/api/admin/attendance", headers=ha).json()
    assert len(today) == 1 and today[0]["teacher_name"] == "Guru A"
    pay = client.get("/api/admin/payroll?period=2026-11", headers=ha).json()
    assert pay["total_take_home"] == 50000


def test_scan_errors_have_codes(env):
    client, repo, clock = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    _, r = open_and_scan(client, clock, ha, hg, lat=MADRASAH[0] + 0.003)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "OUT_OF_RANGE" and 300 < err["distance_m"] < 360
    attempts = client.get("/api/admin/attempts", headers=ha).json()
    assert attempts[0]["reason"] == "OUT_OF_RANGE" and attempts[0]["teacher_name"] == "Guru A"


def test_guru_cannot_call_admin(env):
    client, _, _ = env
    hg = login(client, "gurua")
    for method, path in (("get", "/api/admin/users"), ("get", "/api/admin/attendance"),
                         ("post", "/api/admin/sessions/open"), ("get", "/api/admin/payroll"),
                         ("get", "/api/admin/settings"), ("get", "/api/admin/audit")):
        r = getattr(client, method)(path, headers=hg, **({"json": {"code": "S1"}} if method == "post" else {}))
        assert r.status_code == 403, (path, r.text)
        assert r.json()["error"]["code"] == "FORBIDDEN"


def test_admin_cannot_scan(env):
    client, _, _ = env
    r = client.post("/api/attendance/scan", headers=login(client, "admin"),
                    json={"token": "x", "lat": 0, "lng": 0, "accuracy_m": 1, "position_ts": 1})
    assert r.status_code == 403


def test_cross_access_guru_a_cannot_read_b(env):
    client, repo, clock = env
    ha, hb = login(client, "admin"), login(client, "gurub")
    _, r = open_and_scan(client, clock, ha, hb)
    client.post("/api/attendance/submit", headers=hb, json={"ticket": r.json()["ticket"], "kelas": "Ali",
                                                            "mapel": "Iqra"})
    hg = login(client, "gurua")
    summ = client.get("/api/me/summary", headers=hg).json()
    assert summ["meetings"] == 0 and summ["attendance"] == []
    assert summ["user"]["username"] == "gurua"
    # summary tidak menerima parameter user lain
    b_id = user_id(client, hb)
    summ2 = client.get(f"/api/me/summary?user_id={b_id}", headers=hg).json()
    assert summ2["meetings"] == 0
    # ticket B tidak bisa dipakai A
    r2 = client.post("/api/attendance/submit", headers=hg, json={"ticket": r.json()["ticket"], "kelas": "Ali",
                                                                 "mapel": "Iqra"})
    assert r2.status_code == 403
    assert "50000" not in json.dumps(client.get("/api/meta", headers=hg).json())


def test_unauthenticated(env):
    client, _, _ = env
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer xxx"}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_ticket_is_not_access_token(env):
    client, _, clock = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    _, r = open_and_scan(client, clock, ha, hg)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {r.json()['ticket']}"}).status_code == 401


def test_login_rate_limit(env):
    client, _, clock = env
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "gurua", "pin": "salah1"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "gurua", "pin": PIN})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert "retry-after" in r.headers
    # IP lain masih boleh, lalu setelah 1 menit IP pertama boleh lagi
    login(client, "gurua", ip="10.0.0.9")
    clock.advance(seconds=61)
    login(client, "gurua")


def test_login_rate_limit_per_username_across_ips(env):
    client, _, _ = env
    for i in range(20):
        client.post("/api/auth/login", json={"username": "gurub", "pin": "salah1"},
                    headers={"x-forwarded-for": f"10.1.0.{i}"})
    r = client.post("/api/auth/login", json={"username": "gurub", "pin": PIN}, headers={"x-forwarded-for": "10.9.9.9"})
    assert r.status_code == 429


def test_old_token_version_rejected_after_reset_pin(env):
    client, _, _ = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    uid = user_id(client, hg)
    assert client.post(f"/api/admin/users/{uid}/reset-pin", headers=ha, json={"pin": "654321"}).status_code == 200
    assert client.get("/api/me", headers=hg).status_code == 401
    login(client, "gurua", pin="654321")


def test_deactivate_revokes_token_and_login(env):
    client, _, _ = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    uid = user_id(client, hg)
    assert client.patch(f"/api/admin/users/{uid}", headers=ha, json={"active": False}).json()["active"] is False
    assert client.get("/api/me", headers=hg).status_code == 401
    assert client.post("/api/auth/login", json={"username": "gurua", "pin": PIN}).status_code == 401


def test_admin_cannot_deactivate_self(env):
    client, _, _ = env
    ha = login(client, "admin")
    r = client.patch(f"/api/admin/users/{user_id(client, ha)}", headers=ha, json={"active": False})
    assert r.status_code == 409


def test_cors_allowed_and_unknown_origin(env):
    client, _, _ = env
    ok = client.get("/healthz", headers={"Origin": GURU_ORIGIN})
    assert ok.headers.get("access-control-allow-origin") == GURU_ORIGIN
    assert "access-control-allow-credentials" not in ok.headers
    bad = client.get("/healthz", headers={"Origin": "https://jahat.example"})
    assert "access-control-allow-origin" not in bad.headers
    pre = client.options("/api/auth/login", headers={"Origin": ADMIN_ORIGIN, "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "authorization,content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == ADMIN_ORIGIN
    pre_bad = client.options("/api/auth/login", headers={"Origin": "https://jahat.example",
                                                         "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre_bad.headers


def test_security_headers(env):
    client, _, _ = env
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_body_size_limit(env):
    client, _, _ = env
    big = b"{" + b" " * 40_000 + b"}"
    r = client.post("/api/auth/login", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_pin_hash_never_returned(env):
    client, repo, clock = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    open_and_scan(client, clock, ha, hg)
    uid = user_id(client, hg)
    bodies = [client.get(p, headers=ha).text for p in
              ("/api/admin/users", "/api/admin/audit", "/api/admin/attendance", f"/api/admin/users/{uid}/rates")]
    bodies.append(client.post(f"/api/admin/users/{uid}/reset-pin", headers=ha, json={"pin": "999999"}).text)
    bodies.append(client.get("/api/admin/audit", headers=ha).text)
    for b in bodies:
        assert "pin_hash" not in b and "$argon2" not in b


def test_validation_error_format(env):
    client, _, _ = env
    r = client.post("/api/admin/users", headers=login(client, "admin"),
                    json={"username": "A!", "name": "x", "pin": "1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_guru_requires_rate(env):
    client, _, _ = env
    r = client.post("/api/admin/users", headers=login(client, "admin"),
                    json={"username": "guruc", "name": "Guru C", "pin": PIN})
    assert r.json()["error"]["code"] == "RATE_REQUIRED"


def test_settings_roundtrip_and_audit(env):
    client, _, _ = env
    ha = login(client, "admin")
    s = client.get("/api/admin/settings", headers=ha).json()
    s.update(radius_m=150, lat=-6.3, lng=106.9)
    s.pop("timezone")
    r = client.put("/api/admin/settings", headers=ha, json=s)
    assert r.status_code == 200 and r.json()["radius_m"] == 150
    assert client.get("/api/admin/audit", headers=ha).json()[0]["action"] == "settings.update"
    bad = dict(s, lng=None)
    assert client.put("/api/admin/settings", headers=ha, json=bad).status_code == 422


def test_kelas_upsert_never_deletes(env):
    client, _, _ = env
    ha = login(client, "admin")
    r = client.put("/api/admin/kelas", headers=ha, json={"items": [{"name": "Umar", "active": False},
                                                                  {"name": "Baru", "active": True}]})
    names = {i["name"]: i["active"] for i in r.json()}
    assert names["Umar"] is False and names["Baru"] is True and "Ali" in names
    meta = client.get("/api/meta", headers=login(client, "gurua")).json()
    assert "Umar" not in meta["kelas"] and "Baru" in meta["kelas"]


def test_manual_and_void_via_api(env):
    client, _, clock = env
    ha = login(client, "admin")
    uid = user_id(client, login(client, "gurua"))
    r = client.post("/api/admin/attendance/manual", headers=ha, json={
        "user_id": uid, "date": "2026-11-10", "code": "S1", "kelas": "Ali", "mapel": "Iqra",
        "time": "13:40", "reason": "HP rusak"})
    assert r.status_code == 201 and r.json()["status"] == "late" and r.json()["late_min"] == 10
    aid = r.json()["attendance_id"]
    assert client.post(f"/api/admin/attendance/{aid}/void", headers=ha, json={"reason": ""}).status_code == 422
    v = client.post(f"/api/admin/attendance/{aid}/void", headers=ha, json={"reason": "salah input"})
    assert v.json()["voided"] is True


def test_finalize_and_reopen_via_api(env):
    client, _, clock = env
    ha = login(client, "admin")
    uid = user_id(client, login(client, "gurua"))
    client.post("/api/admin/attendance/manual", headers=ha, json={
        "user_id": uid, "date": "2026-11-10", "code": "S1", "kelas": "Ali", "mapel": "Iqra", "reason": "x"})
    r = client.post(f"/api/admin/payroll/2026-11/{uid}/finalize", headers=ha)
    assert r.status_code == 200 and r.json()["status"] == "final"
    r = client.post("/api/admin/attendance/manual", headers=ha, json={
        "user_id": uid, "date": "2026-11-11", "code": "S1", "kelas": "Ali", "mapel": "Iqra", "reason": "x"})
    assert r.json()["error"]["code"] == "PERIOD_FINAL"
    r = client.post(f"/api/admin/payroll/2026-11/{uid}/reopen", headers=ha, json={"reason": "koreksi"})
    assert r.json()["status"] == "draft"


def test_production_config_guards():
    base = dict(jwt_secret="a" * 40, qr_master_key="b" * 40, allowed_origins=["https://x.example"],
                database_url="postgresql://x")
    AppConfig(env="production", repo_backend="postgres", **base).validate()
    for bad in (dict(repo_backend="memory"), dict(repo_backend="postgres", dev_fake_location=True),
                dict(repo_backend="postgres", jwt_secret="short"),
                dict(repo_backend="postgres", allowed_origins=["http://x.example"])):
        with pytest.raises(RuntimeError):
            AppConfig(env="production", **{**base, **bad}).validate()


def test_dev_router_absent_in_production(clock):
    cfg = AppConfig(env="production", repo_backend="postgres", jwt_secret="a" * 40, qr_master_key="b" * 40,
                    allowed_origins=["https://x.example"], database_url="postgresql://unused")
    app = create_app(cfg, repo=InMemoryRepository(), clock=clock)
    c = TestClient(app)
    assert c.get("/api/dev/config").status_code == 404
    assert c.get("/docs").status_code == 404
    assert c.get("/healthz").headers.get("strict-transport-security")


def test_hash_pin_used():
    assert hash_pin(PIN).startswith("$argon2")


def test_rate_limiter_purges_old_keys(clock):
    from api.ratelimit import LoginRateLimiter

    rl = LoginRateLimiter(clock)
    rl.MAX_KEYS = 50
    for i in range(40):
        rl.fail(f"acak{i}", "1.1.1.1")
    clock.advance(seconds=901)
    rl.fail("baru", "1.1.1.1")
    assert len(rl._fails) <= 2
    assert rl.retry_after("baru", "1.1.1.1") == 0


def test_button_checkin_via_api(env):
    client, repo, clock = env
    ha, hg = login(client, "admin"), login(client, "gurua")
    clock.set_wib(TODAY, "13:25")
    s = client.post("/api/admin/sessions/open", headers=ha, json={"code": "S1"}).json()
    ms = clock().timestamp() * 1000
    body = {"session_id": s["session_id"], "lat": MADRASAH[0], "lng": MADRASAH[1], "accuracy_m": 12,
            "position_ts": ms, "client_ts": ms}
    assert client.get("/api/me/summary", headers=hg).json()["button_checkin"] is False
    r = client.post("/api/attendance/confirm", headers=hg, json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "BUTTON_DISABLED"

    st = client.get("/api/admin/settings", headers=ha).json()
    st.pop("timezone")
    st["allow_button_checkin"] = True
    assert client.put("/api/admin/settings", headers=ha, json=st).json()["allow_button_checkin"] is True
    assert client.get("/api/me/summary", headers=hg).json()["button_checkin"] is True

    far = dict(body, lat=MADRASAH[0] + 0.003)
    r = client.post("/api/attendance/confirm", headers=hg, json=far)
    assert r.status_code == 422 and r.json()["error"]["code"] == "OUT_OF_RANGE"
    r = client.post("/api/attendance/confirm", headers=hg, json=body)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["method"] == "button" and t["session"]["session_id"] == s["session_id"]
    r = client.post("/api/attendance/submit", headers=hg, json={"ticket": t["ticket"], "kelas": "Umar",
                                                                "mapel": "Fikih"})
    assert r.status_code == 200 and r.json()["source"] == "button"
    rows = client.get("/api/admin/attendance", headers=ha).json()
    assert rows[0]["source"] == "button"
    # admin tidak boleh memakai endpoint guru
    assert client.post("/api/attendance/confirm", headers=ha, json=body).status_code == 403
