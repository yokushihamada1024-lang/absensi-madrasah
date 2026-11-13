"""Security headers kedua Static Site. Sumber tunggal untuk dev_server & test yang memeriksa render.yaml."""

from __future__ import annotations

COMMON = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(self), camera=(self), microphone=()",
}


def csp(site: str, api_origin: str) -> str:
    base = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
        f"connect-src 'self' {api_origin}",
        "manifest-src 'self'",
    ]
    if site == "teacher":
        base += ["img-src 'self' data: blob:", "media-src 'self' blob: mediastream:", "worker-src 'self' blob:"]
    else:
        base += ["img-src 'self' data: blob: https://tile.openstreetmap.org", "worker-src 'self'"]
    return "; ".join(base)


def headers(site: str, api_origin: str) -> dict[str, str]:
    h = dict(COMMON)
    if site == "admin":
        h["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=(), screen-wake-lock=(self)"
    h["Content-Security-Policy"] = csp(site, api_origin)
    return h
