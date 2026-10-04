import pandas as pd
import pytest

from homewatt.cmp04_tariff.model import load_tariff
from homewatt.cmp18_verifier.verifier import scores, verify_one
from homewatt.spacetime import us
from tests.conftest import REPO

DTE = load_tariff(REPO / "config" / "tariffs" / "dte_d1_11.yaml")
MADE = pd.Timestamp("2025-07-14T04:00:00Z")
HOURS = pd.date_range(MADE, periods=168, freq="h", tz="UTC")
LOCAL = HOURS.tz_convert("America/Detroit")


def action(saving_usd: float, accepted=MADE):
    return pd.Series({"action_id": "a1", "appliance_id": "wh", "action_type": "shift_out_of_peak", "saving_usd": saving_usd,
                      "status_at_us": us(accepted), "forecast_made_at_us": us(MADE)})


def peak_series(kwh_in_peak: float, kwh_shifted: float = 0.0):
    peak = (LOCAL.hour == 17) & (LOCAL.weekday < 5)
    late = (LOCAL.hour == 21) & (LOCAL.weekday < 5)
    return pd.Series(peak * kwh_in_peak + late * kwh_shifted, index=HOURS, dtype=float)


def test_trs_18_verification_shifted_week_is_verified_unshifted_is_not():
    baseline = peak_series(2.0)
    expected = 5 * 2.0 * (0.24133 - 0.18435)
    fc = pd.DataFrame({"ts": HOURS, "kwh_p50": baseline.to_numpy()})
    v = verify_one(action(expected), fc, peak_series(0.0, 2.0), DTE)
    assert v.status == "verified" and v.verified_saving_usd == pytest.approx(expected)
    v2 = verify_one(action(expected), fc, baseline, DTE)
    assert v2.status == "not_verified" and v2.verified_saving_usd == pytest.approx(0.0)


def test_trs_18_02_threshold_is_half_the_expected_saving():
    fc = pd.DataFrame({"ts": HOURS, "kwh_p50": peak_series(2.0).to_numpy()})
    expected = 5 * 2.0 * (0.24133 - 0.18435)
    half = verify_one(action(expected), fc, peak_series(0.9, 1.1), DTE)  # a little over half the energy moved
    assert half.status == "verified"
    under = verify_one(action(expected), fc, peak_series(1.2, 0.8), DTE)
    assert under.status == "not_verified"


def test_trs_18_03_window_is_clipped_to_the_pricing_forecast_and_expected_scaled():
    fc = pd.DataFrame({"ts": HOURS, "kwh_p50": peak_series(2.0).to_numpy()})
    v = verify_one(action(7.0, MADE + pd.Timedelta(hours=84)), fc, peak_series(0.0, 2.0), DTE)
    assert v.window_hours == 84 and v.expected_usd == pytest.approx(3.5)


def test_trs_18_05_score_formula_and_null_below_two_proposals():
    ledger = pd.DataFrame({
        "action_type": ["a", "a", "a", "a", "b"],
        "status": ["verified", "accepted", "dismissed", "not_verified", "verified"],
        "week_id": ["2025-W27", "2025-W28", "2025-W28", "2025-W29", "2025-W29"],
    })
    rows = {r["action_type"]: r for r in scores(ledger, "2025-W30")}
    assert rows["a"]["success_score"] == pytest.approx((1 + 0.5 * 1) / 4)
    assert rows["b"]["success_score"] == -1.0  # null: fewer than 2 proposals


def test_trs_18_07_scores_only_use_the_trailing_8_weeks():
    ledger = pd.DataFrame({"action_type": ["a"] * 3, "status": ["verified"] * 3, "week_id": ["2025-W10", "2025-W28", "2025-W29"]})
    assert scores(ledger, "2025-W30")[0]["proposed"] == 2
