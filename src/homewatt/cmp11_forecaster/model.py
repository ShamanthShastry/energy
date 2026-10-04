"""LightGBM per appliance with a seasonal-naive baseline and a time-ordered 80/20 evaluation.

TRS-11-02 features: lag_1h, lag_24h, lag_168h, temp_c, hour, weekday, is_weekend. Weather for
future hours is the forecast value; the pipeline passes the horizon weather frame separately
so no observed value can leak past made_at.
TRS-11-03 p50 and p90: p90 = p50 + the 90th percentile of validation residuals (never below p50).
TRS-11-04 split: first 80% train, last 20% test, in time order. No shuffling anywhere.
TRS-11-05 per-appliance MAE stored with the model version; the model is deployed only if it
beats seasonal-naive (same hour, previous week); otherwise that appliance is forecast naively
with model_version 'naive'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

MODEL_VERSION = "lgbm-v1"
NAIVE_VERSION = "naive"
HORIZON_H = 168
MIN_HISTORY_DAYS = 14
FEATURES = ["lag_1h", "lag_24h", "lag_168h", "temp_c", "hour", "weekday", "is_weekend"]

LGBM_PARAMS = dict(
    n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=8,
    subsample=0.9, subsample_freq=1, colsample_bytree=0.9, reg_lambda=1.0, verbose=-1, random_state=7,
)


@dataclass
class ApplianceForecast:
    appliance_id: str
    model_version: str
    frame: pd.DataFrame  # ts, kwh_p50, kwh_p90
    mae_model: float | None
    mae_naive: float
    n_train: int
    n_test: int
    residual_q90: float


@dataclass
class ForecastRun:
    made_at: datetime
    forecasts: list[ApplianceForecast] = field(default_factory=list)

    def frame(self) -> pd.DataFrame:
        parts = [f.frame.assign(appliance_id=f.appliance_id, model_version=f.model_version) for f in self.forecasts]
        return pd.concat(parts, ignore_index=True)[["appliance_id", "ts", "kwh_p50", "kwh_p90", "model_version"]]

    def metrics(self) -> list[dict]:
        rows = []
        for f in self.forecasts:
            rows.append({"appliance_id": f.appliance_id, "model_version": f.model_version, "metric": "mae_kwh_h_naive", "value": f.mae_naive})
            if f.mae_model is not None:
                rows.append({"appliance_id": f.appliance_id, "model_version": MODEL_VERSION, "metric": "mae_kwh_h", "value": f.mae_model})
        return rows


def _calendar(idx: pd.DatetimeIndex, tz: str) -> pd.DataFrame:
    local = idx.tz_convert(tz)
    return pd.DataFrame({"hour": local.hour, "weekday": local.weekday, "is_weekend": (local.weekday >= 5).astype(int)}, index=idx)


def build_features(kwh: pd.Series, temp_c: pd.Series, tz: str) -> pd.DataFrame:
    """Training features for a contiguous hourly history. kwh and temp_c are indexed by UTC hour."""
    df = pd.DataFrame({"kwh": kwh.astype(float)})
    df["lag_1h"] = df["kwh"].shift(1)
    df["lag_24h"] = df["kwh"].shift(24)
    df["lag_168h"] = df["kwh"].shift(168)
    df["temp_c"] = temp_c.reindex(df.index).astype(float)
    df = df.join(_calendar(df.index, tz))
    return df


def seasonal_naive(history: pd.Series, horizon_index: pd.DatetimeIndex) -> pd.Series:
    """Same hour, previous week; falls back to the same hour yesterday, then the history mean."""
    h = history.astype(float)
    out = []
    mean = float(h.mean()) if len(h) else 0.0
    for ts in horizon_index:
        for lag in (pd.Timedelta(hours=168), pd.Timedelta(hours=24)):
            v = h.get(ts - lag)
            if v is not None and not np.isnan(v):
                out.append(float(v))
                break
        else:
            out.append(mean)
    return pd.Series(out, index=horizon_index)


def _naive_in_sample(kwh: pd.Series) -> pd.Series:
    """Naive prediction for every historical hour (lag 168, else lag 24)."""
    return kwh.shift(168).fillna(kwh.shift(24))


def _fit_lgbm(X: pd.DataFrame, y: pd.Series):
    import lightgbm as lgb

    m = lgb.LGBMRegressor(**LGBM_PARAMS)
    m.fit(X, y)
    return m


def _recursive_forecast(model, history: pd.Series, horizon_index: pd.DatetimeIndex, temp_c_forecast: pd.Series, tz: str) -> pd.Series:
    """Hour-by-hour prediction; lags inside the horizon use predictions (never observed data)."""
    series = history.astype(float).copy()
    cal = _calendar(horizon_index, tz)
    preds = []
    for ts in horizon_index:
        row = {
            "lag_1h": series.get(ts - pd.Timedelta(hours=1), np.nan),
            "lag_24h": series.get(ts - pd.Timedelta(hours=24), np.nan),
            "lag_168h": series.get(ts - pd.Timedelta(hours=168), np.nan),
            "temp_c": float(temp_c_forecast.get(ts, np.nan)),
            "hour": cal.loc[ts, "hour"], "weekday": cal.loc[ts, "weekday"], "is_weekend": cal.loc[ts, "is_weekend"],
        }
        p = max(0.0, float(model.predict(pd.DataFrame([row])[FEATURES])[0]))
        preds.append(p)
        series.loc[ts] = p
    return pd.Series(preds, index=horizon_index)


def forecast_appliance(appliance_id: str, kwh: pd.Series, temp_c_hist: pd.Series, temp_c_forecast: pd.Series,
                       made_at: datetime, tz: str, use_lgbm: bool = True) -> ApplianceForecast:
    """kwh: hourly history indexed by UTC hour, ending before made_at. temp_c_hist covers the
    history; temp_c_forecast covers the horizon (forecast values only, TRS-11-02)."""
    made = pd.Timestamp(made_at).floor("h")
    horizon = pd.date_range(made, periods=HORIZON_H, freq="h", tz="UTC")
    kwh = kwh.sort_index()
    kwh = kwh[kwh.index < made]
    days = len(kwh) / 24.0

    # time-ordered 80/20 (TRS-11-04)
    n = len(kwh)
    split = int(n * 0.8)
    test_idx = kwh.index[split:]
    naive_pred = _naive_in_sample(kwh).loc[test_idx]
    ok = naive_pred.notna()
    mae_naive = float((naive_pred[ok] - kwh.loc[test_idx][ok]).abs().mean()) if ok.any() else float("nan")

    mae_model = None
    model = None
    if use_lgbm and days >= MIN_HISTORY_DAYS:
        feats = build_features(kwh, temp_c_hist, tz)
        train = feats.iloc[:split].dropna(subset=["lag_1h"])
        test = feats.iloc[split:].dropna(subset=["lag_1h"])
        if len(train) >= 48 and len(test) >= 12:
            m = _fit_lgbm(train[FEATURES], train["kwh"])
            pred = np.maximum(0.0, m.predict(test[FEATURES]))
            mae_model = float(np.abs(pred - test["kwh"].to_numpy()).mean())
            if np.isnan(mae_naive) or mae_model < mae_naive:
                model = _fit_lgbm(feats.dropna(subset=["lag_1h"])[FEATURES], feats.dropna(subset=["lag_1h"])["kwh"])
                resid = test["kwh"].to_numpy() - pred
            else:
                model = None

    if model is not None:
        p50 = _recursive_forecast(model, kwh, horizon, temp_c_forecast, tz)
        version = MODEL_VERSION
    else:
        p50 = seasonal_naive(kwh, horizon)
        version = NAIVE_VERSION
        resid = (kwh.loc[test_idx][ok] - naive_pred[ok]).to_numpy() if ok.any() else np.zeros(1)
    q90 = float(max(0.0, np.quantile(resid, 0.9))) if len(resid) else 0.0
    frame = pd.DataFrame({"ts": horizon, "kwh_p50": p50.to_numpy(), "kwh_p90": p50.to_numpy() + q90})
    return ApplianceForecast(appliance_id, version, frame, mae_model, mae_naive, split, n - split, q90)


def forecast_household(history: pd.DataFrame, weather_hist: pd.Series, weather_forecast: pd.Series,
                       made_at: datetime, tz: str, use_lgbm: bool = True) -> ForecastRun:
    """history: columns appliance_id, ts (UTC hour), kwh. One ApplianceForecast per appliance."""
    run = ForecastRun(made_at=made_at)
    for app, g in history.groupby("appliance_id"):
        s = g.set_index("ts")["kwh"].astype(float)
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="h", tz="UTC")).fillna(0.0)
        run.forecasts.append(forecast_appliance(app, s, weather_hist, weather_forecast, made_at, tz, use_lgbm))
    return run
