"""Konsistensi konfigurasi deploy & kebersihan repo dari secret."""

import re
import subprocess
from pathlib import Path

from scripts.web_headers import headers

ROOT = Path(__file__).resolve().parents[1]
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")


def test_render_has_three_free_services():
    names = re.findall(r"name: (absensi-[a-z]+)", RENDER)
    assert names == ["absensi-api", "absensi-guru", "absensi-admin"]
    assert RENDER.count("runtime: static") == 2
    assert "plan: free" in RENDER and "numInstances: 1" in RENDER
    assert "healthCheckPath: /healthz" in RENDER
    assert "uvicorn api.main:app --host 0.0.0.0 --port $PORT" in RENDER


def test_render_secrets_not_committed():
    for key in ("DATABASE_URL", "ALLOWED_ORIGINS"):
        block = RENDER.split(f"key: {key}", 1)[1].split("\n")[1]
        assert "sync: false" in block, key
    for key in ("JWT_SECRET", "QR_MASTER_KEY"):
        block = RENDER.split(f"key: {key}", 1)[1].split("\n")[1]
        assert "generateValue: true" in block, key
    assert "value: production" in RENDER and "DEV_FAKE_LOCATION" not in RENDER


def test_render_csp_matches_web_headers():
    for site in ("teacher", "admin"):
        for name, value in headers(site, "https://*.onrender.com").items():
            assert value in RENDER, (site, name)


def test_no_secrets_tracked_in_git():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    bad_names = [f for f in files if re.search(r"(^|/)\.env$|service-account|credentials.*\.json|\.pem$|\.key$", f)]
    assert not bad_names
    pattern = re.compile(
        r"-----BEGIN (RSA |EC )?PRIVATE KEY-----|\"private_key\"\s*:|postgres(ql)?://postgres\.[a-z0-9]{10,}:[^<@\s]+@"
    )
    for f in files:
        p = ROOT / f
        if p.suffix in {".png", ".pdf", ".zip"} or "/vendor/" in f:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        assert not pattern.search(text), f


def test_env_example_present_and_gitignore_covers_env():
    assert (ROOT / ".env.example").exists()
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi and "!.env.example" in gi
