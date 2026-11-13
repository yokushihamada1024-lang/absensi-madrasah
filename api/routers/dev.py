"""Endpoint khusus pengembangan lokal. Hanya di-mount jika ENV=dev (lihat api/main.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import ctx, current_user
from api.state import AppContext
from core.models import User

router = APIRouter(prefix="/api/dev")


@router.get("/config")
def dev_config(c: AppContext = Depends(ctx)) -> dict:
    s = c.repo.settings.get()
    return {"fake_location": c.config.dev_fake_location, "lat": s.lat, "lng": s.lng}


@router.get("/qr-token")
def dev_qr_token(user: User = Depends(current_user), c: AppContext = Depends(ctx)) -> dict:
    """Token QR sesi aktif — pengganti kamera saat uji di laptop."""
    active = c.svc.active_sessions()
    if not active:
        return {"token": None}
    return {"token": c.svc.qr(active[0].session_id).token}
