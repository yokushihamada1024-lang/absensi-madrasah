# PROMPT UNTUK CLAUDE CODE — Sistem Absensi & Penggajian Guru Madrasah

> Cara pakai: taruh file ini di repo kosong (mis. `PROMPT.md`), jalankan Claude Code (Opus 5.5, reasoning high), lalu ketik:
> `Baca PROMPT.md sampai habis lalu kerjakan sesuai Bagian 16 (Fase Kerja). Mulai dari Fase 0.`

---

Kamu adalah senior engineer yang membangun **MVP** sistem absensi + penggajian guru untuk satu madrasah. Baca seluruh dokumen ini sebelum menulis kode.

Aturan main:
- **Jangan bertanya di tengah jalan** kecuali ada kontradiksi yang benar-benar memblokir. Untuk hal yang belum ditentukan, pakai default di Bagian 17 dan catat keputusanmu di `DECISIONS.md`.
- **Jangan menambah fitur di luar Bagian 3 (scope MVP).** Kalau menurutmu ada fitur penting yang terlewat, tulis di `DECISIONS.md` bagian "Usulan", jangan dibangun.
- Kerjakan per fase (Bagian 16). Tiap fase: kode + test lulus + commit. Jangan lompat fase.
- Kalau ada instruksi di sini yang menurutmu salah secara teknis, kerjakan versi yang lebih aman/sederhana, lalu jelaskan alasannya di `DECISIONS.md`.

---

## 1. Konteks & skala

- 1 madrasah, ±10–50 guru, 1–3 admin, 2 sesi per hari: **Sesi 1 = 13:30–15:45, Sesi 2 = 16:15–17:30 (WIB)**.
- Kelas: Utsman, Aisyah, Abu Bakar, Khadijah, Fatimah, Hafsah, Umar, Ali.
- Mata pelajaran: Bahasa Arab, Fikih, Iqra, Tahsin, Tahfidz.
- Guru absen dengan **scan QR yang tampil di layar admin di madrasah**, harus berada dalam **radius 100 m** dari titik madrasah.
- Data disimpan di **Google Sheets** (service account). Skala ini aman untuk Sheets; arsitektur harus tetap memudahkan pindah ke Postgres nanti (lihat repository pattern di Bagian 2).
- Bahasa UI: **Indonesia**. Zona waktu: **Asia/Jakarta (WIB)**.

## 2. Keputusan arsitektur (TERKUNCI — jangan diubah)

```
 [Static Site: PWA Guru]  ──┐   HTTPS + CORS + Bearer token
                            ├────────────────> [Web Service: FastAPI] ──> [Google Sheets]
 [Static Site: Admin Web] ──┘                  (satu-satunya yang menyentuh Sheets)
```

Tiga deployable di Render, semuanya tipe **Free**: 2 Static Site + 1 Web Service.

1. **FastAPI = satu-satunya komponen yang membaca/menulis Google Sheets.** Kedua frontend hanyalah API client (HTTP). Alasan: satu penulis → tidak ada race condition antar-proses, cache konsisten, kredensial Google hanya ada di satu tempat.
2. **PWA guru = Static Site** (`web/teacher`, vanilla JS, ES modules, **tanpa build step framework**). Installable PWA, scan kamera live.
3. **Admin = Static Site kedua** (`web/admin`, vanilla JS, ES modules, tanpa build step framework). Web biasa, bukan PWA. **Tidak ada Streamlit.**
   - Kode yang dipakai bersama (API client, format Rupiah/tanggal) ada di `web/shared/` dan **disalin ke tiap site lewat build command** (mis. `cp -r web/shared web/teacher/shared`), karena Static Site hanya mempublikasikan satu direktori. Import relatif (`./shared/api.js`).
   - Alamat API dimasukkan lewat `config.js` yang dibuat saat build dari env var `API_BASE_URL` (mis. `echo "export const API_BASE_URL='$API_BASE_URL'" > web/teacher/config.js`).
4. **Repository pattern**: semua akses data lewat interface `Repository` (mis. `UserRepo`, `AttendanceRepo`, …). Sediakan 2 implementasi: `InMemoryRepository` (untuk test) dan `SheetsRepository` (produksi). Logika bisnis TIDAK boleh tahu soal gspread.
5. **Tech stack backend:** Python 3.12, FastAPI, uvicorn, pydantic v2, gspread + google-auth, PyJWT, argon2-cffi, reportlab (PDF murni Python, tanpa dependensi sistem), segno (render QR jadi SVG di server), pytest, ruff. **Frontend:** JS murni; scanner QR di PWA guru memakai library yang aktif dirawat (mis. `qr-scanner`), **vendor-kan filenya ke `web/teacher/vendor/`** (jangan CDN), catat versi + lisensi.
6. **Deployment (TERKUNCI):** semuanya di **Render Free**, didefinisikan di `render.yaml` (blueprint). Aturan:
   - API: **tepat 1 instance** (jangan aktifkan scaling horizontal) agar lock in-process & cache konsisten. Catat di README.
   - Filesystem Render **ephemeral** — jangan simpan apa pun di disk (semua data di Sheets).
   - HTTPS otomatis dari Render (`*.onrender.com`) sudah memenuhi syarat secure context untuk kamera & geolokasi.
   - **Hanya Web Service (API) yang bisa tidur.** Free web service di-spin down setelah 15 menit tanpa trafik dan butuh ±30–60 detik untuk bangun; Static Site tidak tidur sehingga halaman PWA/admin selalu langsung terbuka dan hanya panggilan API pertama yang bisa lambat. Strategi pemanasan terjadwal ada di Bagian 15. Kode **wajib tahan cold start** (Bagian 9 dan 10).
   - **CORS:** API hanya mengizinkan origin persis dari kedua Static Site (env `ALLOWED_ORIGINS`), `allow_credentials=False`, header yang diizinkan `Authorization` dan `Content-Type`. **Tidak pakai cookie** (origin berbeda → cookie lintas-situs tidak andal); autentikasi lewat header `Authorization: Bearer`.
   - **Jangan** memakai rewrite/proxy Static Site untuk meneruskan `/api/*` (lebih lambat dan menambah titik gagal saat cold start); frontend memanggil `API_BASE_URL` langsung.
   - Sediakan endpoint `GET /healthz` (tanpa auth, tanpa menyentuh Sheets) untuk health check Render dan pemanasan.

## 3. Scope

### MVP (WAJIB)
- Login 2 role: `admin`, `guru`.
- Admin membuka sesi → sistem menampilkan QR yang **berganti otomatis tiap 30 detik**.
- Guru scan QR di PWA → validasi token + geofence 100 m → pilih Kelas & Mata Pelajaran → absensi tersimpan dengan timestamp server, status tepat waktu/telat, menit telat.
- Dashboard guru: tanggal-tanggal hadir bulan ini, jumlah pertemuan, tarif per pertemuan, estimasi gaji berjalan.
- Admin: kelola guru (CRUD, reset PIN, aktif/nonaktif), atur tarif per pertemuan per guru, atur titik lokasi/radius/jam sesi/daftar kelas & mapel, lihat absensi hari ini, **input manual & void absensi (dengan alasan + audit log)**, rekap gaji bulanan, **cetak slip gaji PDF** (satu guru / semua guru jadi ZIP), finalisasi periode.

### OUT OF SCOPE (JANGAN dibangun)
- Potongan keterlambatan, bonus, tunjangan, pajak, BPJS (struktur data boleh disiapkan, fitur jangan).
- Jadwal mengajar per guru, notifikasi push/WhatsApp, offline-mode absensi, face recognition, deteksi mock-GPS native, multi-madrasah, multi-bahasa.
- Tarif berbeda per mapel/kelas (tarif hanya per guru).

## 4. Alur utama

1. **Admin** buka halaman "Sesi & QR" → pilih Sesi 1/2 → klik **Mulai Sesi**. Sistem membuat `session_instance` (tanggal, kode sesi, jam mulai terjadwal dari pengaturan, `opened_at`). Layar menampilkan QR besar yang auto-refresh (polling API tiap `QR_ROTATE_SEC`), countdown, dan tombol **Tutup Sesi**. Halaman ini **harus tetap terbuka selama sesi** (QR berputar, jadi guru butuh layar yang hidup) — pakai Screen Wake Lock API agar layar tidak mati.
2. **Guru** buka PWA → (sudah login) → tekan **Scan Absen** → izinkan kamera + lokasi → arahkan ke QR.
3. PWA mengirim `POST /api/attendance/scan` berisi token QR + koordinat + akurasi + timestamp posisi.
4. Server memvalidasi (Bagian 6). Jika lolos → server mengembalikan **ticket** (JWT pendek 5 menit, berisi `session_id`, `user_id`, `scanned_at`, `distance_m`, `accuracy_m`, `ticket_id`).
5. Guru memilih **Kelas** dan **Mata Pelajaran** → `POST /api/attendance/submit` dengan ticket → baris `attendance` ditulis. **Waktu kehadiran = `scanned_at` (saat scan lolos), bukan saat form disubmit**, supaya guru tidak bisa "menunda" status telat.
6. Guru melihat konfirmasi: status (Tepat waktu / Terlambat X menit), jam, kelas, mapel.

## 5. Aturan bisnis

- **Satu pertemuan** = satu baris `attendance` valid (`voided=false`). Unik per `(session_id, user_id)`: satu guru maksimal 1 absensi per sesi per hari. Percobaan kedua → error `ALREADY_ATTENDED` (idempoten: submit ulang dengan ticket yang sama mengembalikan hasil yang sama, bukan duplikat).
- **Telat:** `diff_min = floor((scanned_at - scheduled_start) / 60 detik)`. Jika `diff_min > GRACE_MIN` → `status="late"`, `late_min=diff_min`; selain itu `status="on_time"`, `late_min=0`. Scan lebih awal dari `scheduled_start` tetap `on_time`.
- **Jendela scan valid:** dari `scheduled_start - EARLY_OPEN_MIN` sampai `min(scheduled_end, closed_at)`. Di luar itu → `SESSION_CLOSED`.
- **Tarif:** tabel `rates` menyimpan riwayat `(user_id, rate_per_meeting, effective_from)`. Saat absensi ditulis, **tarif yang berlaku saat itu di-snapshot ke kolom `rate_snapshot`** di baris `attendance`. Mengubah tarif **tidak boleh** mengubah absensi/slip periode lalu.
- **Gaji periode** (bulan, dihitung dalam WIB berdasarkan kolom `date`): `meetings = count(attendance valid)`, `gross = sum(rate_snapshot)`, `take_home = gross` (MVP tanpa potongan).
- **Void/manual entry oleh admin:** wajib isi alasan, tercatat di `audit_log` (siapa, kapan, sebelum/sesudah). Absensi manual memakai `source="manual"` dan tarif yang berlaku pada tanggal tersebut.
- **Finalisasi periode:** admin menandai slip `(period, user)` sebagai `final` → menyimpan snapshot angka di `payslips`. Void/manual entry pada periode+guru yang sudah final **ditolak** kecuali admin melakukan "buka kembali" (dengan alasan, tercatat audit).
- **Waktu:** semua timestamp disimpan **UTC ISO-8601**; tampil & batas bulan dihitung di **Asia/Jakarta**. Wajib ada test untuk absensi pukul 23:30 WIB di hari terakhir bulan (secara UTC sudah bulan berikutnya).
- Format uang: `Rp 1.250.000` (titik ribuan, tanpa desimal), bulan dalam Bahasa Indonesia, **tanpa bergantung pada locale OS**.

## 6. Anti-kecurangan (inti sistem — implementasikan dengan teliti)

### 6.1 QR token (pertahanan utama)
- Kunci per sesi diturunkan: `key = HMAC_SHA256(QR_MASTER_KEY, session_id)` (tidak disimpan di Sheets).
- `slot = floor(unix_time / QR_ROTATE_SEC)` (default 30).
- Payload QR = `base64url(session_id) . slot . base64url(HMAC_SHA256(key, f"{session_id}.{slot}")[:16])`.
- Validasi server: signature cocok (`hmac.compare_digest`), `slot ∈ {current, current-1}` (jadi token hidup ±30–60 dtk), sesi terbuka.
- Tujuan: foto QR yang dikirim lewat WhatsApp jadi basi dalam hitungan detik.
- Endpoint admin `GET /api/admin/sessions/{id}/qr` mengembalikan `{token, svg, expires_at, rotate_sec}` untuk slot sekarang (`svg` dirender server dengan segno). Frontend admin menampilkannya lewat `Blob` + `<img>` (bukan `innerHTML`) dan menjadwalkan polling berikutnya dari `expires_at`.

### 6.2 Geofence (pertahanan kedua)
- Titik madrasah `(lat, lng)` dan `RADIUS_M` (default 100) dari settings.
- Jarak dengan **haversine**.
- Lolos jika **`accuracy_m <= MAX_ACCURACY_M` (default 75) DAN `distance_m <= RADIUS_M`**.
- Tolak `STALE_LOCATION` jika `|server_now - position_timestamp| > 30 detik`.
- Kode error yang dikembalikan: `TOKEN_INVALID`, `TOKEN_EXPIRED`, `SESSION_CLOSED`, `OUT_OF_RANGE` (sertakan `distance_m` untuk pesan "Anda ±340 m dari madrasah"), `LOW_ACCURACY`, `STALE_LOCATION`, `ALREADY_ATTENDED`.
- **Setiap percobaan gagal dicatat** di tab `attempts` (waktu, user, sesi, alasan, jarak, akurasi) agar admin bisa melihat pola.
- **Batasan jujur (tulis di README):** GPS dari browser bisa dipalsukan (mock location) dan tidak bisa dideteksi dari web. Karena itu QR yang berputar adalah pertahanan utama; geofence adalah lapisan tambahan. Jangan klaim sistem ini "anti-curang 100%".

## 7. Model data Google Sheets

Satu spreadsheet, tiap tab = satu tabel. Baris 1 = header. Semua ID = UUID4 kecuali dinyatakan lain. Sediakan `python -m scripts.bootstrap_sheets` (idempoten: buat tab + header jika belum ada) dan `python -m scripts.create_admin` (buat admin pertama).

| Tab | Kolom |
|---|---|
| `settings` | `key`, `value` (madrasah_name, lat, lng, radius_m, max_accuracy_m, qr_rotate_sec, grace_min, early_open_min, timezone) |
| `session_defs` | `code` (S1/S2), `name`, `start_hhmm`, `end_hhmm` |
| `kelas` | `name`, `active` |
| `mapel` | `name`, `active` |
| `users` | `user_id`, `username`, `name`, `role` (admin/guru), `pin_hash`, `token_version`, `active`, `created_at` |
| `rates` | `user_id`, `rate_per_meeting` (int rupiah), `effective_from` (date), `set_by`, `set_at` |
| `session_instances` | `session_id`, `date`, `code`, `scheduled_start` (UTC ISO), `scheduled_end`, `opened_at`, `opened_by`, `closed_at` |
| `attendance` | `attendance_id`, `session_id`, `date` (WIB), `code`, `user_id`, `teacher_name`, `kelas`, `mapel`, `scanned_at`, `submitted_at`, `lat`, `lng`, `accuracy_m`, `distance_m`, `status`, `late_min`, `rate_snapshot`, `source` (scan/manual), `voided`, `void_reason`, `voided_by`, `ticket_id` |
| `attempts` | `ts`, `user_id`, `session_id`, `reason`, `distance_m`, `accuracy_m` |
| `payslips` | `period` (YYYY-MM), `user_id`, `meetings`, `gross`, `take_home`, `status` (draft/final), `finalized_at`, `finalized_by`, `snapshot_json` |
| `audit_log` | `ts`, `actor`, `action`, `entity`, `entity_id`, `before_json`, `after_json`, `reason` |

Aturan akses Sheets (penting untuk performa & kuota):
- Kuota Sheets API per menit terbatas dan tiap panggilan lambat (ratusan ms). **Batch read per tab** (`get_all_records` sekali), **cache TTL 30 detik** untuk tab statis (`settings`, `users`, `rates`, `kelas`, `mapel`, `session_defs`), invalidate saat ada tulis.
- Untuk `attendance`: tulis dengan **append**; cek duplikat dengan **baca fresh baris sesi aktif** (jangan cache lama), dibungkus `threading.Lock` per `(session_id,user_id)` + verifikasi setelah tulis (jika ternyata ada duplikat, tandai yang kedua `voided=true` dengan alasan `auto-duplicate`).
- Tambahkan retry dengan exponential backoff untuk HTTP 429/5xx.
- Jangan pernah mengurutkan/menghapus baris di Sheets secara programatik; void = tandai kolom, bukan hapus.

## 8. Spesifikasi API (FastAPI, prefix `/api`)

Auth: username + PIN (min 6 digit/karakter), hash **argon2**. Login mengembalikan JWT (HS256, `JWT_SECRET`) yang dikirim frontend di header `Authorization: Bearer`. JWT memuat `user_id`, `role`, `token_version`; **mengubah/reset PIN atau menonaktifkan user menaikkan `token_version`** sehingga token lama langsung ditolak. Masa berlaku: guru 30 hari (disimpan di `localStorage` agar tidak login terus), admin 8 jam (disimpan di `sessionStorage`). Mitigasi XSS wajib: tanpa script pihak ketiga, tanpa `innerHTML` dengan data server, `Content-Security-Policy` ketat di kedua Static Site (lewat custom headers `render.yaml`). Rate-limit login (mis. 5 gagal/menit per username+IP, in-memory).

Guru:
- `POST /auth/login`, `POST /auth/logout`, `GET /me`
- `GET /me/summary?month=YYYY-MM` → profil, daftar absensi bulan itu, `meetings`, `current_rate`, `estimated_gross`
- `GET /sessions/active` → sesi yang sedang terbuka (tanpa token/secret)
- `POST /attendance/scan` → `{token, lat, lng, accuracy_m, position_ts}` → ticket atau error code
- `POST /attendance/submit` → `{ticket, kelas, mapel}`
- `GET /meta` → daftar kelas & mapel aktif

Admin (role `admin` saja; guru yang memanggil → 403):
- `POST /admin/sessions/open` `{code}`, `POST /admin/sessions/{id}/close`, `GET /admin/sessions/{id}/qr`, `GET /admin/sessions/today`
- `GET/POST/PATCH /admin/users`, `POST /admin/users/{id}/reset-pin`
- `PUT /admin/users/{id}/rate` `{rate_per_meeting, effective_from}`, `GET /admin/users/{id}/rates`
- `GET/PUT /admin/settings`, `GET/PUT /admin/kelas`, `GET/PUT /admin/mapel`, `GET/PUT /admin/session-defs`
- `GET /admin/attendance?date=&user_id=&from=&to=`, `POST /admin/attendance/manual`, `POST /admin/attendance/{id}/void`
- `GET /admin/payroll?period=YYYY-MM` → rekap per guru
- `GET /admin/payroll/{period}/{user_id}/slip.pdf`, `GET /admin/payroll/{period}/slips.zip`
- `POST /admin/payroll/{period}/{user_id}/finalize`, `POST /admin/payroll/{period}/{user_id}/reopen`
- `GET /admin/attempts`, `GET /admin/audit`

Semua input divalidasi pydantic; guru hanya boleh membaca data miliknya sendiri; data tarif/gaji tidak pernah dikirim ke guru lain.

## 9. PWA Guru (Static Site `web/teacher`, vanilla JS)

- Mobile-first, tombol besar, Bahasa Indonesia. API dipanggil ke `API_BASE_URL` (dari `config.js`) dengan header Bearer. Halaman: **Login**, **Beranda**, **Scan**, **Konfirmasi (pilih kelas & mapel)**, **Riwayat**.
- **Beranda:** nama guru, tanggal hari ini, status absensi hari ini per sesi, tombol besar "Scan Absen", ringkasan bulan berjalan: daftar tanggal hadir, jumlah pertemuan, tarif per pertemuan, **estimasi gaji saat ini** (`meetings × rate`, dari `rate_snapshot`), dan label "estimasi, final setelah periode ditutup admin".
- **Scan:** `getUserMedia({video:{facingMode:"environment"}})`; gunakan `BarcodeDetector` bila ada, fallback ke library vendor. Minta geolokasi **saat tombol Scan ditekan** dengan `enableHighAccuracy:true, timeout:10000, maximumAge:0`. Tampilkan petunjuk jelas jika izin kamera/lokasi ditolak (cara mengaktifkannya), jika GPS lemah, atau jika di luar jangkauan (tampilkan jarak).
- Kirim ke server: token, `coords.latitude/longitude/accuracy`, `position.timestamp`.
- **Tahan cold start:** semua pemanggilan API memakai timeout panjang (≥90 dtk) + retry otomatis pada error jaringan/502/503/504. Selama menunggu tampilkan "Menghubungkan ke server… (bisa sampai 1 menit)" — jangan tampilkan error generik. Setelah login, panggil `/healthz` di latar belakang saat PWA dibuka untuk "membangunkan" server lebih awal.
- **Installable PWA:** `manifest.webmanifest` (name, short_name, `start_url`, `scope`, `display:"standalone"`, `theme_color`, ikon 192/512 + maskable), service worker yang **hanya meng-cache app shell**, **tidak pernah meng-cache `/api/*`**. Saat offline tampilkan "Butuh koneksi internet untuk absen".
- Wajib HTTPS (kamera & geolokasi butuh secure context). Tulis di README: uji di perangkat nyata (Android Chrome dan iPhone Safari/standalone — perilaku izin lokasi di iOS standalone berbeda dan sering minta izin ulang).
- Hindari `innerHTML` dengan data dari server (cegah XSS); gunakan `textContent`/DOM API.

## 10. Admin Web (Static Site `web/admin`, vanilla JS)

Router hash sederhana (`#/dashboard`, `#/sesi`, …), tabel & form dibuat dengan DOM API, desktop-first tapi tetap terbaca di tablet. Halaman: **Login**, **Dashboard Hari Ini** (sesi terbuka, daftar yang sudah absen + status telat/menit, jumlah attempt gagal), **Sesi & QR** (Mulai/Tutup, QR besar, countdown, daftar yang baru absen), **Guru** (CRUD, reset PIN, aktif/nonaktif, atur tarif + riwayat tarif), **Absensi** (filter, input manual, void + alasan), **Pengaturan** (nama madrasah, koordinat + radius — tombol "pakai lokasi saya sekarang" via Geolocation browser atau input manual lat/lng, jam sesi, grace, daftar kelas/mapel), **Penggajian** (pilih periode, tabel rekap per guru: pertemuan × tarif = gaji, unduh slip PDF per guru, unduh semua ZIP, finalisasi/buka kembali), **Log** (attempts gagal, audit).

- **Halaman Sesi & QR:** polling `GET /admin/sessions/{id}/qr` sesuai `expires_at`; tampilkan QR sebesar mungkin; countdown ke rotasi berikutnya; indikator jelas bila polling gagal ("Koneksi terputus — QR mungkin basi"). Polling ini sekaligus menjaga API tetap terjaga selama sesi.
- **Unduh PDF/ZIP:** `fetch` dengan header Bearer → `Blob` → `URL.createObjectURL` → klik link sementara (link `<a href>` biasa tidak bisa mengirim header Authorization).
- **Tahan cold start:** pakai `shared/api.js` yang sama dengan PWA (timeout ≥90 dtk, retry untuk error jaringan/502/503/504) dan tampilkan "Menghubungkan ke server… (bisa sampai 1 menit)" alih-alih error generik.
- Hindari `innerHTML` dengan data dari server; konfirmasi sebelum aksi destruktif (void, finalisasi, buka kembali).
- Admin tidak pernah memegang kredensial Google; semuanya lewat API.

## 11. Slip gaji (PDF, reportlab)

Isi (A4, rapi, siap cetak):
- Header: nama madrasah, "SLIP GAJI GURU", periode (mis. "November 2026").
- Identitas: nama guru, username/ID.
- Tabel rincian: No | Tanggal | Sesi | Kelas | Mata Pelajaran | Status (Tepat waktu / Terlambat X mnt) | Tarif.
- Ringkasan: **Total pertemuan**, tarif per pertemuan (jika tarif berubah di tengah bulan, tampilkan pengelompokan per tarif), **Total / Take Home Pay** (tebal).
- Footer: tanggal cetak, kolom tanda tangan Admin/Bendahara dan penerima, label "DRAFT" jika periode belum final, "FINAL" jika sudah.
- Jika baris melebihi satu halaman, lanjutkan dengan header tabel berulang.
- Test: PDF berhasil dibuat, tidak kosong, memuat nama guru & total yang benar.

## 12. Keamanan & secrets

- Env vars **API (Web Service)**: `GOOGLE_SERVICE_ACCOUNT_JSON` (isi JSON) **atau** `GOOGLE_APPLICATION_CREDENTIALS` (path ke Secret File), `SPREADSHEET_ID`, `JWT_SECRET`, `QR_MASTER_KEY`, `ALLOWED_ORIGINS`, `TZ`. Di `render.yaml` tandai secret dengan `sync: false` agar nilainya tidak masuk repo. **Static Site** hanya butuh `API_BASE_URL` (non-rahasia, dipakai saat build).
- Catatan: Sheets privat butuh **service account (file JSON)**, bukan API key. Spreadsheet harus di-**share ke email service account** dengan akses Editor. **Jangan pernah commit file JSON/secret**; buat `.gitignore` dan `.env.example`; di produksi pakai Render Environment/Secret Files.
- Jangan log PIN, token, atau isi JSON kredensial. Jangan kembalikan `pin_hash` di response API mana pun.
- Security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`) di API dan kedua Static Site, CORS dibatasi ke 2 origin, HTTPS only, validasi ukuran request.
- Spreadsheet berisi data gaji: dokumentasikan siapa saja yang boleh punya akses langsung ke Sheets (idealnya hanya owner + service account).

## 13. Struktur repo

```
.
├── PROMPT.md
├── README.md            # setup, deploy, batasan, cara test di HP
├── DECISIONS.md
├── core/                # logika bisnis murni (tanpa FastAPI/gspread)
│   ├── models.py  tokens.py  geo.py  attendance.py  payroll.py  money.py  timeutil.py
│   └── repo/ (base.py, memory.py, sheets.py)
├── api/                 # FastAPI app, routers, auth, deps
├── web/
│   ├── shared/          # api.js (timeout+retry), format.js — disalin ke tiap site saat build
│   ├── teacher/         # PWA: index.html, app.js, sw.js, manifest.webmanifest, vendor/
│   └── admin/           # Admin Web: index.html, app.js, pages/
├── scripts/             # bootstrap_sheets.py, create_admin.py
├── tests/
├── render.yaml          # blueprint Render: 1 web service (API) + 2 static site (guru, admin)
└── requirements*.txt
```

## 14. Testing (pytest, pakai `InMemoryRepository`; jangan butuh internet)

Wajib ada:
- `tokens`: token valid; slot sekarang & slot-1 diterima; slot-2 ditolak; signature dimodifikasi ditolak; session_id lain ditolak.
- `geo`: haversine akurat (bandingkan dengan titik uji yang diketahui); **99 m lolos, 101 m ditolak**; akurasi 76 m ditolak; `STALE_LOCATION`.
- `attendance`: telat di batas (grace=5 → menit ke-5 `on_time`, menit ke-6 `late`); scan sebelum jadwal `on_time`; di luar jendela ditolak; duplikat per sesi ditolak & idempoten; submit memakai `scanned_at` bukan waktu submit; double-tap paralel tidak membuat 2 baris.
- `payroll`: tarif berubah di tengah bulan → absensi lama tetap memakai tarif lama; void mengurangi pertemuan; batas bulan 23:30 WIB hari terakhir; periode final menolak void/manual; angka `take_home` benar.
- `money/timeutil`: format Rupiah, nama bulan Indonesia.
- `api`: akses silang (guru A tidak bisa baca data guru B), guru tidak bisa memanggil endpoint admin, login rate-limit, CORS (origin tak dikenal tidak mendapat header allow-origin), token dengan `token_version` lama ditolak.
- `slip pdf`: lihat Bagian 11.
- Sediakan `scripts/simulate_day.py` yang mensimulasikan 1 hari (admin buka sesi, 5 guru scan dengan variasi telat/di luar radius/QR basi) terhadap `InMemoryRepository` dan mencetak ringkasan — sebagai demo & smoke test.

## 15. Deployment & runbook (tulis di README)

Tiga service Render Free, didefinisikan di `render.yaml`:

| Service | Tipe | Isi |
|---|---|---|
| `absensi-api` | Web Service (Python) | FastAPI. Start: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`. Health check: `/healthz`. 1 instance. |
| `absensi-guru` | Static Site | publish `web/teacher` (build: salin `web/shared` + buat `config.js`) |
| `absensi-admin` | Static Site | publish `web/admin` (build: sama) |

Langkah:
1. Buat spreadsheet kosong → share ke email service account (Editor) → set `SPREADSHEET_ID`.
2. Dari laptop (dengan env yang sama): `python -m scripts.bootstrap_sheets` lalu `python -m scripts.create_admin`.
3. Deploy lewat `render.yaml`; isi secret di dashboard; set `ALLOWED_ORIGINS` = URL kedua Static Site; set `API_BASE_URL` = URL API di kedua Static Site.
4. Admin login → Pengaturan: isi koordinat madrasah, radius, jam sesi, daftar guru + tarif. (Sesi tidak bisa dibuka sebelum koordinat diisi.)
5. Guru buka URL `absensi-guru` di HP → "Tambahkan ke layar utama".
6. **Pemanasan terjadwal (wajib didokumentasikan):**
   - Free web service tidur setelah 15 menit tanpa trafik dan butuh ±30–60 dtk untuk bangun. Static Site tidak tidur.
   - Buat 2 job di layanan cron eksternal gratis yang mendukung zona waktu per job (mis. cron-job.org), metode `GET https://<api>/healthz`, zona **Asia/Jakarta**: pukul **13:25** (sebelum Sesi 1 13:30) dan **16:00** (sebelum Sesi 2 16:15), pada hari aktif madrasah.
   - Catatan: layanan cron gratis biasanya punya timeout request ±30 dtk, sedangkan bangun bisa lebih lama → job bisa tercatat "gagal" padahal server tetap bangun. Itu aman; matikan notifikasi kegagalan untuk job ini.
   - Selama sesi berlangsung, halaman QR admin memanggil API tiap ~30 dtk sehingga API tidak tidur selama layar QR dibiarkan terbuka (wajib, karena QR berputar). Karena itu dua ping per hari sudah cukup.
   - Konsekuensi yang harus ditulis jujur di README: guru/admin yang membuka aplikasi di luar jendela itu (mis. cek rekap jam 09:00) akan menunggu bangun ±1 menit; admin sebaiknya membuka sesi ≥5 menit sebelum jam mulai; kalau jam sesi berubah, ubah juga jadwal cron.
   - Anggaran jam gratis: API hidup sekitar 13:25–17:45 (± 4–5 jam/hari ≈ <150 jam/bulan), jauh di bawah jatah jam instance Free per workspace; tulis hitungannya di README dan sarankan memverifikasi di halaman billing Render karena kebijakan platform bisa berubah.
   - Jalur upgrade tanpa ubah kode: naikkan `absensi-api` ke instance berbayar → tidak ada tidur sama sekali, ping tidak diperlukan lagi.
7. **Checklist uji lapangan** (wajib dikerjakan manusia, tulis sebagai tabel di README): scan di dalam radius, scan dari luar radius (±150 m), scan QR basi (>60 dtk), scan dua kali, izin lokasi ditolak, GPS indoor lemah, Android + iPhone, offline, **buka PWA saat API sedang tidur** (pastikan pesan "Menghubungkan ke server…" muncul, bukan error).
8. Backup: ekspor Sheets bulanan (jelaskan cara/otomasi sederhana).

## 16. Fase kerja & Definition of Done

**Fase 0 — Rencana (tanpa kode produksi).** Buat `DECISIONS.md` dan `ARCHITECTURE.md` singkat (diagram alur, daftar modul, risiko). Pastikan tidak ada kontradiksi dokumen ini. Commit.

**Fase 1 — Core + repository.** `core/*`, `InMemoryRepository`, `SheetsRepository`, `bootstrap_sheets`, `create_admin`. Test `tokens`, `geo`, `attendance`, `payroll`, `money/timeutil` lulus. Commit.

**Fase 2 — API.** Auth, semua endpoint Bagian 8, rate-limit, audit. Test API lulus; `simulate_day.py` jalan. Commit.

**Fase 3 — PWA guru.** Semua halaman Bagian 9, manifest + service worker, vendor scanner. Jalankan lokal; verifikasi manual alur dengan API palsu/in-memory (buat mode `DEV_FAKE_LOCATION` hanya aktif jika env `ENV=dev`, **tidak boleh bisa aktif di produksi**). Commit.

**Fase 4 — Admin Web (Static Site).** Semua halaman Bagian 10. Commit.

**Fase 5 — Slip gaji PDF + ZIP + finalisasi.** Bagian 11 + test. Commit.

**Fase 6 — Hardening & dokumentasi.** Review keamanan Bagian 12 (cek tidak ada secret di repo, `pin_hash` tidak bocor, header, CORS), `render.yaml` (API + 2 Static Site, custom headers CSP), README lengkap (termasuk Bagian 15: pemanasan terjadwal & anggaran jam Free) + checklist uji lapangan, `ruff` bersih. Commit.

**Definition of Done (seluruhnya):**
- `pytest` hijau, `ruff` bersih, `simulate_day.py` jalan.
- Alur penuh bisa didemokan lokal dengan InMemory: admin buka sesi → QR berputar → guru scan (lokasi disimulasikan) → absen tercatat → dashboard guru terisi → slip PDF terunduh.
- Tidak ada secret di repo; `.env.example` ada.
- README menyebut batasan GPS-spoofing dan batasan Sheets (kuota, bukan transaksi, single-instance).

## 17. Parameter default (boleh diubah admin lewat Pengaturan)

| Parameter | Default |
|---|---|
| Sesi 1 | 13:30–15:45 |
| Sesi 2 | 16:15–17:30 |
| `GRACE_MIN` | 5 |
| `EARLY_OPEN_MIN` | 20 (lebih kecil dari jeda antar-sesi 30 menit) |
| `RADIUS_M` | 100 |
| `MAX_ACCURACY_M` | 75 |
| `QR_ROTATE_SEC` | 30 |
| Hari aktif | Tidak dibatasi (admin yang memutuskan dengan membuka/tidak membuka sesi) |
| Koordinat madrasah | Kosong — wajib diisi admin sebelum sesi pertama dibuka (sesi tidak bisa dibuka jika belum diisi) |
| Potongan telat | Tidak ada |

## 18. Cara kerjamu

- Mulai dengan satu kalimat ringkas tentang apa yang akan kamu kerjakan, lalu langsung Fase 0.
- Gunakan task list untuk melacak fase. Di akhir tiap fase: jalankan test, commit dengan pesan jelas, lanjut.
- Verifikasi pekerjaanmu sendiri: jalankan kodenya, jangan hanya menulisnya. Kalau tidak bisa memverifikasi sesuatu (mis. kamera/GPS di HP asli), tulis itu eksplisit di README sebagai "belum teruji".
- Di akhir, berikan ringkasan: apa yang jadi, apa yang belum teruji, dan 3 risiko teratas yang masih tersisa.
