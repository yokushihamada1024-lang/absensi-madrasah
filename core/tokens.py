"""Token QR berputar (HMAC) dan ticket absensi (JWT pendek)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from core.models import AppError

TICKET_TTL_S = 300
SIG_BYTES = 16


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def session_key(master_key: str, session_id: str) -> bytes:
    return hmac.new(master_key.encode(), session_id.encode(), hashlib.sha256).digest()


def current_slot(now: datetime, rotate_sec: int) -> int:
    return math.floor(now.timestamp() / rotate_sec)


def slot_expires_at(slot: int, rotate_sec: int) -> datetime:
    """Saat slot ini berhenti menjadi 'current' (QR layar harus diganti)."""
    return datetime.fromtimestamp((slot + 1) * rotate_sec, tz=UTC)


def make_qr_token(master_key: str, session_id: str, slot: int) -> str:
    key = session_key(master_key, session_id)
    sig = hmac.new(key, f"{session_id}.{slot}".encode(), hashlib.sha256).digest()[:SIG_BYTES]
    return f"{_b64e(session_id.encode())}.{slot}.{_b64e(sig)}"


def verify_qr_token(
    master_key: str,
    token: str,
    now: datetime,
    rotate_sec: int,
    expected_session_id: str | None = None,
) -> str:
    """Kembalikan session_id jika valid. Raise AppError TOKEN_INVALID / TOKEN_EXPIRED."""
    invalid = AppError("TOKEN_INVALID", "QR tidak dikenali. Scan QR di layar admin.", 400)
    if not isinstance(token, str) or len(token) > 200:
        raise invalid
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise invalid
    sid_b64, slot_s, sig_b64 = parts
    try:
        session_id = _b64d(sid_b64).decode("utf-8")
        slot = int(slot_s)
        sig = _b64d(sig_b64)
        uuid.UUID(session_id)
    except (ValueError, UnicodeDecodeError):
        raise invalid from None
    # Tolak bentuk non-kanonik (base64 longgar soal bit sisa; slot tanpa nol di depan)
    if str(slot) != slot_s or _b64e(sig) != sig_b64 or _b64e(session_id.encode()) != sid_b64:
        raise invalid
    key = session_key(master_key, session_id)
    expected = hmac.new(key, f"{session_id}.{slot}".encode(), hashlib.sha256).digest()[:SIG_BYTES]
    if not hmac.compare_digest(sig, expected):
        raise invalid
    if expected_session_id is not None and session_id != expected_session_id:
        raise invalid
    cur = current_slot(now, rotate_sec)
    if slot not in (cur, cur - 1):
        raise AppError("TOKEN_EXPIRED", "QR sudah basi. Scan QR terbaru di layar admin.", 400)
    return session_id


# --- Ticket ---------------------------------------------------------------


def _ticket_key(jwt_secret: str) -> bytes:
    return hmac.new(jwt_secret.encode(), b"ticket-v1", hashlib.sha256).digest()


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    session_id: str
    user_id: str
    scanned_at: datetime
    distance_m: float
    accuracy_m: float
    lat: float
    lng: float
    method: str = "scan"  # "scan" (QR) atau "button" (konfirmasi tanpa QR)


def issue_ticket(jwt_secret: str, t: Ticket) -> tuple[str, datetime]:
    exp = t.scanned_at + timedelta(seconds=TICKET_TTL_S)
    payload = {
        "typ": "ticket",
        "tid": t.ticket_id,
        "sid": t.session_id,
        "uid": t.user_id,
        "sat": t.scanned_at.timestamp(),
        "dist": t.distance_m,
        "acc": t.accuracy_m,
        "lat": t.lat,
        "lng": t.lng,
        "mth": t.method,
        "iat": int(t.scanned_at.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, _ticket_key(jwt_secret), algorithm="HS256"), exp


def decode_ticket(jwt_secret: str, token: str, now: datetime) -> Ticket:
    try:
        p = jwt.decode(
            token,
            _ticket_key(jwt_secret),
            algorithms=["HS256"],
            options={"require": ["exp", "iat"], "verify_exp": False, "verify_iat": False, "verify_nbf": False},
        )
    except jwt.PyJWTError:
        raise AppError("TICKET_INVALID", "Tiket absen tidak valid. Silakan scan ulang.", 400) from None
    if p.get("typ") != "ticket":
        raise AppError("TICKET_INVALID", "Tiket absen tidak valid. Silakan scan ulang.", 400)
    # exp dicek manual memakai jam yang diinjeksi (testable)
    if now.timestamp() > p["exp"]:
        raise AppError("TICKET_EXPIRED", "Waktu memilih kelas habis (5 menit). Silakan scan ulang.", 400)
    method = p.get("mth", "scan")
    if method not in ("scan", "button"):
        raise AppError("TICKET_INVALID", "Tiket absen tidak valid. Silakan scan ulang.", 400)
    return Ticket(
        ticket_id=p["tid"],
        session_id=p["sid"],
        user_id=p["uid"],
        scanned_at=datetime.fromtimestamp(p["sat"], tz=UTC),
        distance_m=p["dist"],
        accuracy_m=p["acc"],
        lat=p["lat"],
        lng=p["lng"],
        method=method,
    )
