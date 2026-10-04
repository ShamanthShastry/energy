import numpy as np
import pandas as pd
import pytest

from homewatt.cmp08_appliance_store.rollup import assign_dt_s, baseload_residual, hourly_kwh


def test_trs_08_03_ten_minute_gap_integrates_fifty_minutes_not_sixty():
    """Verification: 10-minute gap in one hour -> kWh equals the integral over 50 minutes."""
    ts = pd.date_range("2025-07-01T10:00Z", periods=1800, freq="2s")  # one hour at 2 s
    keep = ~((ts >= "2025-07-01T10:20Z") & (ts < "2025-07-01T10:30Z"))
    ts = ts[keep]
    watts = pd.Series(np.full(len(ts), 1200.0))
    out = hourly_kwh(pd.Series(ts), watts)
    assert len(out) == 1
    assert out["kwh"].iloc[0] == pytest.approx(1.2 * 50 / 60, rel=1e-3)
    assert out["covered_s"].iloc[0] == pytest.approx(50 * 60, abs=3)
    # the mean-of-samples approach would wrongly say 1.2 kWh
    assert out["kwh"].iloc[0] < 1.2 * 0.9


def test_trs_08_03_dt_is_previous_interval_capped_at_gap_threshold():
    ts = pd.to_datetime(["2025-07-01T00:00:00Z", "2025-07-01T00:00:02Z", "2025-07-01T00:00:05Z", "2025-07-01T00:10:00Z"])
    dt = assign_dt_s(pd.Series(ts))
    assert dt.tolist() == [2.0, 2.0, 3.0, 2.0]  # 595 s gap -> nominal 2 s, not 595


def test_trs_08_03_prev_ts_from_an_earlier_batch_is_honoured():
    ts = pd.to_datetime(["2025-07-01T00:00:04Z", "2025-07-01T00:00:06Z"])
    dt = assign_dt_s(pd.Series(ts), prev_ts=pd.Timestamp("2025-07-01T00:00:00Z"))
    assert dt.tolist() == [4.0, 2.0]


def test_trs_08_03_module_and_python_use_the_same_expression():
    from tests.conftest import REPO

    ts_src = (REPO / "spacetimedb" / "src" / "index.ts").read_text()
    assert "const wh = (watts * dtS) / 3600.0;" in ts_src
    assert "kwh: wh / 1000.0" in ts_src


def test_trs_08_05_baseload_is_residual_floored_at_zero():
    agg = np.array([100.0, 100.0, 50.0])
    apps = np.array([[30.0, 20.0], [60.0, 50.0], [0.0, 0.0]])
    np.testing.assert_array_equal(baseload_residual(agg, apps), [50.0, 0.0, 50.0])


def test_trs_08_02_nilm_rows_without_model_version_are_refused_before_the_db():
    from homewatt.cmp08_appliance_store.writer import AppliancePowerWriter

    w = AppliancePowerWriter(client=None)
    df = pd.DataFrame({"household_id": ["h"], "appliance_id": ["a"], "ts": pd.to_datetime(["2025-07-01T00:00:00Z"]), "watts": [1.0]})
    with pytest.raises(ValueError, match="TRS-08-02"):
        w.write_frame(df, source="nilm", model_version="")
    with pytest.raises(ValueError):
        w.write_frame(df, source="plug", model_version="v1")
