# DECISIONS.md

Catatan keputusan teknis. Setiap poin yang tidak ditentukan oleh `PROMPT.md`, atau yang sengaja dibuat lebih aman/sederhana, dicatat di sini beserta alasannya.

## Keputusan dari diskusi dengan pemilik (2026-11-13)

| # | Keputusan | Alasan |
|---|---|---|
| P1 | **Titik madrasah dipilih di peta OpenStreetMap** pada halaman Pengaturan admin (klik/geser penanda), lingkaran radius digambar di peta. Tombol "pakai lokasi saya sekarang" dan input lat/lng manual tetap ada. | Permintaan pemilik. Peta hanya alat bantu memilih titik; validasi tetap di server (haversine). |
| P2 | Leaflet **di-vendor** ke `web/admin/vendor/leaflet/` (bukan CDN). Tile diambil dari `tile.openstreetmap.org`; CSP admin mengizinkan `img-src https://tile.openstreetmap.org`. Atribusi "© OpenStreetMap contributors" ditampilkan. | Aturan "tanpa script pihak ketiga". Tile hanya gambar. Trafik 1–3 admin jauh di bawah batas kebijakan tile OSM. |
| P3 | **Radius = 100 m** (lingkaran berdiameter 200 m), bisa diubah admin di Pengaturan. | Dikonfirmasi pemilik. GPS dalam gedung sering meleset 20–50 m; radius 50 m akan sering menolak guru jujur. |

## PIVOT penyimpanan: Google Sheets → Supabase Postgres (2026-11-13, permintaan pemilik)

Pemilik meminta berhenti memakai Google Sheets dan pindah ke **Supabase Postgres (free tier)**, koneksi lewat **session pooler** (diatur pemilik). Ini mengganti keputusan "TERKUNCI" Bagian 2/7/12 PROMPT soal Sheets; bagian lain arsitektur (FastAPI satu-satunya yang menyentuh data, 2 Static Site, Render Free) tetap.

| # | Keputusan | Alasan |
|---|---|---|
| PG1 | `SheetsRepository` dihapus, diganti `PostgresRepository` (`core/repo/postgres.py`, psycopg 3 + psycopg-pool). Logika bisnis tidak berubah (repository pattern). | Permintaan pemilik. |
| PG2 | Env: `DATABASE_URL` (rahasia, `sync: false`) menggantikan `GOOGLE_*` + `SPREADSHEET_ID`. `REPO_BACKEND` = `memory` \| `postgres`. | — |
| PG3 | Pool kecil: `max_size=4`, `min_size=1`, dibuka malas saat query pertama, `check_connection` saat checkout, `max_idle=120 dtk`, `prepare_threshold=None`, autocommit. | Kuota koneksi pooler free tier terbatas; `/healthz` tidak boleh menyentuh DB; koneksi yang diputus saat API tidur diganti otomatis; aman bila nanti pindah ke transaction pooler (6543). |
| PG4 | Tabel di schema **`absensi`** (bukan `public`) + **RLS aktif tanpa policy** di semua tabel. | Supabase Data API (anon key) otomatis mengekspos `public`; dengan ini data gaji tidak bisa dibaca lewat Data API. API kita konek sebagai `postgres` (pemilik tabel) sehingga tidak terkena RLS. |
| PG5 | **Keunikan absensi dijamin database**: partial unique index `(session_id, user_id) WHERE NOT voided` + unique `ticket_id`. Lock in-process tetap ada (mengurangi balapan), tetapi tidak lagi menjadi penjaga utama. Pelanggaran → `DuplicateAttendanceError` → `ALREADY_ATTENDED` / baris pemenang bila ticket sama. Mekanisme "verifikasi setelah tulis + auto-void `auto-duplicate`" (khusus Sheets) dihapus. | Constraint DB lebih kuat dari baca-ulang ala Sheets. |
| PG6 | Skema di `db/schema.sql`, diterapkan oleh `python -m scripts.migrate` (idempoten, menggantikan `bootstrap_sheets`), sekaligus mengisi default kelas/mapel/jam sesi. | — |
| PG7 | Tipe kolom asli Postgres (`timestamptz`, `date`, `bigint`, `boolean`); ID tetap teks UUID4. Tidak ada `DELETE` di kode; void = tandai kolom. | — |
| PG8 | Test `PostgresRepository` memakai Postgres sungguhan: `TEST_DATABASE_URL` jika di-set, jika tidak **pgserver** (Postgres lokal sementara, dev dependency). Semua test attendance/payroll dijalankan di **kedua** backend (memory & postgres). Koneksi ke Supabase asli **belum teruji** dari lingkungan ini. | Test tidak butuh internet. |
| PG9 | Batas free tier Supabase yang perlu diketahui: project di-*pause* setelah ±1 minggu tanpa aktivitas (aktivitas harian madrasah biasanya cukup), kuota DB 500 MB (puluhan tahun data absensi skala ini), backup harian otomatis tidak tersedia di free tier → README menjelaskan `pg_dump` bulanan. Pilih region Supabase sama/dekat dengan region Render (mis. Singapore). | Kejujuran soal batasan. |

Keputusan Sheets di bawah yang **tidak berlaku lagi**: D14, D15, D16, D30 (dan bagian "lock per (session,user) + verifikasi setelah tulis" di D18). D17 tetap (upsert, tidak menghapus baris).

## Keputusan teknis

| # | Topik | Keputusan | Alasan |
|---|---|---|---|
| D1 | `STALE_LOCATION` | Klien mengirim `position_ts` **dan** `client_ts` (jam HP saat kirim). Umur posisi = `client_ts - position_ts` (keduanya jam HP). Ditolak jika umur > 30 dtk atau < -5 dtk. Selisih jam HP vs server dicatat (`clock_skew_s`) di attempt, tapi tidak dipakai untuk menolak. Jika `client_ts` tidak dikirim, fallback ke aturan asli `|server_now - position_ts| > 30 dtk`. | Aturan asli membandingkan jam HP dengan jam server, sehingga guru jujur dengan jam HP meleset >30 dtk akan selalu ditolak. Posisi bisa dipalsukan dari web apa pun aturannya; pertahanan utama tetap QR berputar. |
| D2 | Input manual tanpa sesi | Admin memilih tanggal + kode sesi. Jika `session_instance (date, code)` sudah ada, dipakai; jika belum, dibuat instance baru yang langsung tertutup (`opened_at = closed_at = waktu input`, `opened_by` = admin). | Baris `attendance` wajib punya `session_id`; tidak perlu tab baru. |
| D3 | Jam hadir pada input manual | Opsional (HH:MM WIB). Default = jam mulai terjadwal (→ tepat waktu). Status telat dihitung dengan aturan yang sama dengan scan. | Konsisten dengan aturan telat. |
| D4 | Sesi ditutup di antara scan dan submit | Submit tetap diterima selama ticket (5 menit) masih berlaku. | Waktu hadir = `scanned_at`, yang saat itu sah. |
| D5 | Logout | `POST /auth/logout` tidak menaikkan `token_version`; klien menghapus token. `token_version` naik hanya saat ganti/reset PIN atau nonaktif. | Menaikkan versi saat logout akan mengeluarkan guru dari semua perangkat. |
| D6 | Tab `payslips` | Baris ditulis saat **finalisasi** (status `final`). "Buka kembali" mengubah baris yang sama menjadi `draft`. Rekap draft selalu dihitung langsung dari `attendance`. | Tidak ada baris yang dihapus; satu baris per (periode, guru). |
| D7 | Absen ulang setelah void | Boleh. Keunikan `(session_id, user_id)` hanya berlaku untuk baris `voided=false`. | Void biasanya koreksi kesalahan. |
| D8 | Idempotensi submit | `ticket_id` disimpan di baris attendance. Submit ulang dengan ticket yang sama mengembalikan baris yang sama (HTTP 200). Ticket lain untuk sesi+guru yang sudah valid → `ALREADY_ATTENDED`. Scan juga sudah menolak `ALREADY_ATTENDED` sebelum ticket diterbitkan. | Sesuai Bagian 5. |
| D9 | Guru tanpa tarif | Absensi tetap tercatat dengan `rate_snapshot = 0`; halaman Penggajian dan Guru menandai "belum ada tarif". Form tambah guru mewajibkan tarif awal. | Kehadiran tidak boleh hilang karena kelalaian admin. Koreksi: void + input manual setelah tarif diisi. |
| D10 | Pemilihan tarif | Tarif berlaku = baris `rates` dengan `effective_from <= tanggal (WIB)` terbaru; seri diputus oleh `set_at` terbaru. | Deterministik. |
| D11 | Membuka sesi | Ditolak `LOCATION_NOT_SET` jika lat/lng belum diisi. Satu instance per `(tanggal, kode)`. Membuka sesi yang sudah terbuka mengembalikan instance itu; membuka sesi yang sudah ditutup membukanya kembali (mengosongkan `closed_at`) dan dicatat di audit. | Admin bisa salah klik "Tutup". |
| D12 | Scan di luar jendela | Kode `SESSION_CLOSED` dengan pesan berbeda untuk "belum dibuka" vs "sudah ditutup" (field `detail`). | Tidak menambah kode error baru. |
| D13 | Rate-limit login | 5 gagal / 60 dtk per (username, IP) **dan** 20 gagal / 15 menit per username (apa pun IP-nya) → `429 RATE_LIMITED`. IP = entri pertama `X-Forwarded-For` (Render berada di belakang proxy). | Batas kedua mencegah bypass dengan memalsukan `X-Forwarded-For`. |
| D14 | Format nilai di Sheets | Semua nilai ditulis sebagai **string** dengan `value_input_option=RAW` dan dibaca dengan `UNFORMATTED_VALUE`. Boolean = `TRUE`/`FALSE`. | Mencegah Sheets mengubah username/angka/tanggal sesuai locale spreadsheet (mis. `12,5` vs `12.5`). |
| D15 | Mirror attendance di memori | API adalah satu-satunya penulis, jadi `SheetsRepository` menyimpan mirror tab (dengan nomor baris) dan memperbaruinya saat menulis. Tab statis TTL 30 dtk; `attendance`/`attempts`/`audit_log` dimuat ulang penuh tiap 5 menit. **Cek duplikat sebelum tulis** membaca *fresh* blok ekor (± 500 baris terakhir) + mirror; **verifikasi setelah tulis** membaca ekor lagi. | Membaca seluruh tab attendance (puluhan ribu baris setelah setahun) tiap scan terlalu lambat & boros kuota. Baris sesi aktif selalu ada di ekor karena append-only. |
| D16 | Ubah baris di Sheets | Update baris berdasarkan nomor baris dari mirror, setelah memverifikasi kolom kunci (mis. `attendance_id`) di baris tersebut masih sama (baca fresh 1 baris). Tidak pernah sort/hapus. | Nomor baris stabil karena tidak ada penghapusan. |
| D17 | Kelas/mapel/session_defs/settings | `PUT` melakukan upsert: nama yang ada diperbarui, nama baru ditambah, penghapusan = `active=FALSE`. Tidak ada baris yang dihapus. | Aturan "jangan hapus baris". |
| D18 | Endpoint sinkron | Endpoint FastAPI ditulis sebagai `def` (bukan `async def`) agar berjalan di threadpool, sehingga `threading.Lock` per `(session_id, user_id)` bermakna dan panggilan gspread (blocking) tidak memblokir event loop. | Sesuai Bagian 7. |
| D19 | Kunci ticket | Ticket JWT ditandatangani dengan kunci turunan `HMAC(JWT_SECRET, "ticket-v1")` dan claim `typ="ticket"`; access token memakai `typ="access"`. | Ticket tidak bisa dipakai sebagai access token dan sebaliknya. |
| D20 | `DEV_FAKE_LOCATION` | Router `/api/dev/*` hanya di-mount jika `ENV=dev`. Aplikasi **menolak start** jika `DEV_FAKE_LOCATION=1` dan `ENV` bukan `dev`, atau jika `REPO_BACKEND=memory` di `ENV=production`. PWA menampilkan panel lokasi palsu hanya jika `/api/dev/config` menjawab `fake_location: true`. | "Tidak boleh bisa aktif di produksi". |
| D21 | Retry di klien | `shared/api.js` me-retry error jaringan dan 502/503/504 (termasuk POST) hingga ±90 dtk total. Aman karena semua POST yang membuat data dijaga duplikasinya di server (ticket, unik sesi+guru, username unik). | Cold start Render. |
| D22 | Zona waktu | Indonesia tidak memakai DST; tampilan di frontend menghitung WIB = UTC+7 secara manual (bukan `toLocaleString`) agar tidak bergantung locale. Backend memakai `zoneinfo("Asia/Jakarta")` + paket `tzdata` (Windows tidak punya database zona). Setting `timezone` disimpan tapi hanya `Asia/Jakarta` yang didukung. | Bagian 5 "tanpa bergantung pada locale OS". |
| D23 | CSP `connect-src` Static Site | Default `https://*.onrender.com` karena URL pasti API baru diketahui setelah deploy; README menyarankan menggantinya dengan URL API persis. | Nilai header di `render.yaml` statis. |
| D24 | Ikon PWA | Dibuat oleh `scripts/make_icons.py` (encoder PNG murni Python, tanpa Pillow). | Tanpa dependensi tambahan. |
| D25 | Lapisan repository | `core/repo/base.py` = interface per entitas (`UserRepo`, `AttendanceRepo`, …) dalam satu kontainer `Repository`. `InMemoryRepository` = entitas generik (`tables.py`) di atas list di memori (`memory.py`); `PostgresRepository` (`postgres.py`) mengimplementasikan interface entitas langsung dengan SQL. | Logika bisnis tidak tahu storage; pivot Sheets → Postgres tidak menyentuh `core/attendance.py`/`payroll.py` selain penanganan `DuplicateAttendanceError`. |
| D26 | Endpoint tambahan kecil | `GET /api/healthz` alias tidak ditambah; `GET /healthz` di root. Ditambah `GET /api/admin/sessions/{id}/attendance` tidak perlu — daftar yang baru absen diambil dari `GET /admin/attendance?date=`. | Tetap di dalam spesifikasi. |

| D27 | Kolom tambahan `attempts.detail` | Tab `attempts` diberi kolom ke-7 `detail` (JSON: umur posisi, selisih jam HP, sub-alasan). `reason` tetap berisi kode error saja agar mudah difilter. | Membantu admin membaca pola tanpa mengubah kolom yang ditentukan. |
| D28 | Test batas bulan | Spesifikasi menyebut "23:30 WIB hari terakhir bulan (secara UTC sudah bulan berikutnya)". Itu keliru: 23:30 WIB = 16:30 UTC di hari yang sama. Kasus UTC beda bulan adalah **00:00–06:59 WIB tanggal 1**. Test mencakup keduanya: 23:30 WIB 30 Nov → November; 00:30 WIB 1 Des (UTC masih 30 Nov) → Desember. | Menguji kasus yang benar-benar berisiko. |
| D29 | Membuka sesi setelah jam selesai | Ditolak `SESSION_OVER`. | Jendela scan sudah kosong; mencegah sesi "hantu". |
| D30 | `SheetsBackend` di test | Diuji dengan klien gspread palsu (`tests/fake_gspread.py`): bootstrap idempoten, header salah terdeteksi, retry 429/503, alur absensi penuh. Akses Google Sheets sungguhan **belum teruji** dari lingkungan pengembangan ini. | Test tidak boleh butuh internet. |

| D31 | Rahasia di Render | `JWT_SECRET` & `QR_MASTER_KEY` memakai `generateValue: true` (acak oleh Render); `DATABASE_URL` & `ALLOWED_ORIGINS` `sync: false`. API menolak start di produksi bila secret <32 karakter, sama satu sama lain, origin bukan https, atau backend memory. | Tidak ada secret di repo; salah konfigurasi gagal cepat. |
| D32 | Header Static Site | Sumber tunggal `scripts/web_headers.py` dipakai `dev_server` (sehingga CSP produksi teruji lokal) dan dicocokkan dengan `render.yaml` oleh test. `sw.js` & `config.js` diberi `Cache-Control: no-cache`. Service worker network-first agar deploy baru langsung terpakai; cache hanya cadangan offline. | Mencegah CSP produksi berbeda dari yang diuji; mencegah PWA terjebak versi lama. |
| D33 | QR di admin | SVG dari segno disimpan sebagai dokumen SVG mandiri (`xmlns`), ditampilkan via `Blob` + `<img>`. Jadwal polling berikutnya = `expires_at` + 300 ms, dikoreksi selisih jam PC admin vs server (`server_time`). Watchdog meredupkan QR dan menampilkan "Koneksi terputus — QR mungkin basi" bila QR di layar sudah melewati masa berlakunya. | `svg_inline` tanpa namespace gagal dirender lewat Blob (ditemukan saat uji). |
| D34 | Rate-limiter memori | Entri kedaluwarsa dibersihkan bila jumlah kunci > 5.000. | Mencegah memori membengkak oleh percobaan login dengan username acak. |
| D35 | Token QR kanonik | Token ditolak bila encoding base64url/slot tidak kanonik (bit sisa base64 dimodifikasi). | Ditemukan oleh test acak: base64 Python menerima beberapa ejaan untuk byte yang sama. Bukan pemalsuan, tetapi token kini punya tepat satu bentuk sah. |

## Usulan (tidak dibangun)

- Ekspor backup Sheets otomatis (Apps Script time-driven trigger) — saat ini hanya didokumentasikan sebagai langkah manual.
- Ganti PIN oleh guru sendiri (saat ini hanya reset oleh admin).
- Tampilan peta posisi guru vs lingkaran madrasah di PWA saat `OUT_OF_RANGE`.
- Pindah ke Postgres bila jumlah guru/sesi bertambah jauh atau butuh laporan lintas tahun yang cepat.
