import math
from datetime import UTC, datetime

import pytest

from core.geo import check_location, haversine_m
from core.models import AppError, Settings

LAT, LNG = -6.2, 106.816666
NOW = datetime(2026, 11, 13, 6, 30, tzinfo=UTC)
NOW_MS = NOW.timestamp() * 1000
S = Settings(lat=LAT, lng=LNG, radius_m=100, max_accuracy_m=75)
M_PER_DEG_LAT = math.pi / 180 * 6_371_000  # ≈ 111194.93 m


def north(meters: float) -> float:
    return LAT + meters / M_PER_DEG_LAT


def test_haversine_one_degree_latitude():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_194.93, abs=0.5)


def test_haversine_known_cities():
    # Monas (Jakarta) → Gedung Sate (Bandung): ±119 km garis lurus
    d = haversine_m(-6.175392, 106.827153, -6.902477, 107.618782)
    assert 118_000 < d < 120_000


def test_haversine_symmetric_and_zero():
    assert haversine_m(LAT, LNG, LAT, LNG) == 0
    a = haversine_m(LAT, LNG, -6.3, 106.9)
    assert a == pytest.approx(haversine_m(-6.3, 106.9, LAT, LNG))


def test_99m_passes():
    r = check_location(S, north(99), LNG, 10, NOW_MS, NOW)
    assert r.distance_m == pytest.approx(99, abs=0.1)


def test_101m_rejected_with_distance():
    with pytest.raises(AppError) as e:
        check_location(S, north(101), LNG, 10, NOW_MS, NOW)
    assert e.value.code == "OUT_OF_RANGE"
    assert e.value.extra["distance_m"] == pytest.approx(101, abs=0.1)


def test_far_away_message():
    with pytest.raises(AppError) as e:
        check_location(S, north(340), LNG, 10, NOW_MS, NOW)
    assert "±340 m" in e.value.message


def test_accuracy_75_ok_76_rejected():
    check_location(S, LAT, LNG, 75, NOW_MS, NOW)
    with pytest.raises(AppError) as e:
        check_location(S, LAT, LNG, 76, NOW_MS, NOW)
    assert e.value.code == "LOW_ACCURACY"


def test_stale_location_server_clock_fallback():
    check_location(S, LAT, LNG, 10, NOW_MS - 30_000, NOW)
    with pytest.raises(AppError) as e:
        check_location(S, LAT, LNG, 10, NOW_MS - 31_000, NOW)
    assert e.value.code == "STALE_LOCATION"


def test_stale_location_uses_client_clock_when_given():
    # Jam HP terlambat 5 menit, tapi posisi baru 2 detik → lolos (DECISIONS D1)
    skewed = NOW_MS - 300_000
    r = check_location(S, LAT, LNG, 10, skewed - 2_000, NOW, client_ts_ms=skewed)
    assert r.clock_skew_s == pytest.approx(-300)
    with pytest.raises(AppError) as e:
        check_location(S, LAT, LNG, 10, skewed - 31_000, NOW, client_ts_ms=skewed)
    assert e.value.code == "STALE_LOCATION"


def test_location_not_set():
    with pytest.raises(AppError) as e:
        check_location(Settings(), LAT, LNG, 10, NOW_MS, NOW)
    assert e.value.code == "LOCATION_NOT_SET"
