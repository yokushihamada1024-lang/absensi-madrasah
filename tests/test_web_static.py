"""Pemeriksaan statis frontend: aturan XSS, manifest PWA, service worker, CSP."""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
FORBIDDEN = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\s*\(|new Function)\b")


def own_js():
    for p in WEB.rglob("*.js"):
        rel = p.relative_to(WEB).as_posix()
        if "/vendor/" in rel or rel.startswith(("teacher/shared/", "admin/shared/")) or rel.endswith("config.js"):
            continue
        yield p


def test_no_html_injection_apis():
    files = list(own_js())
    assert any(p.name == "app.js" for p in files)
    for p in files:
        src = p.read_text(encoding="utf-8")
        assert not FORBIDDEN.search(src), f"{p} memakai API HTML mentah"


def test_no_inline_script_or_style_or_third_party():
    for p in WEB.rglob("*.html"):
        if "/vendor/" in p.as_posix():
            continue
        html = p.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), f"{p}: script inline"
        assert "style=" not in html and "<style" not in html, f"{p}: style inline (diblokir CSP)"
        assert not re.search(r"""(src|href)=["']https?://""", html), f"{p}: aset pihak ketiga"


def test_manifest():
    m = json.loads((WEB / "teacher" / "manifest.webmanifest").read_text(encoding="utf-8"))
    for k in ("name", "short_name", "start_url", "scope", "display", "theme_color"):
        assert m.get(k)
    assert m["display"] == "standalone"
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes and ("512x512", "maskable") in sizes
    for i in m["icons"]:
        assert (WEB / "teacher" / i["src"]).exists()


def test_service_worker_never_caches_api():
    sw = (WEB / "teacher" / "sw.js").read_text(encoding="utf-8")
    assert "url.origin !== self.location.origin" in sw and '"/api/"' in sw
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "api" not in shell.lower().replace("shared/api.js", "")
    for f in re.findall(r'"([^"]+)"', shell):
        if f in ("./", "config.js") or f.startswith("shared/"):
            continue  # config.js & shared/ dibuat saat build
        assert (WEB / "teacher" / f).exists(), f


def test_vendor_files_and_licenses_present():
    assert (WEB / "teacher" / "vendor" / "qr-scanner" / "LICENSE").exists()
    assert (WEB / "teacher" / "vendor" / "qr-scanner" / "qr-scanner-worker.min.js").exists()


def test_osm_tiles_send_referer():
    """Halaman admin no-referrer; tile OSM wajib Referer (kalau tidak: 403 'Access blocked')."""
    src = (WEB / "admin" / "pages" / "pengaturan.js").read_text(encoding="utf-8")
    assert 'referrerPolicy: "strict-origin-when-cross-origin"' in src
