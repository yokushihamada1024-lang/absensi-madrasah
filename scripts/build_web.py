"""Siapkan Static Site lokal: salin web/shared ke tiap site + buat config.js dari API_BASE_URL.

Render melakukan hal yang sama lewat buildCommand di render.yaml.
Pakai:  python -m scripts.build_web            (API_BASE_URL default http://localhost:8000)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def build(api_base_url: str) -> None:
    for site in ("teacher", "admin"):
        dst = WEB / site / "shared"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(WEB / "shared", dst)
        (WEB / site / "config.js").write_text(f"export const API_BASE_URL = {api_base_url!r};\n".replace("'", '"'),
                                              encoding="utf-8")


def main() -> int:
    url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    build(url)
    print(f"web/teacher & web/admin siap (API_BASE_URL={url})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
