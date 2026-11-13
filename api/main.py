"""FastAPI app. Jalankan: uvicorn api.main:app --host 0.0.0.0 --port $PORT"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import AppConfig
from api.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from api.ratelimit import LoginRateLimiter
from api.routers import admin, dev, guru
from api.state import AppContext
from core.attendance import AttendanceService
from core.models import AppError
from core.repo.base import Repository
from core.timeutil import Clock, system_clock, to_iso

log = logging.getLogger("absensi")


def build_repo(config: AppConfig) -> Repository:
    if config.repo_backend == "postgres":
        from core.repo.postgres import PostgresRepository

        return PostgresRepository(config.database_url)
    from core.repo.memory import InMemoryRepository

    repo = InMemoryRepository()
    if config.is_dev:
        from scripts.dev_seed import seed_demo

        seed_demo(repo)
    return repo


def _err(code: str, message: str, status: int, **extra) -> JSONResponse:
    headers = {"Retry-After": str(extra["retry_after"])} if "retry_after" in extra else None
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status, headers=headers)


def create_app(config: AppConfig | None = None, repo: Repository | None = None, clock: Clock | None = None) -> FastAPI:
    config = config or AppConfig.from_env()
    config.validate()
    clock = clock or system_clock
    repo = repo or build_repo(config)

    app = FastAPI(
        title="Absensi Madrasah API",
        docs_url="/docs" if config.is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.is_dev else None,
    )
    app.state.ctx = AppContext(
        config=config,
        repo=repo,
        clock=clock,
        svc=AttendanceService(repo, clock, config.qr_master_key, config.jwt_secret),
        limiter=LoginRateLimiter(clock),
    )

    @app.exception_handler(AppError)
    def _app_error(_: Request, e: AppError) -> JSONResponse:
        return _err(e.code, e.message, e.status, **e.extra)

    @app.exception_handler(RequestValidationError)
    def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        fields = [{"field": ".".join(str(x) for x in err.get("loc", [])[1:]), "message": err.get("msg", "")}
                  for err in e.errors()]
        return _err("VALIDATION_ERROR", "Data yang dikirim tidak valid.", 422, fields=fields)

    @app.exception_handler(StarletteHTTPException)
    def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR")
        return _err(code, str(e.detail), e.status_code)

    @app.exception_handler(Exception)
    def _unhandled(_: Request, e: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", type(e).__name__)
        return _err("INTERNAL", "Terjadi kesalahan di server. Coba lagi.", 500)

    @app.get("/healthz")
    def healthz() -> dict:
        # Tanpa auth, tanpa menyentuh database: untuk health check Render & ping pemanasan.
        return {"ok": True, "time": to_iso(clock())}

    app.include_router(guru.router)
    app.include_router(admin.router)
    if config.is_dev:
        app.include_router(dev.router)

    # Urutan: middleware terakhir ditambahkan = terluar.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=config.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=not config.is_dev)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """`api.main:app` dibuat malas (saat uvicorn mengaksesnya), sehingga test bisa mengimpor
    create_app tanpa environment produksi."""
    global _app
    if name != "app":
        raise AttributeError(name)
    if _app is None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        _app = create_app()
    return _app
