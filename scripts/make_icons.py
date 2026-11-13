"""Buat ikon PWA (PNG) tanpa Pillow: latar hijau tosca + tanda centang putih.

Pakai:  python -m scripts.make_icons
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "teacher" / "icons"
BG = (15, 118, 110)  # #0f766e
FG = (255, 255, 255)


def _png(w: int, h: int, rows: list[bytes]) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size: int, maskable: bool) -> bytes:
    s = 3  # supersampling
    radius = 0 if maskable else 0.22
    scale = 0.95 if maskable else 1.25  # maskable: konten tetap di dalam safe zone
    pts = [(-0.30, 0.02), (-0.08, 0.24), (0.32, -0.20)]
    thick = 0.075
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc_bg = acc_fg = 0
            for sy in range(s):
                for sx in range(s):
                    u = (x + (sx + 0.5) / s) / size * 2 - 1
                    v = (y + (sy + 0.5) / s) / size * 2 - 1
                    inside = True
                    if radius:
                        qx, qy = max(abs(u) - (1 - radius * 2), 0), max(abs(v) - (1 - radius * 2), 0)
                        inside = math.hypot(qx, qy) <= radius * 2
                    if not inside:
                        continue
                    acc_bg += 1
                    cu, cv = u / scale, v / scale
                    d = min(_seg_dist(cu, cv, *pts[0], *pts[1]), _seg_dist(cu, cv, *pts[1], *pts[2]))
                    if d <= thick:
                        acc_fg += 1
            n = s * s
            a = acc_bg / n
            f = acc_fg / max(acc_bg, 1)
            rgb = [round(BG[i] * (1 - f) + FG[i] * f) for i in range(3)]
            row += bytes(rgb + [round(a * 255)])
        rows.append(bytes(row))
    return _png(size, size, rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, mask in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                             ("maskable-512.png", 512, True), ("apple-touch-icon.png", 180, True)):
        (OUT / name).write_bytes(render(size, mask))
        print("tulis", OUT / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
