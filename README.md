# Absensi & Penggajian Guru Madrasah

Guru absen dengan **scan QR** yang tampil di layar admin dan berganti tiap 30 detik. Absen hanya sah dalam **radius 100 m** dari titik madrasah. Gaji dihitung otomatis dari **jumlah pertemuan × tarif**, lalu admin mencetak **slip gaji PDF**.

- **PWA Guru** (`web/teacher`): login, scan QR, pilih kelas & mapel, lihat kehadiran dan estimasi gaji bulan berjalan. Bisa dipasang ke layar utama HP.
- **Admin Web** (`web/admin`): buka/tutup sesi dengan QR berputar, kelola guru & tarif, titik lokasi di peta OpenStreetMap, input manual/void absensi (dengan alasan + audit), rekap gaji, slip PDF/ZIP, finalisasi periode, log.
- **API** (`api/`, FastAPI): satu-satunya komponen yang menyentuh database **Supabase Postgres**.

Dokumen lain: [ARCHITECTURE.md](ARCHITECTURE.md) (alur & modul), [DECISIONS.md](DECISIONS.md) (keputusan teknis & alasannya), [PROMPT.md](PROMPT.md) (spesifikasi awal), [web/VENDOR.md](web/VENDOR.md) (library pihak ketiga).

---

## 1. Batasan yang perlu diketahui (jujur)

- **GPS dari browser bisa dipalsukan** (aplikasi *mock location*), dan aplikasi web **tidak bisa mendeteksinya**. Karena itu pertahanan utama adalah **QR yang berganti tiap 30 detik** (token hanya sah ±30–60 detik, jadi foto QR yang dikirim lewat WhatsApp cepat basi). Geofence adalah lapisan tambahan. Sistem ini **tidak** "anti-curang 100%". Semua percobaan gagal dicatat di menu **Log** agar pola mencurigakan bisa dilihat.
- **Tetap ada celah sosial.** Misalnya rekan di madrasah melakukan video call sambil menunjukkan QR ke guru yang ada di rumah, dan guru itu memalsukan GPS. Risiko ini diperkecil, tapi tidak bisa dihilangkan dari sisi teknis.
- **Butuh internet.** Tidak ada mode absen offline.
- **API harus tepat 1 instance.** Lock anti-dobel-tap dan rate-limit login disimpan di memori proses. Duplikat tetap dicegah oleh constraint unik di database, tetapi jangan aktifkan scaling horizontal.
- **Render Free tidur** setelah 15 menit tanpa trafik. Panggilan pertama sesudahnya butuh ±30–60 detik (lihat §6).
- **Batas Supabase Free:**
  - Project di-*pause* setelah ±1 minggu tanpa aktivitas, misalnya saat libur panjang. Aktifkan lagi lewat dashboard Supabase.
  - Kapasitas database 500 MB, cukup untuk puluhan tahun data skala ini.
  - Tidak ada backup otomatis yang bisa dipulihkan sendiri, jadi lakukan backup bulanan (§9).
  - Kebijakan free tier bisa berubah; cek halaman billing Supabase dan Render secara berkala.

## 2. Menjalankan di laptop (demo lokal)

Butuh Python 3.12 dan Node (hanya untuk test JS).

```bash
py -3.12 -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
```

```bash
.venv/Scripts/python -m scripts.dev_server
```

Lalu buka:

- PWA guru: <http://localhost:8001>
- Admin: <http://localhost:8002>
- API: <http://localhost:8000> (dokumentasi `/docs` hanya ada di mode dev)

Mode dev memakai database **in-memory** (data hilang saat server dimatikan) dengan data demo dari `scripts/dev_seed.py`: akun `admin` dan `guru1`–`guru5`, PIN `123456`, titik madrasah di Monas. Di PWA guru yang dibuka dari `localhost` muncul panel **MODE DEV — lokasi palsu**. Panel ini memakai token QR aktif dan koordinat yang Anda ketik, sehingga alur absen bisa diuji tanpa kamera atau GPS. Panel ini **tidak bisa aktif di produksi**: router `/api/dev/*` hanya ada saat `ENV=dev`, dan API menolak start jika `DEV_FAKE_LOCATION=1` di luar dev.

Alur demo: Admin → Pengaturan (ubah jam Sesi 1 agar mencakup jam sekarang) → Sesi & QR → Mulai → di PWA guru: Scan Absen → panel DEV → pilih kelas & mapel → Simpan → Admin → Penggajian → Slip PDF.

### Test & lint

```bash
.venv/Scripts/python -m pytest
```

```bash
.venv/Scripts/ruff check .
```

```bash
node --test tests/js/api.test.mjs
```

```bash
.venv/Scripts/python -m scripts.simulate_day
```

`pytest` menjalankan test absensi & penggajian di **dua backend**: in-memory dan **Postgres sungguhan**. Postgres-nya adalah server lokal sementara via paket `pgserver`, atau database yang Anda tunjuk lewat `TEST_DATABASE_URL`. Tidak butuh internet.

## 3. Menyiapkan Supabase

1. Buat project di <https://supabase.com> (plan Free). Pilih region **Southeast Asia (Singapore)**, sama dengan region API di Render, agar latensi kecil. Simpan password database.
2. Buka **Connect** → salin connection string **Session pooler** (port 5432, IPv4). Bentuknya: `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`. Ini nilai `DATABASE_URL`, dan ini **rahasia**.
3. Dari laptop, set `DATABASE_URL` di terminal (jangan di file yang di-commit), lalu jalankan:

   ```bash
   .venv/Scripts/python -m scripts.migrate
   ```

   ```bash
   .venv/Scripts/python -m scripts.create_admin
   ```

   `migrate` bersifat idempoten. Ia membuat schema `absensi` beserta tabel dan index, lalu mengisi default kelas, mapel, dan jam sesi. `create_admin` membuat akun admin pertama (PIN minimal 6 karakter).
4. Tabel berada di schema `absensi` dengan **RLS aktif tanpa policy**, sehingga Supabase Data API (anon key) tidak bisa membaca data gaji. Jangan menambahkan schema `absensi` ke "Exposed schemas" di pengaturan API Supabase.

**Siapa yang boleh punya akses langsung ke database:** hanya pemilik project Supabase. API mengakses lewat `DATABASE_URL`. Jangan undang anggota lain ke project Supabase dan jangan bagikan connection string. Semua orang lain (admin madrasah) bekerja lewat Admin Web.

## 4. Deploy ke Render (3 service Free)

| Service | Tipe | Isi |
|---|---|---|
| `absensi-api` | Web Service (Python) | `uvicorn api.main:app --host 0.0.0.0 --port $PORT`, health check `/healthz`, **1 instance** |
| `absensi-guru` | Static Site | publish `web/teacher` (build: salin `web/shared` + buat `config.js`) |
| `absensi-admin` | Static Site | publish `web/admin` (build: sama) |

1. Push repo ke GitHub, lalu di Render: **New → Blueprint** → pilih repo. `render.yaml` membuat ketiga service.
2. Isi variabel yang ditandai `sync: false`:
   - `absensi-api` → `DATABASE_URL` = connection string session pooler dari §3.
   - `absensi-api` → `ALLOWED_ORIGINS` = `https://absensi-guru.onrender.com,https://absensi-admin.onrender.com`. Gunakan URL persis yang diberikan Render, tanpa garis miring di akhir.
   - `absensi-guru` dan `absensi-admin` → `API_BASE_URL` = `https://absensi-api.onrender.com`.
   - `JWT_SECRET` dan `QR_MASTER_KEY` dibuat acak otomatis oleh Render (`generateValue`). Jangan ubah tanpa alasan: mengganti `JWT_SECRET` mengeluarkan semua user, dan mengganti `QR_MASTER_KEY` membuat QR sesi yang sedang berjalan tidak sah.
3. Jika URL berbeda dari contoh (Render kadang menambah akhiran acak), perbarui `ALLOWED_ORIGINS` dan `API_BASE_URL`, lalu **deploy ulang kedua Static Site** karena `config.js` dibuat saat build.
4. **Perketat CSP (disarankan):** di `render.yaml`, ganti `https://*.onrender.com` pada `connect-src` di kedua Static Site dengan URL API persis. Ubah juga `scripts/web_headers.py` agar test tetap hijau.
5. **Jangan** menaikkan jumlah instance API. Filesystem Render ephemeral, tetapi aplikasi tidak menyimpan apa pun di disk.

HTTPS otomatis dari `*.onrender.com` sudah memenuhi syarat *secure context* untuk kamera, geolokasi, dan Wake Lock.

## 5. Setelah deploy: pengaturan awal oleh admin

1. Login di Admin Web → **Pengaturan**:
   - Isi nama madrasah.
   - Klik atau geser penanda di peta ke titik madrasah. Bisa juga tekan "Pakai lokasi saya sekarang" dari lokasi madrasah, atau isi lat/lng manual.
   - Atur radius (default 100 m). Lingkaran di peta menunjukkan area sah.
   - **Sesi tidak bisa dibuka sebelum koordinat disimpan.**
2. Periksa jam sesi (default Sesi 1 13:30–15:45, Sesi 2 16:15–17:30), toleransi telat (5 menit), dan daftar kelas & mapel.
3. **Guru** → tambah tiap guru dengan PIN awal dan tarif per pertemuan. Sampaikan PIN secara pribadi.
4. Guru membuka URL `absensi-guru` di HP → login → "Tambahkan ke layar utama" (Android: tombol "Pasang Aplikasi" di beranda; iPhone: Safari → Bagikan → Tambahkan ke Layar Utama).

## 6. Pemanasan terjadwal (wajib) & anggaran jam Free

Free web service Render tidur setelah **15 menit tanpa trafik** dan butuh **±30–60 detik** untuk bangun. Static Site tidak tidur, jadi halaman PWA dan admin selalu langsung terbuka; hanya panggilan API pertama yang bisa lambat. Selama menunggu, aplikasi menampilkan "Menghubungkan ke server… (bisa sampai 1 menit)" dan me-retry otomatis hingga ±90 detik.

**Buat 2 job di layanan cron eksternal gratis** yang mendukung zona waktu per job (mis. <https://cron-job.org>):

| Job | URL (GET) | Zona | Jam | Hari |
|---|---|---|---|---|
| Pemanasan Sesi 1 | `https://<api>.onrender.com/healthz` | Asia/Jakarta | **13:25** | hari aktif madrasah |
| Pemanasan Sesi 2 | `https://<api>.onrender.com/healthz` | Asia/Jakarta | **16:00** | hari aktif madrasah |

- Layanan cron gratis biasanya punya timeout ±30 detik, sedangkan bangun bisa lebih lama. Job bisa tercatat "gagal" padahal server tetap bangun. Itu aman; **matikan notifikasi kegagalan** untuk job ini.
- Selama sesi berlangsung, halaman QR admin memanggil API tiap ±30 detik, sehingga API tidak tidur selama layar QR terbuka. Karena itu dua ping per hari sudah cukup.
- **Konsekuensi:**
  - Guru atau admin yang membuka aplikasi di luar jendela itu (mis. cek rekap jam 09:00) akan menunggu server bangun ±1 menit.
  - Admin sebaiknya membuka sesi **≥5 menit sebelum jam mulai**.
  - **Jika jam sesi diubah, ubah juga jadwal cron.**
- **Anggaran jam:**
  - API hidup kira-kira 13:25 sampai selesai Sesi 2 ditambah 15 menit idle (±18:00), yaitu ±4,6 jam/hari.
  - Hitungan: 4,6 × 31 hari ≈ **143 jam/bulan**, ditambah sedikit untuk akses di luar jam sesi.
  - Itu jauh di bawah jatah jam instance Free per workspace (750 jam/bulan saat dokumen ini ditulis). Verifikasi di halaman billing Render, karena kebijakan platform bisa berubah.
- **Jalur upgrade tanpa ubah kode:** naikkan `absensi-api` ke instance berbayar. API tidak tidur lagi dan ping tidak diperlukan.

## 7. Pemakaian harian

1. **Admin:**
   - Buka Admin Web → **Sesi & QR** → **Mulai Sesi 1** (≥5 menit sebelum 13:30).
   - Biarkan layar QR **tetap terbuka** selama sesi; tombol "Layar penuh" cocok untuk proyektor/TV.
   - Halaman meminta Wake Lock agar layar tidak mati. Jika browser tidak mendukung, matikan sleep/screensaver secara manual.
   - Indikator "Koneksi terputus — QR mungkin basi" berarti layar tidak lagi mendapat QR baru.
2. **Guru:**
   - Buka aplikasi → **Scan Absen** → izinkan kamera & lokasi → arahkan ke QR.
   - Pilih kelas & mapel dalam 5 menit.
   - Jam hadir dihitung saat scan, bukan saat menyimpan.
3. **Admin** menutup sesi setelah selesai, atau biarkan; scan otomatis ditolak setelah jam selesai.
4. **Akhir bulan:**
   - Penggajian → periksa rekap.
   - Koreksi bila perlu lewat Absensi (input manual / void, wajib dengan alasan).
   - **Finalisasi** per guru, lalu unduh slip PDF atau ZIP.
   - Periode final menolak void/input manual sampai "Buka kembali" (dengan alasan, tercatat di audit).

## 8. Uji di HP nyata + checklist uji lapangan

Kamera, GPS, dan perilaku izin **harus diuji manusia di perangkat nyata**. Uji di **Android Chrome** dan **iPhone Safari**, termasuk saat dibuka sebagai aplikasi di layar utama (*standalone*). Di iOS standalone, izin lokasi sering diminta ulang.

| # | Skenario | Langkah | Hasil yang diharapkan | Android | iPhone |
|---|---|---|---|---|---|
| 1 | Scan di dalam radius | Di madrasah, Scan Absen → pilih kelas/mapel | "Absensi tersimpan", status sesuai jam | ☐ | ☐ |
| 2 | Scan dari luar radius | ±150 m dari titik madrasah | Ditolak, pesan "Anda ±… m dari madrasah" | ☐ | ☐ |
| 3 | QR basi | Foto QR, tunggu >60 dtk, scan foto itu | Ditolak "QR sudah basi" | ☐ | ☐ |
| 4 | Scan dua kali | Setelah absen, scan lagi di sesi yang sama | Ditolak "Anda sudah absen di sesi ini" | ☐ | ☐ |
| 5 | Izin lokasi ditolak | Tolak izin lokasi | Muncul panduan cara mengaktifkan | ☐ | ☐ |
| 6 | Izin kamera ditolak | Tolak izin kamera | Muncul panduan cara mengaktifkan | ☐ | ☐ |
| 7 | GPS indoor lemah | Scan di ruangan tertutup | Lolos jika akurasi ≤75 m; jika tidak, pesan "Sinyal GPS lemah" + tips | ☐ | ☐ |
| 8 | Offline | Mode pesawat, buka aplikasi | Aplikasi terbuka, banner "Butuh koneksi internet untuk absen" | ☐ | ☐ |
| 9 | **API sedang tidur** | Buka PWA >15 menit setelah trafik terakhir | Muncul "Menghubungkan ke server… (bisa sampai 1 menit)", lalu berhasil, **bukan** error | ☐ | ☐ |
| 10 | Pasang ke layar utama | Pasang, buka dari ikon | Terbuka standalone, login tetap tersimpan | ☐ | ☐ |
| 11 | Layar QR admin | Biarkan layar QR 30 menit | QR berganti tiap 30 dtk, layar tidak mati | (laptop/TV admin) | |
| 12 | Telat | Scan >5 menit setelah jam mulai | Status "Terlambat X menit" | ☐ | ☐ |

## 9. Backup & pemulihan

Supabase Free tidak menyediakan backup yang bisa dipulihkan sendiri. Lakukan **backup bulanan** (mis. setelah finalisasi gaji) dari laptop pemilik:

```bash
pg_dump "$DATABASE_URL" --schema=absensi --format=custom --file=absensi-2026-11.dump
```

- Versi `pg_dump` sebaiknya ≥ versi Postgres Supabase (lihat Settings → Infrastructure).
- Simpan file backup di tempat aman (data gaji = data pribadi). Contoh: drive terenkripsi milik pemilik.
- Pulihkan ke project baru dengan:

  ```bash
  pg_restore --dbname "$DATABASE_URL" --no-owner absensi-2026-11.dump
  ```

- Alternatif tanpa terminal: Admin → Penggajian → **Unduh semua slip (ZIP)** tiap bulan sebagai arsip cetak.

## 10. Keamanan

- **Secret** hanya ada di environment Render, tidak pernah di repo: `DATABASE_URL`, `JWT_SECRET`, `QR_MASTER_KEY`. `.gitignore` menolak `.env`; contoh variabel ada di `.env.example`. Test `tests/test_deploy_config.py` memeriksa tidak ada secret yang ter-commit.
- **Login:**
  - Username + PIN di-hash dengan **argon2**.
  - Rate-limit 5 gagal/menit per (username, IP) dan 20 gagal/15 menit per username.
  - Token JWT dikirim lewat header `Authorization: Bearer`; tidak memakai cookie.
  - Masa berlaku token guru 30 hari (`localStorage`), admin 8 jam (`sessionStorage`).
  - Reset PIN atau menonaktifkan user langsung membatalkan token lama (`token_version`).
- **API:**
  - CORS hanya untuk 2 origin Static Site (`allow_credentials=False`).
  - Security headers lengkap (CSP `default-src 'none'`, `nosniff`, `no-referrer`, HSTS).
  - Body maksimal 32 KB.
  - `pin_hash` tidak pernah dikirim di response.
  - `/docs` dimatikan di produksi.
- **Frontend:**
  - Tanpa script pihak ketiga; library di-vendor.
  - Tanpa `innerHTML` untuk data server (dicek otomatis oleh test).
  - CSP ketat lewat header Static Site di `render.yaml`.
- **Database:** schema `absensi` + RLS tanpa policy (Data API Supabase tidak bisa membaca). Absensi tidak pernah dihapus; void = tandai kolom. Semua perubahan admin tercatat di audit log.

## 11. Yang belum teruji

- **Kamera & GPS di HP nyata** (Android Chrome, iPhone Safari/standalone). Di lingkungan pengembangan, alur absen diuji dengan panel lokasi palsu DEV. Jalur "izin ditolak" sudah diuji di browser desktop.
- **Koneksi ke Supabase sungguhan lewat session pooler.** `PostgresRepository` diuji terhadap Postgres 16 lokal, bukan terhadap Supabase.
- **Deploy Render sungguhan.** `render.yaml` belum dicoba sebagai Blueprint; cold start nyata dan ping cron belum diuji. Perilaku retry/cold-start di klien diuji dengan test Node dan dengan mematikan server lokal.
- **Wake Lock** di browser/perangkat layar admin yang dipakai madrasah.
- **Tampilan slip PDF saat dicetak** di printer madrasah (PDF sudah diperiksa secara visual di layar).

## 12. Struktur repo

```
core/            logika bisnis murni (token QR, geofence, absensi, penggajian, slip PDF) + repository
  repo/          base.py (interface), memory.py + tables.py (InMemory), postgres.py (Supabase)
api/             FastAPI: config, auth, rate-limit, middleware keamanan, routers (guru, admin, dev)
db/schema.sql    skema Postgres (idempoten)
web/shared/      api.js (timeout 90 dtk + retry), format.js — disalin ke tiap site saat build
web/teacher/     PWA guru (index.html, app.js, scanner.js, sw.js, manifest, icons/, vendor/qr-scanner)
web/admin/       Admin Web (index.html, app.js, ui.js, pages/, vendor/leaflet)
scripts/         migrate, create_admin, simulate_day, dev_server, dev_seed, build_web, make_icons
tests/           pytest (memory + Postgres), tests/js (node --test)
render.yaml      blueprint Render: 1 web service + 2 static site
```
