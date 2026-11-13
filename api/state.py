"""Kontainer dependensi aplikasi (disimpan di app.state.ctx)."""

from __future__ import annotations

from dataclasses import dataclass

from api.config import AppConfig
from api.ratelimit import LoginRateLimiter
from core.attendance import AttendanceService
from core.repo.base import Repository
from core.timeutil import Clock


@dataclass
class AppContext:
    config: AppConfig
    repo: Repository
    clock: Clock
    svc: AttendanceService
    limiter: LoginRateLimiter
