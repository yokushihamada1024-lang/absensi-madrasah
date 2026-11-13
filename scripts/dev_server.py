"""Jalankan semuanya lokal untuk demo/uji manual (InMemory, data demo, lokasi palsu DEV):

  API          http://localhost:8000   (ENV=dev, REPO_BACKEND=memory, DEV_FAKE_LOCATION=1)
  PWA guru     http://localhost:8001   (header CSP sama dengan produksi)
  Admin web    http://localhost:8002

Akun demo: admin / guru1..guru5, PIN 123456 (lihat scripts/dev_seed.py).
Pakai:  python -m scripts.dev_server
Catatan: kamera & lokasi di browser hanya jalan di secure context; localhost dihitung aman.
"""

from __future__ import annotations

import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.build_web import build
from scripts.web_headers import headers

ROOT = Path(__file__).resolve().parents[1]
API_PORT, GURU_PORT, ADMIN_PORT = 8000, 8001, 8002
API = f"http://localhost:{API_PORT}"


class StaticHandler(SimpleHTTPRequestHandler):
    site = "teacher"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript",
                      ".webmanifest": "application/manifest+json"}

    def end_headers(self) -> None:
        for k, v in headers(self.site, f"{API} http://127.0.0.1:{API_PORT}").items():
            self.send_header(k, v)
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # lebih tenang
        pass


def serve_static(site: str, port: int) -> None:
    handler = type(f"{site}Handler", (StaticHandler,), {"site": site})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(handler, directory=str(ROOT / "web" / site)))
    httpd.serve_forever()


def main() -> int:
    os.environ.setdefault("ENV", "dev")
    os.environ.setdefault("REPO_BACKEND", "memory")
    os.environ.setdefault("DEV_FAKE_LOCATION", "1")
    os.environ.setdefault("JWT_SECRET", "dev-only-jwt-secret-jangan-dipakai-di-produksi")
    os.environ.setdefault("QR_MASTER_KEY", "dev-only-qr-master-key-jangan-dipakai-di-produksi")
    os.environ.setdefault("ALLOWED_ORIGINS", ",".join(
        f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (GURU_PORT, ADMIN_PORT)))
    build(API)
    for site, port in (("teacher", GURU_PORT), ("admin", ADMIN_PORT)):
        threading.Thread(target=serve_static, args=(site, port), daemon=True).start()
    print(f"PWA guru : http://localhost:{GURU_PORT}\nAdmin    : http://localhost:{ADMIN_PORT}\nAPI      : {API}")
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=API_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
