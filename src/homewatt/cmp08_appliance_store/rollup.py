"""TRS-08-03: hourly kWh is the time-weighted integral of watts, not the mean of samples.

Realised as sum(watts * dt_s) where dt_s is the interval the sample covers:
  dt_s = ts_i - ts_{i-1} when that is <= GAP_THRESHOLD_S (10 s), else the nominal 2 s.
So a 10-minute gap contributes nothing and the hour integrates over the ~50 covered minutes.
The SQL continuous aggregate in db/init/004 computes exactly this expression; this module is
the same arithmetic in Python for tests, the replay-only path, and CMP-09 batch writes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from homewatt.schema import GAP_THRESHOLD_S, ON_THRESHOLD_W, SAMPLE_PERIOD_S


def assign_dt_s(ts: pd.Series | np.ndarray, prev_ts=None) -> np.ndarray:
    """dt_s for a time-ordered series of one (household, appliance, source, model_version) key.
    `prev_ts` is the last timestamp written before this batch, if any."""
    t = pd.DatetimeIndex(ts).as_unit("ns").asi8 / 1e9  # pandas 3 defaults to µs; be explicit
    if len(t) == 0:
        return np.zeros(0, dtype=np.float32)
    if np.any(np.diff(t) <= 0):
        raise ValueError("timestamps must be strictly increasing within a key")
    prev = np.empty(len(t))
    prev[1:] = t[:-1]
    prev[0] = (pd.Timestamp(prev_ts).as_unit("ns").value / 1e9) if prev_ts is not None else t[0] - SAMPLE_PERIOD_S
    dt = t - prev
    dt = np.where((dt > 0) & (dt <= GAP_THRESHOLD_S), dt, SAMPLE_PERIOD_S)
    return dt.astype(np.float32)


def hourly_kwh(ts: pd.Series, watts: pd.Series, prev_ts=None) -> pd.DataFrame:
    """Per-hour rollup matching appliance_hourly: bucket, kwh, mean_w, on_s, covered_s, n_samples."""
    dt = assign_dt_s(ts, prev_ts)
    w = np.asarray(watts, dtype=np.float64)
    df = pd.DataFrame(
        {
            "bucket": pd.DatetimeIndex(ts).floor("h"),
            "wh": w * dt / 3600.0,
            "dt": dt,
            "on_s": np.where(w > ON_THRESHOLD_W, dt, 0.0),
        }
    )
    g = df.groupby("bucket", sort=True)
    out = pd.DataFrame(
        {
            "kwh": g["wh"].sum() / 1000.0,
            "covered_s": g["dt"].sum(),
            "on_s": g["on_s"].sum(),
            "n_samples": g.size(),
        }
    )
    out["mean_w"] = out["kwh"] * 3.6e6 / out["covered_s"]
    return out.reset_index()


def baseload_residual(aggregate_w: np.ndarray, appliance_w: np.ndarray) -> np.ndarray:
    """TRS-08-05: baseload = aggregate - sum(other appliances), floored at zero, per timestep.
    appliance_w has shape (n, k)."""
    return np.maximum(np.asarray(aggregate_w) - np.asarray(appliance_w).sum(axis=1), 0.0)
