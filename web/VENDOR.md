# Library pihak ketiga (di-vendor, tidak dimuat dari CDN)

| Library | Versi | Lisensi | Lokasi | Sumber | SHA-256 |
|---|---|---|---|---|---|
| qr-scanner (Nimiq) | 1.4.2 | MIT | `web/teacher/vendor/qr-scanner/` (`qr-scanner.min.js`, `qr-scanner-worker.min.js`, `LICENSE`) | npm `qr-scanner@1.4.2` | `0564e4cf…5484` (main), `f4d8445f…0d14` (worker) |
| Leaflet | 1.9.4 | BSD-2-Clause | `web/admin/vendor/leaflet/` (`leaflet.js`, `leaflet.css`, `images/`, `LICENSE`) | npm `leaflet@1.9.4` | `db49d009…641a` |

Catatan:
- PWA guru memakai `BarcodeDetector` bawaan browser bila tersedia (Android Chrome); `qr-scanner` hanya dipakai sebagai decoder cadangan (mis. iPhone Safari). Worker qr-scanner dibuat dari blob URL, sehingga CSP PWA memuat `worker-src blob:`.
- Tile peta admin diambil dari `https://tile.openstreetmap.org` (gambar saja) dengan atribusi "© OpenStreetMap contributors".
- Untuk memperbarui: `npm pack <paket>@<versi>`, ekstrak, salin file yang sama, perbarui tabel ini.
