import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from homewatt.cmp06_synth.fault import Fault
from homewatt.cmp06_synth.generator import SAMPLES_PER_DAY, generate
from homewatt.cmp12_anomaly.detector import (
    MIN_BASELINE_DAYS,
    alert_text,
    decide,
    features,
    robust_z,
    severity,
)

START = datetime(2025, 7, 1)


def test_trs_12_01_z_is_median_mad_with_1_4826():
    z, med, mad = robust_z(14.0, [10, 10, 11, 9, 10, 12, 8])
    assert med == 10 and mad == 1 and z == pytest.approx(4 / 1.4826)


def test_cmp12_error_handling_mad_zero_uses_one_percent_of_median():
    z, med, mad = robust_z(58.0 * 1.4, [58.0] * 12)
    assert mad == 0 and z == pytest.approx((81.2 - 58.0) / 0.58)


def test_trs_12_02_features_duty_cycles_mean_on():
    w = pd.Series([0, 60, 60, 0, 0, 60, 0, 0])
    f = features(pd.Series(range(8)), w, pd.Series([60.0] * 8))
    assert f.duty_cycle == pytest.approx(3 / 8) and f.cycles_per_day == 2 and f.mean_on_watts == 60


def test_trs_12_03_single_day_excursion_does_not_alert_two_days_do():
    assert decide(6.0, 0.5, False) is None
    assert decide(6.0, float("nan"), False) is None
    assert decide(6.0, 4.0, False) == "alert"
    assert decide(1.0, 6.0, True) == "close"


def test_trs_12_05_06_text_states_feature_and_magnitude_without_cause_and_severity_bands():
    t = alert_text("fridge", "mean_on_watts", 80.0, 58.0)
    assert t == "fridge is drawing 38% more power than usual"
    assert not any(w in t for w in ("seal", "coil", "broken", "because"))
    assert severity(4.0) == "watch" and severity(5.1) == "act" and severity(-6) == "act"


def _daily_fridge_features(tl) -> list:
    tr = tl.truth[["ts", "fridge_w"]].set_index("ts")["fridge_w"].resample("60s").mean()
    out = []
    for d in range(len(tr) // 1440):
        day = tr.iloc[d * 1440 : (d + 1) * 1440]
        out.append(features(pd.Series(day.index), day, pd.Series(np.full(len(day), 60.0))))
    return out


def _alert_days(feats) -> list[int]:
    alerts, z_prev, flagged = [], {}, set()
    for i, f in enumerate(feats):
        base = [b for j, b in enumerate(feats[:i]) if j not in flagged][-14:]
        if len(base) < MIN_BASELINE_DAYS:
            continue
        for k in ("duty_cycle", "mean_on_watts"):
            z, _, _ = robust_z(getattr(f, k), [getattr(b, k) for b in base])
            if decide(z, z_prev.get(k, math.nan), False) == "alert":
                alerts.append(i)
            if abs(z) > 3:
                flagged.add(i)
            z_prev[k] = z
    return sorted(set(alerts))


def test_trs_12_verification_fridge_fault_day_12_alerts_on_day_13_and_not_before(fake_library, hot_weather, small_profile):
    fault = Fault(appliance_id="fridge", start_day=12, kind="power", magnitude=0.4)
    tl = generate(small_profile, fake_library, hot_weather, START, days=15, seed=3, fault=fault)
    days = _alert_days(_daily_fridge_features(tl))
    assert days and days[0] == 13 and min(days) >= 12


def test_trs_12_verification_no_fault_no_alerts_over_14_days(fake_library, hot_weather, small_profile):
    tl = generate(small_profile, fake_library, hot_weather, START, days=15, seed=3)
    assert _alert_days(_daily_fridge_features(tl)) == []
    assert SAMPLES_PER_DAY == 43200


def test_trs_12_persistent_fault_stays_alerted_and_flagged_days_leave_the_baseline(fake_library, hot_weather, small_profile):
    fault = Fault(appliance_id="fridge", start_day=12, kind="power", magnitude=0.4)
    tl = generate(small_profile, fake_library, hot_weather, START, days=21, seed=3, fault=fault)
    days = _alert_days(_daily_fridge_features(tl))
    assert days == list(range(13, 21))  # every faulty day after the first keeps alerting


def test_baseline_rows_skips_scored_anomalous_days():
    from homewatt.cmp12_anomaly.detector import baseline_rows

    hist = pd.DataFrame({
        "day": [f"2025-07-{d:02d}" for d in range(1, 17)],
        "baseline_days": [0] * 10 + [10] * 6,
        "z_duty_cycle": [0.0] * 16,
        "z_mean_on_watts": [0.0] * 12 + [40.0, 41.0, 0.5, 0.2],
    })
    b = baseline_rows(hist, "2025-07-17")
    assert "2025-07-13" not in set(b["day"]) and "2025-07-14" not in set(b["day"]) and len(b) == 14
