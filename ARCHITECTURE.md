# ARCHITECTURE.md

## Gambaran

```
 [Static Site: PWA Guru  web/teacher] ──┐  HTTPS, CORS (2 origin), Authorization: Bearer
                                        ├──────────────> [Web Service: FastAPI  api/] ──> [Google Sheets]
 [Static Site: Admin Web web/admin]  ───┘                 1 instance, satu-satunya penulis
```

- Frontend = vanilla JS (ES modules), tanpa build framework. `web/shared/` disalin ke tiap site saat build; `config.js` dibuat dari env `API_BASE_URL`.
- API = FastAPI sinkron (threadpool). Logika bisnis ada di `core/` dan tidak tahu FastAPI maupun gspread.
- Data = Google Sheets lewat `SheetsRepository` (produksi) atau `InMemoryRepository` (test/dev).

## Alur absensi

```
Admin (layar QR)                  API                                Guru (PWA)
  | POST /admin/sessions/open ---> buat session_instance
  | GET  /admin/sessions/{id}/qr -> token slot sekarang + SVG (segno)
  |   (polling sesuai expires_at, ~30 dtk; layar Wake Lock)
  |                                                       <--- scan QR kamera + Geolocation
  |                               POST /attendance/scan <------ {token, lat, lng, accuracy_m, position_ts, client_ts}
  |                               1. verifikasi HMAC token, slot ∈ {now, now-1}
  |                               2. sesi terbuka & dalam jendela
  |                               3. belum absen di sesi ini
  |                               4. lokasi segar, akurasi ≤ 75 m, jarak ≤ radius
  |                               gagal → append `attempts`, kembalikan kode error
  |                               lolos → ticket JWT 5 menit (scanned_at, jarak, akurasi)
  |                               POST /attendance/submit <---- {ticket, kelas, mapel}
  |                               lock(session,user) → cek fresh → append attendance
  |                               (rate_snapshot, status telat dari scanned_at) → verifikasi
  |                                                       ----> konfirmasi status
```

## Modul

| Modul | Isi |
|---|---|
| `core/timeutil.py` | UTC ISO-8601, konversi WIB, nama bulan Indonesia, batas periode |
| `core/money.py` | format Rupiah tanpa locale |
| `core/tokens.py` | token QR HMAC berputar, ticket JWT |
| `core/geo.py` | haversine, validasi lokasi |
| `core/models.py` | model pydantic (User, Rate, SessionInstance, Attendance, …) + `AppError` |
| `core/attendance.py` | sesi (buka/tutup/QR), scan, submit, input manual, void |
| `core/payroll.py` | tarif berlaku, rekap periode, finalisasi/buka kembali |
| `core/slip.py` | slip gaji PDF (reportlab) + ZIP |
| `core/repo/base.py` | interface repository per entitas |
| `core/repo/tables.py` | implementasi entitas di atas table backend generik |
| `core/repo/memory.py` | backend in-memory (test/dev) |
| `core/repo/sheets.py` | backend Google Sheets (gspread, cache TTL, retry/backoff) |
| `api/` | FastAPI: config, auth (argon2, JWT, rate-limit), deps, routers, middleware keamanan |
| `web/shared/` | `api.js` (timeout 90 dtk + retry), `format.js` |
| `web/teacher/` | PWA guru (login, beranda, scan, konfirmasi, riwayat), manifest, service worker, `vendor/qr-scanner` |
| `web/admin/` | admin web (dashboard, sesi & QR, guru, absensi, pengaturan + peta OSM, penggajian, log), `vendor/leaflet` |
| `scripts/` | `bootstrap_sheets`, `create_admin`, `simulate_day`, `dev_server`, `build_web`, `make_icons` |

## Risiko utama

| Risiko | Mitigasi |
|---|---|
| GPS palsu (mock location) | Tidak bisa dideteksi dari web. QR berputar 30 dtk = pertahanan utama; geofence lapisan tambahan; semua kegagalan dicatat di `attempts`. |
| Guru di rumah dikirimi QR live oleh rekan (video call/foto cepat) | Token hidup ≤60 dtk + geofence. Sisa risiko diterima; pola terlihat di `attempts`. |
| Kuota/latensi Google Sheets | Cache TTL, mirror attendance, baca ekor saja untuk cek duplikat, retry backoff 429/5xx. |
| Cold start Render Free (30–60 dtk) | `/healthz` tanpa Sheets, ping cron 13:25 & 16:00 WIB, polling QR menjaga API terjaga, klien timeout 90 dtk + retry + pesan "Menghubungkan ke server…". |
| Lebih dari 1 instance API | Lock & cache in-process jadi tidak konsisten → `render.yaml` mengunci 1 instance; didokumentasikan. |
| Sheets bukan database transaksional | Lock in-process + verifikasi setelah tulis + auto-void duplikat. |
| Token JWT dicuri via XSS | Tanpa script pihak ketiga, tanpa `innerHTML` data server, CSP ketat. |
| Data gaji di spreadsheet | Hanya owner + service account yang diberi akses (README). |
