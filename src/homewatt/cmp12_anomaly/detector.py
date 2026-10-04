"""Daily features, robust z-scores, two-consecutive-day alerting.

TRS-14-02: the appliance type selects the anomaly features. V1 monitors the fridge, the one
appliance in the demo with a steady daily pattern. Event loads (hair dryer, iron) have no stable
daily baseline and HVAC follows the weather, so they get no features in V1.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from homewatt.schema import ON_THRESHOLD_W

log = logging.getLogger(__name__)

FEATURES_BY_TYPE: dict[str, tuple[str, ...]] = {"fridge": ("duty_cycle", "mean_on_watts", "cycles_per_day")}
ALERT_FEATURES = ("duty_cycle", "mean_on_watts")  # TRS-12-03
Z_ALERT = 3.0
Z_ACT = 5.0  # TRS-12-06
BASELINE_DAYS = 14
MIN_BASELINE_DAYS = 10  # TRS-12-04
MAD_K = 1.4826
# v0.12: the one reader that keeps the simulated feed first. co-v2.1 reports fixed on-levels, so it
# cannot see a fridge drawing more; the detector reads the sim feed until a splitter outputs real watts.
SOURCE_PREFERENCE = ("plug", "sim", "nilm")


@dataclass
class DayFeatures:
    duty_cycle: float
    cycles_per_day: float
    mean_on_watts: float
    covered_s: float


def features(ts: pd.Series, w: pd.Series, dt_s: pd.Series) -> DayFeatures:
    """From one day of one appliance's rows (time ordered)."""
    w = np.asarray(w, dtype=float)
    dt = np.asarray(dt_s, dtype=float)
    on = w > ON_THRESHOLD_W
    covered = float(dt.sum())
    on_s = float(dt[on].sum())
    starts = int(np.sum(on[1:] & ~on[:-1]) + (1 if len(on) and on[0] else 0))
    mean_on = float(w[on].mean()) if on.any() else 0.0
    return DayFeatures(on_s / covered if covered else 0.0, float(starts), mean_on, covered)


def robust_z(today: float, baseline: list[float]) -> tuple[float, float, float]:
    """TRS-12-01: z = (today - median) / (1.4826 · MAD); MAD = 0 -> 0.01 · median as the scale."""
    b = np.asarray(baseline, dtype=float)
    med = float(np.median(b))
    mad = float(np.median(np.abs(b - med)))
    scale = MAD_K * mad
    if scale == 0:
        scale = 0.01 * abs(med)
        log.info("MAD = 0; using 0.01 x median = %.4f as the scale (CMP-12 error handling)", scale)
    if scale == 0:
        return 0.0, med, mad
    return (today - med) / scale, med, mad


def baseline_rows(hist: pd.DataFrame, day_s: str) -> pd.DataFrame:
    """The appliance's own normal: the latest 14 earlier days, skipping days that were themselves
    scored anomalous (|z| > 3 on an alerting feature). Without the skip, a fault that persists for
    a week becomes the new median and the alert closes while the fault is still there."""
    if hist.empty:
        return hist
    prior = hist[hist["day"] < day_s]
    scored = prior["baseline_days"] >= MIN_BASELINE_DAYS
    flagged = scored & ((prior["z_duty_cycle"].abs() > Z_ALERT) | (prior["z_mean_on_watts"].abs() > Z_ALERT))
    return prior[~flagged].tail(BASELINE_DAYS)


def decide(z_today: float, z_prev: float, is_open: bool) -> str | None:
    """TRS-12-03: alert only when |z| > 3 on two consecutive days; close an open alert once the
    feature is back within |z| <= 3. Returns 'alert', 'close', or None."""
    if abs(z_today) > Z_ALERT and not math.isnan(z_prev) and abs(z_prev) > Z_ALERT:
        return "alert"
    if is_open and abs(z_today) <= Z_ALERT:
        return "close"
    return None


def severity(z: float) -> str:
    return "act" if abs(z) > Z_ACT else "watch"


def alert_text(label: str, feature: str, today: float, median: float) -> str:
    """TRS-12-05: feature and magnitude in plain terms, no cause."""
    change = (today / median - 1.0) * 100 if median else 0.0
    pct = f"{abs(change):.0f}%"
    if feature == "mean_on_watts":
        return f"{label} is drawing {pct} {'more' if change >= 0 else 'less'} power than usual"
    return f"{label} is running {pct} {'longer' if change >= 0 else 'shorter'} than usual"


def _local_day_bounds(d: date, tz: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(datetime(d.year, d.month, d.day), tz=tz)
    return start.tz_convert("UTC"), (start + pd.Timedelta(days=1)).tz_convert("UTC")


def read_day_rows(client, household_id: str, appliance_id: str, d: date, tz: str) -> pd.DataFrame:
    from homewatt.spacetime import from_us, us

    a, b = _local_day_bounds(d, tz)
    df = client.sql(
        f"SELECT ts_us, watts, dt_s, source, model_version FROM appliance_power WHERE household_id = '{household_id}' "
        f"AND appliance_id = '{appliance_id}' AND ts_us >= {us(a)} AND ts_us < {us(b)}"
    )
    if df.empty:
        return df
    for src in SOURCE_PREFERENCE:
        sub = df[df["source"] == src]
        if len(sub):
            latest = sorted(sub["model_version"].unique())[-1]
            sub = sub[sub["model_version"] == latest].sort_values("ts_us")
            sub = sub.assign(ts=from_us(sub["ts_us"]))
            return sub.reset_index(drop=True)
    return df.iloc[0:0]


def read_feature_history(client, household_id: str, appliance_id: str) -> pd.DataFrame:
    df = client.sql(f"SELECT * FROM appliance_day_feature WHERE household_id = '{household_id}' AND appliance_id = '{appliance_id}'")
    return df.sort_values("day").reset_index(drop=True) if len(df) else df


def run_day(client, household_id: str, d: date, tz: str) -> list[dict]:
    """Compute day d's features for every monitored appliance, score against the previous 14
    days, and raise, update or close alerts. Returns the alert decisions made."""
    from homewatt.spacetime import us

    apps = client.sql(f"SELECT appliance_id, type, label FROM appliance WHERE household_id = '{household_id}'")
    decisions: list[dict] = []
    day_s = d.isoformat()
    for app in apps.itertuples():
        feats = FEATURES_BY_TYPE.get(app.type)
        if not feats:
            continue
        rows = read_day_rows(client, household_id, app.appliance_id, d, tz)
        if rows.empty:
            continue
        f = features(rows["ts"], rows["watts"], rows["dt_s"])
        hist = read_feature_history(client, household_id, app.appliance_id)
        prior = baseline_rows(hist, day_s)
        n_base = len(prior)
        z = {k: float("nan") for k in ("duty_cycle", "mean_on_watts", "cycles_per_day")}
        stats: dict[str, tuple[float, float]] = {}
        if n_base >= MIN_BASELINE_DAYS:
            for k in feats:
                col = {"duty_cycle": "duty_cycle", "mean_on_watts": "mean_on_watts", "cycles_per_day": "cycles_per_day"}[k]
                zz, med, mad = robust_z(getattr(f, k), list(prior[col]))
                z[k] = zz
                stats[k] = (med, mad)
        source = str(rows["source"].iloc[0])
        client.call("write_day_features", [{
            "household_id": household_id, "appliance_id": app.appliance_id, "day": day_s, "source": source,
            "duty_cycle": f.duty_cycle, "cycles_per_day": f.cycles_per_day, "mean_on_watts": f.mean_on_watts,
            # A z-score only counts when baseline_days >= 10 (TRS-12-04); otherwise 0 is stored.
            "covered_s": f.covered_s, "z_duty_cycle": _finite(z["duty_cycle"]), "z_mean_on_watts": _finite(z["mean_on_watts"]),
            "z_cycles_per_day": _finite(z["cycles_per_day"]), "baseline_days": n_base,
        }])
        if n_base < MIN_BASELINE_DAYS:
            decisions.append({"appliance_id": app.appliance_id, "day": day_s, "decision": "insufficient history", "baseline_days": n_base})
            continue
        prev = hist[hist["day"] < day_s].tail(1)
        open_alerts = client.sql(
            f"SELECT id, feature FROM alert WHERE household_id = '{household_id}' AND appliance_id = '{app.appliance_id}' AND closed_at_us = 0"
        )
        _, day_end = _local_day_bounds(d, tz)
        for k in ALERT_FEATURES:
            if k not in feats:
                continue
            zt = z[k]
            scored = len(prev) and int(prev["baseline_days"].iloc[0]) >= MIN_BASELINE_DAYS
            zp = float(prev[f"z_{k}"].iloc[0]) if scored else float("nan")
            is_open = bool(len(open_alerts) and (open_alerts["feature"] == k).any())
            verdict = decide(zt, zp, is_open)
            if verdict == "alert":
                med, mad = stats[k]
                client.call("upsert_alert", household_id, app.appliance_id, k, us(day_end), getattr(f, k), med, mad, zt,
                            severity(zt), alert_text(app.label, k, getattr(f, k), med))
                decisions.append({"appliance_id": app.appliance_id, "day": day_s, "feature": k, "decision": "alert", "z": zt})
            elif verdict == "close":
                for r in open_alerts[open_alerts["feature"] == k].itertuples():
                    client.call("close_alert", int(r.id))
                decisions.append({"appliance_id": app.appliance_id, "day": day_s, "feature": k, "decision": "closed", "z": zt})
    return decisions


def _finite(x: float) -> float:
    return 0.0 if (x is None or math.isnan(x) or math.isinf(x)) else float(x)


def days_between(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out
