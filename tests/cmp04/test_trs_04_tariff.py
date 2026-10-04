from datetime import date

import pandas as pd
import pytest

from homewatt.cmp04_tariff.model import (
    Period,
    Season,
    Tariff,
    TariffError,
    flat_tariff,
    load_tariff,
)
from tests.conftest import REPO

DTE = REPO / "config" / "tariffs" / "dte_d1_11.yaml"


def local(ts: str, tz="America/Detroit"):
    return pd.Timestamp(ts, tz=tz).tz_convert("UTC")


def test_trs_04_verification_two_period_plan_peak_and_off_peak():
    t = load_tariff(DTE)
    assert t.rate(local("2025-07-08T17:00")).period_name == "peak"  # Tuesday 17:00
    assert t.rate(local("2025-07-08T21:00")).period_name == "off_peak"  # Tuesday 21:00
    assert t.rate(local("2025-07-08T17:00")).usd_per_kwh == pytest.approx(0.24133)
    assert t.rate(local("2025-07-08T21:00")).usd_per_kwh == pytest.approx(0.18435)


def test_trs_04_01_seasons_summer_and_non_summer_coexist():
    t = load_tariff(DTE)
    assert t.rate(local("2025-11-04T17:00")).usd_per_kwh == pytest.approx(0.20045)
    assert t.rate(local("2025-11-04T17:00")).season == "non_summer"
    assert t.rate(local("2025-07-08T17:00")).season == "summer"


def test_trs_04_01_weekend_and_holiday_are_off_peak_all_day():
    t = load_tariff(DTE)
    assert t.rate(local("2025-07-12T17:00")).period_name == "off_peak"  # Saturday
    assert t.rate(local("2025-07-04T17:00")).period_name == "off_peak"  # Independence Day (Friday)
    assert t.day_type(date(2025, 7, 4)) == "holiday"


def test_trs_04_verification_missing_hours_fail_naming_them():
    t = load_tariff(DTE)
    bad = t.model_copy(deep=True)
    bad.seasons[0].periods = [p for p in bad.seasons[0].periods if not (p.start_hour == 19 and "weekday" in p.days)]
    bad.seasons[0].periods.append(Period(name="late", days=["weekday"], start_hour=21, end_hour=24, usd_per_kwh=0.18))
    with pytest.raises(TariffError) as e:
        bad.check_coverage()
    assert "19-20, 20-21" in str(e.value) and "weekday" in str(e.value)


def test_trs_04_01_overlap_is_rejected():
    t = load_tariff(DTE)
    bad = t.model_copy(deep=True)
    bad.seasons[0].periods.append(Period(name="dup", days=["weekday"], start_hour=16, end_hour=17, usd_per_kwh=0.1))
    with pytest.raises(TariffError, match="covered twice"):
        bad.check_coverage()


def test_trs_04_01_season_gap_is_rejected():
    t = load_tariff(DTE)
    bad = t.model_copy(deep=True)
    bad.seasons[1].end = "05-30"
    with pytest.raises(TariffError, match="not in any season"):
        bad.check_coverage()


def test_trs_04_02_flat_plan_is_one_period_and_flagged_flat():
    f = flat_tariff(0.17)
    f.check_coverage()
    assert f.is_flat and f.peak_window(date(2025, 7, 8)) is None
    assert not load_tariff(DTE).is_flat
    assert load_tariff(DTE).peak_window(date(2025, 7, 8)) == (15, 19)
    assert load_tariff(DTE).peak_window(date(2025, 7, 12)) is None  # Saturday


def test_trs_04_03_every_rate_row_carries_valid_from():
    rows = load_tariff(DTE).period_rows()
    assert rows and all(r["valid_from"] == "2025-02-06" for r in rows)


def test_trs_04_05_fixed_charge_is_stored_but_not_in_rates():
    t = load_tariff(DTE)
    assert t.fixed_usd_per_month == 8.50
    r = t.rates(pd.date_range("2025-07-01", periods=48, freq="h", tz="UTC"))
    assert set(r.columns) == {"usd_per_kwh", "kg_co2_per_kwh", "period_name", "season"}
    assert (r["usd_per_kwh"] < 0.30).all() and (r["kg_co2_per_kwh"] == 0.51).all()
    assert all("kg_co_2_per_kwh" in row for row in t.period_rows())


def test_rates_vectorised_matches_scalar():
    t = load_tariff(DTE)
    idx = pd.date_range("2025-07-07T00:00", periods=24 * 7, freq="h", tz="America/Detroit").tz_convert("UTC")
    v = t.rates(idx)
    for i in (0, 17, 40, 100, 167):
        assert v.loc[i, "usd_per_kwh"] == pytest.approx(t.rate(idx[i]).usd_per_kwh)
    assert (v["period_name"] == "peak").sum() == 5 * 4  # five weekdays x four peak hours


def test_tariff_model_requires_tz_aware():
    with pytest.raises(TariffError):
        load_tariff(DTE).rate(pd.Timestamp("2025-07-08T17:00"))
    Season(name="x", start="01-01", end="12-31", periods=[])
    Tariff  # noqa: B018
