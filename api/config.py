"""Konfigurasi dari environment variable + validasi aman-untuk-produksi."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AppConfig:
    env: str = "dev"
    repo_backend: str = "memory"
    jwt_secret: str = ""
    qr_master_key: str = ""
    allowed_origins: list[str] = field(default_factory=list)
    database_url: str = ""
    dev_fake_location: bool = False
    max_body_bytes: int = 32 * 1024

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @classmethod
    def from_env(cls) -> AppConfig:
        env = os.environ.get("ENV", "production").strip().lower()
        cfg = cls(
            env=env,
            repo_backend=os.environ.get("REPO_BACKEND", "postgres" if env != "dev" else "memory").strip().lower(),
            jwt_secret=os.environ.get("JWT_SECRET", ""),
            qr_master_key=os.environ.get("QR_MASTER_KEY", ""),
            allowed_origins=[o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
                             if o.strip()],
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            dev_fake_location=_bool(os.environ.get("DEV_FAKE_LOCATION")),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        errors = []
        if self.env not in ("dev", "production"):
            errors.append("ENV harus 'dev' atau 'production'")
        if self.repo_backend not in ("memory", "postgres"):
            errors.append("REPO_BACKEND harus 'memory' atau 'postgres'")
        if self.dev_fake_location and not self.is_dev:
            errors.append("DEV_FAKE_LOCATION hanya boleh aktif saat ENV=dev")
        if not self.is_dev:
            if self.repo_backend == "memory":
                errors.append("REPO_BACKEND=memory dilarang di produksi")
            if len(self.jwt_secret) < 32:
                errors.append("JWT_SECRET minimal 32 karakter di produksi")
            if len(self.qr_master_key) < 32:
                errors.append("QR_MASTER_KEY minimal 32 karakter di produksi")
            if self.jwt_secret and self.jwt_secret == self.qr_master_key:
                errors.append("JWT_SECRET dan QR_MASTER_KEY harus berbeda")
            if not self.allowed_origins:
                errors.append("ALLOWED_ORIGINS wajib diisi di produksi")
            if any(not o.startswith("https://") for o in self.allowed_origins):
                errors.append("ALLOWED_ORIGINS harus https:// di produksi")
        if self.repo_backend == "postgres" and not self.database_url:
            errors.append("DATABASE_URL wajib jika REPO_BACKEND=postgres")
        if not self.jwt_secret or not self.qr_master_key:
            errors.append("JWT_SECRET dan QR_MASTER_KEY wajib diisi")
        if errors:
            raise RuntimeError("Konfigurasi tidak valid: " + "; ".join(errors))
