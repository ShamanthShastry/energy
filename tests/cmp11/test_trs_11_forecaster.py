import numpy as np
import pandas as pd
import pytest

from homewatt.cmp11_forecaster import model as fm

TZ = "America/Detroit"


def _has_lgbm():
    try:
        import lightgbm  # noqa: F401
        import numpy as _np

        lightgbm.LGBMRegressor(n_estimators=2, verbose=-1).fit(_np.zeros((10, 2)), _np.zeros(10))
        return True
    except Exception:
        return False


HAS_LGBM = _has_lgbm()


def synthetic_history(days=28, seed=0):
    """Hourly kWh with a daily shape, a weekend effect, and a strong temperature term."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-06-16T00:00", periods=days * 24, freq="h", tz=TZ).tz_convert("UTC")
    local = idx.tz_convert(TZ)
    temp = 26 + 6 * np.sin((local.hour - 9) / 24 * 2 * np.pi) + rng.normal(0, 1.0, len(idx))
    daily = 0.2 + 0.3 * (local.hour >= 18).astype(float) * (local.hour < 23).astype(float)
    weekend = 0.15 * (local.weekday >= 5)
    hvac = np.maximum(0, temp - 22) * 0.12
    kwh = daily + weekend + hvac + rng.normal(0, 0.03, len(idx))
    return pd.Series(np.maximum(0, kwh), index=idx), pd.Series(temp, index=idx)


def test_trs_11_04_split_is_time_ordered_80_20():
    kwh, temp = synthetic_history(28)
    made_at = kwh.index[-1] + pd.Timedelta(hours=1)
    f = fm.forecast_appliance("x", kwh, temp, temp, made_at, TZ, use_lgbm=False)
    assert f.n_train == int(len(kwh) * 0.8) and f.n_test == len(kwh) - f.n_train


def test_trs_11_03_p90_is_never_below_p50_and_horizon_is_168h():
    kwh, temp = synthetic_history(21)
    made_at = kwh.index[-1] + pd.Timedelta(hours=1)
    f = fm.forecast_appliance("x", kwh, temp, temp, made_at, TZ, use_lgbm=False)
    assert len(f.frame) == 168 and (f.frame["kwh_p90"] >= f.frame["kwh_p50"]).all()
    assert f.frame["ts"].iloc[0] == pd.Timestamp(made_at).floor("h")


def test_cmp11_error_handling_short_history_is_naive():
    kwh, temp = synthetic_history(10)
    made_at = kwh.index[-1] + pd.Timedelta(hours=1)
    f = fm.forecast_appliance("x", kwh, temp, temp, made_at, TZ, use_lgbm=True)
    assert f.model_version == "naive" and f.mae_model is None


def test_seasonal_naive_uses_same_hour_previous_week():
    kwh, _ = synthetic_history(14)
    horizon = pd.date_range(kwh.index[-1] + pd.Timedelta(hours=1), periods=168, freq="h", tz="UTC")
    naive = fm.seasonal_naive(kwh, horizon)
    assert naive.iloc[0] == pytest.approx(kwh.loc[horizon[0] - pd.Timedelta(hours=168)])


@pytest.mark.skipif(not HAS_LGBM, reason="lightgbm not usable (brew install libomp)")
def test_trs_11_05_lightgbm_beats_seasonal_naive_on_weather_driven_load_and_logs_mae():
    kwh, temp = synthetic_history(28)
    made_at = kwh.index[-1] + pd.Timedelta(hours=1)
    f = fm.forecast_appliance("hvac", kwh, temp, temp, made_at, TZ, use_lgbm=True)
    assert f.mae_model is not None and f.mae_naive > 0
    assert f.mae_model < f.mae_naive
    assert f.model_version == "lgbm-v1"


@pytest.mark.skipif(not HAS_LGBM, reason="lightgbm not usable (brew install libomp)")
def test_trs_11_05_model_that_does_not_beat_naive_is_not_deployed():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2025-06-16T00:00", periods=28 * 24, freq="h", tz="UTC")
    kwh = pd.Series(rng.random(len(idx)), index=idx)  # pure noise: nothing beats anything reliably
    temp = pd.Series(np.full(len(idx), 25.0), index=idx)
    f = fm.forecast_appliance("noise", kwh, temp, temp, idx[-1] + pd.Timedelta(hours=1), "UTC", use_lgbm=True)
    assert f.model_version in ("naive", "lgbm-v1")
    if f.model_version == "naive":
        assert f.mae_model is not None and f.mae_model >= f.mae_naive


@pytest.mark.skipif(not HAS_LGBM, reason="lightgbm not usable (brew install libomp)")
def test_trs_11_02_horizon_features_use_forecast_weather_only():
    kwh, temp = synthetic_history(28)
    made_at = kwh.index[-1] + pd.Timedelta(hours=1)
    horizon = pd.date_range(pd.Timestamp(made_at).floor("h"), periods=168, freq="h", tz="UTC")
    hot = pd.Series(np.full(168, 35.0), index=horizon)
    cold = pd.Series(np.full(168, 15.0), index=horizon)
    f_hot = fm.forecast_appliance("hvac", kwh, temp, hot, made_at, TZ)
    f_cold = fm.forecast_appliance("hvac", kwh, temp, cold, made_at, TZ)
    assert f_hot.model_version == "lgbm-v1"
    assert f_hot.frame["kwh_p50"].sum() > f_cold.frame["kwh_p50"].sum() * 1.3


def test_trs_11_01_forecaster_emits_kwh_only():
    import inspect

    src = inspect.getsource(fm)
    assert "usd" not in src.lower() and "tariff" not in src.lower()
