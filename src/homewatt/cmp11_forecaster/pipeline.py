"""Store-facing CMP-11 run: read sim/plug/nilm hourly rollups and weather, forecast, write
forecast rows (TRS-11-07) and metrics (TRS-11-05)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from homewatt.cmp03_weather.store import MAX_FORECAST_AGE, forecast_age, read_weather
from homewatt.cmp08_appliance_store.reader import read_hourly
from homewatt.cmp11_forecaster.model import (
    HORIZON_H,
    MIN_HISTORY_DAYS,
    ForecastRun,
    forecast_household,
)
from homewatt.spacetime import us, us_array

log = logging.getLogger(__name__)
SOURCE_PREFERENCE = ("plug", "nilm", "sim")  # TRS-08-01 (v0.12): the splitter estimate before the simulated feed


def preferred_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    """One row per (appliance, bucket): plug > nilm > sim (v0.12); latest model_version within a source."""
    if hourly.empty:
        return hourly
    from homewatt.cmp09_nilm.runner import deployed_version

    pref = {s: i for i, s in enumerate(SOURCE_PREFERENCE)}
    dep = deployed_version()  # the deployed splitter's rows first among nilm versions (data/models/deployed.json)
    h = hourly.assign(_p=hourly["source"].map(pref), _d=~((hourly["source"] == "nilm") & (hourly["model_version"] == dep)))
    h = h.sort_values(["appliance_id", "bucket_us", "_p", "_d", "model_version"], ascending=[True, True, True, True, False]).drop(columns="_d")
    return h.drop_duplicates(["appliance_id", "bucket_us"], keep="first").drop(columns="_p")


def run(client, household_id: str, location_id: str, now: datetime, tz: str, history_days: int = 35, use_lgbm: bool = True) -> ForecastRun:
    now = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now).tz_localize("UTC")
    start = now - timedelta(days=history_days)
    hourly = preferred_hourly(read_hourly(client, household_id, start, now))
    if hourly.empty:
        raise RuntimeError(f"no hourly rollups for {household_id} in the last {history_days} days")
    history = hourly.rename(columns={"bucket": "ts"})[["appliance_id", "ts", "kwh"]]
    wx_hist = read_weather(client, location_id, start, now, is_forecast=False)
    wx_fc = read_weather(client, location_id, now, now + timedelta(hours=HORIZON_H), is_forecast=True)
    age = forecast_age(wx_fc, now)
    if age is None or age > MAX_FORECAST_AGE:
        raise RuntimeError(f"TRS-03-04: weather forecast missing or older than 24 h (age={age})")
    temp_hist = wx_hist.set_index("ts")["temp_c"]
    temp_fc = wx_fc.set_index("ts")["temp_c"]
    days = history.groupby("appliance_id")["ts"].nunique().max() / 24.0
    if days < MIN_HISTORY_DAYS:
        log.warning("only %.1f days of history (< %d): seasonal-naive for every appliance", days, MIN_HISTORY_DAYS)
    run_ = forecast_household(history, temp_hist, temp_fc, now.to_pydatetime(), tz, use_lgbm=use_lgbm)
    write(client, household_id, run_)
    return run_


def write(client, household_id: str, run_: ForecastRun) -> int:
    f = run_.frame()
    ts_us = us_array(f["ts"])
    rows = [
        {"household_id": household_id, "appliance_id": a, "ts_us": int(t), "kwh_p_50": float(p50), "kwh_p_90": float(p90), "model_version": mv}
        for a, t, p50, p90, mv in zip(f["appliance_id"], ts_us, f["kwh_p50"], f["kwh_p90"], f["model_version"], strict=True)
    ]
    made = us(run_.made_at)
    for i in range(0, len(rows), 2000):
        client.call("write_forecasts", rows[i : i + 2000], made)
    metrics = [
        {"model_version": m["model_version"], "component": "cmp11_forecaster", "appliance_type": m["appliance_id"],
         "metric": m["metric"], "value": float(m["value"]) if m["value"] == m["value"] else -1.0, "synthetic": True,
         "eval_sessions": f"time-ordered 80/20 to {run_.made_at.isoformat()}"}
        for m in run_.metrics()
    ]
    if metrics:
        client.call("write_model_metrics", metrics)
    return len(rows)


def read_latest_forecast(client, household_id: str) -> tuple[pd.DataFrame, datetime | None]:
    """Latest made_at batch: columns appliance_id, ts, kwh_p50, kwh_p90, model_version."""
    from homewatt.spacetime import from_us

    df = client.sql(f"SELECT * FROM forecast WHERE household_id = '{household_id}'")
    if df.empty:
        return df, None
    made = int(df["made_at_us"].max())
    df = df[df["made_at_us"] == made].sort_values(["appliance_id", "ts_us"])
    out = pd.DataFrame({"appliance_id": df["appliance_id"], "ts": from_us(df["ts_us"]), "kwh_p50": df["kwh_p_50"].astype(float),
                        "kwh_p90": df["kwh_p_90"].astype(float), "model_version": df["model_version"]}).reset_index(drop=True)
    return out, from_us(made).to_pydatetime()
