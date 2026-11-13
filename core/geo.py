"""Geofence: haversine + validasi lokasi."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from core.models import AppError, Settings

EARTH_RADIUS_M = 6_371_000.0
MAX_POSITION_AGE_S = 30.0
MAX_FUTURE_SKEW_S = 5.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


@dataclass(frozen=True)
class LocationCheck:
    distance_m: float
    accuracy_m: float
    clock_skew_s: float | None


def check_location(
    settings: Settings,
    lat: float,
    lng: float,
    accuracy_m: float,
    position_ts_ms: float,
    server_now: datetime,
    client_ts_ms: float | None = None,
) -> LocationCheck:
    """Validasi lokasi. Urutan: STALE_LOCATION → LOW_ACCURACY → OUT_OF_RANGE.

    Umur posisi dihitung dari jam HP sendiri (client_ts - position_ts) jika client_ts ada,
    sehingga jam HP yang meleset tidak membuat guru jujur ditolak (DECISIONS D1).
    """
    if not settings.location_set:
        raise AppError("LOCATION_NOT_SET", "Lokasi madrasah belum diatur admin.", 409)
    server_ms = server_now.timestamp() * 1000
    skew = None
    if client_ts_ms is not None:
        age_s = (client_ts_ms - position_ts_ms) / 1000
        skew = round((client_ts_ms - server_ms) / 1000, 1)
    else:
        age_s = (server_ms - position_ts_ms) / 1000
    distance = haversine_m(settings.lat, settings.lng, lat, lng)  # type: ignore[arg-type]
    distance_r = round(distance, 1)
    if age_s > MAX_POSITION_AGE_S or age_s < -MAX_FUTURE_SKEW_S:
        raise AppError(
            "STALE_LOCATION",
            "Data lokasi sudah kedaluwarsa. Coba scan lagi.",
            422,
            age_s=round(age_s, 1),
            clock_skew_s=skew,
            distance_m=distance_r,
            accuracy_m=accuracy_m,
        )
    if accuracy_m > settings.max_accuracy_m:
        raise AppError(
            "LOW_ACCURACY",
            f"Sinyal GPS lemah (akurasi ±{round(accuracy_m)} m). Pindah ke dekat jendela/luar ruangan lalu coba lagi.",
            422,
            accuracy_m=accuracy_m,
            max_accuracy_m=settings.max_accuracy_m,
            distance_m=distance_r,
            clock_skew_s=skew,
        )
    if distance > settings.radius_m:
        raise AppError(
            "OUT_OF_RANGE",
            f"Anda ±{round(distance)} m dari madrasah (maks {round(settings.radius_m)} m).",
            422,
            distance_m=distance_r,
            radius_m=settings.radius_m,
            accuracy_m=accuracy_m,
            clock_skew_s=skew,
        )
    return LocationCheck(distance_m=distance_r, accuracy_m=accuracy_m, clock_skew_s=skew)
