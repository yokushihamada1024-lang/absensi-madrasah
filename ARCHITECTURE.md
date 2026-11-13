# ARCHITECTURE.md

## Gambaran

```
 [Static Site: PWA Guru  web/teacher] ──┐  HTTPS, CORS (2 origin), Authorization: Bearer
                                        ├──────────────> [Web Service: FastAPI  api/] ──> [Supabase Postgres]
 [Static Site: Admin Web web/admin]  ───┘                 1 instance, satu-satunya penulis
```

- Frontend = vanilla JS (ES modules), tanpa build framework. `web/shared/` disalin ke tiap site saat build; `config.js` dibuat dari env `API_BASE_URL`.
- API = FastAPI sinkron (threadpool). Logika bisnis ada di `core/` dan tidak tahu FastAPI maupun gspread.
- Data = Supabase Postgres (free tier, session pooler) lewat `PostgresRepository` (produksi) atau `InMemoryRepository` (test/dev). Tabel di schema `absensi`, RLS aktif tanpa policy.

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
  |                               lock(session,user) → cek → INSERT attendance
  |                               (rate_snapshot, status telat dari scanned_at);
  |                               partial unique index menolak duplikat
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
| `core/repo/tables.py` + `memory.py` | InMemoryRepository (test/dev) |
| `core/repo/postgres.py` | PostgresRepository (psycopg 3, pool kecil) |
| `db/schema.sql` | skema Postgres idempoten (`scripts.migrate`) |
| `api/` | FastAPI: config, auth (argon2, JWT, rate-limit), deps, routers, middleware keamanan |
| `web/shared/` | `api.js` (timeout 90 dtk + retry), `format.js` |
| `web/teacher/` | PWA guru (login, beranda, scan, konfirmasi, riwayat), manifest, service worker, `vendor/qr-scanner` |
| `web/admin/` | admin web (dashboard, sesi & QR, guru, absensi, pengaturan + peta OSM, penggajian, log), `vendor/leaflet` |
| `scripts/` | `migrate`, `create_admin`, `simulate_day`, `dev_server`, `build_web`, `make_icons` |

## Risiko utama

| Risiko | Mitigasi |
|---|---|
| GPS palsu (mock location) | Tidak bisa dideteksi dari web. QR berputar 30 dtk = pertahanan utama; geofence lapisan tambahan; semua kegagalan dicatat di `attempts`. |
| Guru di rumah dikirimi QR live oleh rekan (video call/foto cepat) | Token hidup ≤60 dtk + geofence. Sisa risiko diterima; pola terlihat di `attempts`. |
| Batas Supabase free tier (koneksi pooler, pause saat lama tak aktif, tanpa backup otomatis) | Pool max 4, `check_connection`, `pg_dump` bulanan (README). |
| Cold start Render Free (30–60 dtk) | `/healthz` tanpa database, ping cron 13:25 & 16:00 WIB, polling QR menjaga API terjaga, klien timeout 90 dtk + retry + pesan "Menghubungkan ke server…". |
| Lebih dari 1 instance API | Lock & cache in-process jadi tidak konsisten → `render.yaml` mengunci 1 instance; didokumentasikan. |
| Duplikat absensi karena balapan | Partial unique index di Postgres + lock in-process + idempotensi ticket. |
| Token JWT dicuri via XSS | Tanpa script pihak ketiga, tanpa `innerHTML` data server, CSP ketat. |
| Data gaji di spreadsheet | Hanya owner + service account yang diberi akses (README). |
