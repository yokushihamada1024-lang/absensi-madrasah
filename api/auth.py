"""Access token JWT + dependency FastAPI untuk user saat ini."""

from __future__ import annotations

from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Request

from api.state import AppContext
from core.models import AppError, User

GURU_TTL = timedelta(days=30)
ADMIN_TTL = timedelta(hours=8)


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def issue_access_token(secret: str, user: User, now: datetime) -> tuple[str, datetime]:
    exp = now + (ADMIN_TTL if user.role == "admin" else GURU_TTL)
    payload = {
        "typ": "access",
        "sub": user.user_id,
        "role": user.role,
        "tv": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256"), exp


def _unauth(msg: str = "Silakan login kembali.") -> AppError:
    return AppError("UNAUTHENTICATED", msg, 401)


def current_user(request: Request, c: AppContext = Depends(ctx)) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauth()
    try:
        p = jwt.decode(
            token.strip(),
            c.config.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"], "verify_exp": False, "verify_iat": False},
        )
    except jwt.PyJWTError:
        raise _unauth() from None
    if p.get("typ") != "access":
        raise _unauth()
    if c.clock().timestamp() > p["exp"]:
        raise _unauth("Sesi login habis. Silakan login kembali.")
    user = c.repo.users.get(p["sub"])
    if user is None or not user.active or user.token_version != p.get("tv") or user.role != p.get("role"):
        raise _unauth()
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise AppError("FORBIDDEN", "Hanya admin yang boleh mengakses.", 403)
    return user


def require_guru(user: User = Depends(current_user)) -> User:
    if user.role != "guru":
        raise AppError("FORBIDDEN", "Hanya guru yang boleh absen.", 403)
    return user


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"
