from datetime import UTC, date, datetime

import pytest

from core.money import format_rupiah
from core.timeutil import (
    format_date_id,
    parse_iso,
    period_bounds,
    period_label,
    to_iso,
    wib_date,
    wib_to_utc,
)


@pytest.mark.parametrize(
    "n,s",
    [(0, "Rp 0"), (500, "Rp 500"), (1000, "Rp 1.000"), (1250000, "Rp 1.250.000"),
     (999999, "Rp 999.999"), (12345678901, "Rp 12.345.678.901"), (-5000, "-Rp 5.000")],
)
def test_format_rupiah(n, s):
    assert format_rupiah(n) == s


def test_month_names_indonesian():
    assert period_label("2026-11") == "November 2026"
    assert period_label("2026-02") == "Februari 2026"
    assert format_date_id(date(2026, 8, 17)) == "17 Agustus 2026"
    assert format_date_id(date(2026, 11, 13), with_day=True) == "Jumat, 13 November 2026"


def test_iso_roundtrip_utc():
    dt = datetime(2026, 11, 13, 6, 30, 5, tzinfo=UTC)
    assert to_iso(dt) == "2026-11-13T06:30:05Z"
    assert parse_iso("2026-11-13T06:30:05Z") == dt
    assert parse_iso("2026-11-13T13:30:05+07:00") == dt


def test_wib_conversion_month_boundary():
    # 30 Nov 23:30 WIB = 30 Nov 16:30 UTC; 1 Des 00:30 WIB = 30 Nov 17:30 UTC
    utc = wib_to_utc(date(2026, 11, 30), "23:30")
    assert utc == datetime(2026, 11, 30, 16, 30, tzinfo=UTC)
    late = datetime(2026, 11, 30, 17, 30, tzinfo=UTC)
    assert wib_date(late) == date(2026, 12, 1)


def test_period_bounds():
    assert period_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))
    assert period_bounds("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    with pytest.raises(ValueError):
        period_bounds("2026-13")
