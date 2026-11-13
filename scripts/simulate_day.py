"""Simulasi 1 hari terhadap InMemoryRepository (demo & smoke test).

Pakai:  python -m scripts.simulate_day
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from core import tokens
from core.attendance import AttendanceService
from core.models import AppError, Rate, User
from core.money import format_rupiah
from core.payroll import compute_period
from core.repo.memory import InMemoryRepository
from core.timeutil import format_date_id, period_of, wib_hhmm, wib_to_utc

LAT, LNG = -6.175392, 106.827153
DAY = date(2026, 11, 13)


class Clock:
    def __init__(self) -> None:
        self.now = wib_to_utc(DAY, "13:20")

    def __call__(self) -> datetime:
        return self.now

    def at(self, hhmm: str, sec: int = 0) -> None:
        self.now = wib_to_utc(DAY, hhmm) + timedelta(seconds=sec)


def main() -> int:
    repo = InMemoryRepository()
    repo.settings.save(repo.settings.get().model_copy(update={"madrasah_name": "Madrasah Simulasi",
                                                              "lat": LAT, "lng": LNG}))
    clock = Clock()
    svc = AttendanceService(repo, clock, "sim-qr-key", "sim-jwt-secret")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    admin = User(user_id=str(uuid.uuid4()), username="admin", name="Admin", role="admin", pin_hash="-",
                 created_at=t0)
    repo.users.create(admin)
    guru = []
    for i, n in enumerate(["Ahmad", "Budi", "Citra", "Dewi", "Eko"], start=1):
        u = User(user_id=str(uuid.uuid4()), username=n.lower(), name=f"Ustadz/ah {n}", role="guru",
                 pin_hash="-", created_at=t0)
        repo.users.create(u)
        repo.rates.add(Rate(user_id=u.user_id, rate_per_meeting=50000 + i * 5000, effective_from=date(2026, 1, 1),
                            set_by=admin.user_id, set_at=t0))
        guru.append(u)

    def m_north(m: float) -> float:
        return LAT + m / 111_195

    def attempt(label: str, u: User, hhmm: str, sec: int = 0, lat: float = LAT, acc: float = 15,
                stale_slots: int = 0, kelas: str = "Umar", mapel: str = "Fikih") -> None:
        clock.at(hhmm, sec)
        rot = repo.settings.get().qr_rotate_sec
        slot = tokens.current_slot(clock(), rot) - stale_slots
        tok = tokens.make_qr_token(svc.qr_master_key, s.session_id, slot)
        ms = clock().timestamp() * 1000
        try:
            r = svc.scan(u, tok, lat, LNG, acc, ms, ms)
            a = svc.submit(u, r.ticket, kelas, mapel)
            st = "Tepat waktu" if a.status == "on_time" else f"Terlambat {a.late_min} mnt"
            print(f"  {hhmm}  {u.name:<18} OK      {st:<18} {a.kelas}/{a.mapel}  ({r.distance_m:.0f} m)  [{label}]")
        except AppError as e:
            print(f"  {hhmm}  {u.name:<18} DITOLAK {e.code:<18} {e.message}  [{label}]")

    print(f"Simulasi {format_date_id(DAY, with_day=True)} — {repo.settings.get().madrasah_name}")
    clock.at("13:20")
    s = svc.open_session(admin, "S1")
    print(f"Admin membuka Sesi 1 pukul {wib_hhmm(clock())} WIB (jadwal 13:30, grace 5 mnt)\n")
    attempt("datang awal", guru[0], "13:22")
    attempt("menit ke-5 masih tepat", guru[1], "13:35", 40)
    attempt("telat", guru[2], "13:47", kelas="Ali", mapel="Tahfidz")
    attempt("di luar radius ±250 m", guru[3], "13:31", lat=m_north(250))
    attempt("GPS lemah", guru[3], "13:32", acc=180)
    attempt("QR basi (foto dari WA)", guru[4], "13:33", stale_slots=3)
    attempt("coba lagi di lokasi", guru[3], "13:38", lat=m_north(40))
    attempt("scan dua kali", guru[0], "13:50")
    clock.at("15:45")
    svc.close_session(admin, s.session_id)
    attempt("setelah sesi ditutup", guru[4], "15:50")

    print("\nPercobaan gagal tercatat:")
    for a in reversed(repo.attempts.recent()):
        dist = f"{a.distance_m:.0f} m" if a.distance_m is not None else "-"
        print(f"  {wib_hhmm(a.ts)}  {next(u.name for u in guru if u.user_id == a.user_id):<18} {a.reason:<18} {dist}")

    print(f"\nRekap {period_of(DAY)} (estimasi):")
    total = 0
    for line in compute_period(repo, period_of(DAY), today=DAY):
        total += line.take_home
        print(f"  {line.user.name:<18} {line.meetings} pertemuan  {format_rupiah(line.take_home):>12}")
    print(f"  {'TOTAL':<18}              {format_rupiah(total):>12}")
    valid = [a for a in repo.attendance.list() if not a.voided]
    assert len(valid) == 4, "simulasi: harus ada 4 absensi valid"
    print("\nSmoke test OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
