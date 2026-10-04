from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from homewatt.cmp04_tariff.model import flat_tariff, load_tariff
from homewatt.cmp06_synth.profile import ThermostatParams
from homewatt.cmp13_simulator.atl import load_atl
from homewatt.cmp13_simulator.costing import cost
from homewatt.cmp13_simulator.simulator import (
    ApplianceInfo,
    Household,
    price_all,
    rank,
    suppressed_action_types,
)
from tests.conftest import REPO

DTE = load_tariff(REPO / "config" / "tariffs" / "dte_d1_11.yaml")
ATL = load_atl()
MADE_AT = datetime(2025, 7, 14, 0, 0, tzinfo=pd.Timestamp("2025-07-14", tz="UTC").tzinfo)


def horizon():
    """168 hourly UTC timestamps starting Monday 2025-07-14 00:00 local (Detroit)."""
    return pd.date_range("2025-07-14T00:00", periods=168, freq="h", tz="America/Detroit").tz_convert("UTC")


def forecast_for(appliance_id: str, kwh_by_local_hour) -> pd.DataFrame:
    idx = horizon()
    local_hour = idx.tz_convert("America/Detroit").hour
    is_weekday = idx.tz_convert("America/Detroit").weekday < 5
    kwh = np.array([kwh_by_local_hour(h, wd) for h, wd in zip(local_hour, is_weekday, strict=True)], dtype=float)
    return pd.DataFrame({"appliance_id": appliance_id, "ts": idx, "kwh_p50": kwh})


def hh(apps, **kw):
    return Household("hh", apps, week_id="2025-W29", **kw)


def test_trs_13_verification_shift_saving_equals_kwh_times_rate_gap():
    """Water heater use concentrated at 17:00 on weekdays; shift to 21:00 saves kWh x (peak - off_peak)."""
    fc = forecast_for("wh", lambda h, wd: 2.0 if (h == 17 and wd) else 0.0)
    acts = price_all(ATL, hh([ApplianceInfo("wh", "water_heater", "water heater")]), fc, DTE, MADE_AT)
    shift = next(a for a in acts if a.action_type == "shift_out_of_peak")
    expected = 5 * 2.0 * (0.24133 - 0.18435)
    assert shift.saving_usd == pytest.approx(expected, rel=1e-6)
    assert shift.params["to_hour"] == 19  # first value of the search range; all off-peak hours price equally
    assert shift.counterfactual.kwh == pytest.approx(shift.baseline.kwh)  # energy-preserving
    assert shift.surfaced and "19:00 or later" in shift.assumption_text


def test_trs_13_05_flat_tariff_prices_shift_at_zero_and_does_not_surface():
    fc = forecast_for("wh", lambda h, wd: 2.0 if (h == 17 and wd) else 0.0)
    acts = price_all(ATL, hh([ApplianceInfo("wh", "water_heater", "water heater")]), fc, flat_tariff(0.17), MADE_AT)
    shift = next(a for a in acts if a.action_type == "shift_out_of_peak")
    assert shift.saving_usd == 0.0 and not shift.surfaced and shift.not_surfaced_reason == "flat_tariff"
    trim_ = next(a for a in acts if a.action_type == "water_heater_setpoint")
    assert trim_.saving_usd > 0  # trim actions remain


def test_trs_13_02_baseline_equals_the_costing_function():
    fc = forecast_for("wh", lambda h, wd: 0.5)
    acts = price_all(ATL, hh([ApplianceInfo("wh", "water_heater", "water heater")]), fc, DTE, MADE_AT)
    base = cost(fc.set_index("ts")["kwh_p50"], DTE)
    for a in acts:
        assert a.baseline.usd == pytest.approx(base.usd)
        assert a.saving_usd == pytest.approx(a.baseline.usd - a.counterfactual.usd, abs=1e-9)


def test_trs_13_04_below_one_dollar_per_month_is_computed_but_not_surfaced():
    fc = forecast_for("wh", lambda h, wd: 0.05 if (h == 17 and wd) else 0.0)  # tiny peak use
    acts = price_all(ATL, hh([ApplianceInfo("wh", "water_heater", "water heater")]), fc, DTE, MADE_AT)
    shift = next(a for a in acts if a.action_type == "shift_out_of_peak")
    assert shift.saving_usd > 0 and shift.saving_usd_month < 1.0
    assert not shift.surfaced and shift.not_surfaced_reason == "below_floor"


def test_trs_13_06_and_09_rank_by_saving_times_half_plus_score_keep_three():
    apps = [ApplianceInfo("wh", "water_heater", "water heater"), ApplianceInfo("hd", "hair_dryer", "hair dryer"),
            ApplianceInfo("lap", "laptop", "laptop"), ApplianceInfo("tv", "screen", "TV")]
    fc = pd.concat([
        forecast_for("wh", lambda h, wd: 2.0 if (h == 17 and wd) else 0.2),
        forecast_for("hd", lambda h, wd: 1.0 if (h == 16 and wd) else 0.0),
        forecast_for("lap", lambda h, wd: 0.3),
        forecast_for("tv", lambda h, wd: 0.3),
    ])
    scores = {"shift_out_of_peak": 0.0, "water_heater_setpoint": 1.0, "trim_standby": None}
    acts = price_all(ATL, hh(apps, first_week=False, success_scores=scores), fc, DTE, MADE_AT)
    top = rank(acts)
    assert len(top) == 3
    for a in acts:
        if a.success_score is None:
            assert a.rank_score == pytest.approx(a.saving_usd)
        else:
            assert a.rank_score == pytest.approx(a.saving_usd * (0.5 + a.success_score))
    assert top == sorted(top, key=lambda a: -a.rank_score)


def test_trs_13_13_cold_start_ranks_by_saving_alone():
    apps = [ApplianceInfo("wh", "water_heater", "water heater")]
    fc = forecast_for("wh", lambda h, wd: 2.0 if (h == 17 and wd) else 0.2)
    acts = price_all(ATL, hh(apps, first_week=True, success_scores={"shift_out_of_peak": 0.0}), fc, DTE, MADE_AT)
    for a in acts:
        assert a.rank_score == pytest.approx(a.saving_usd)


def test_trs_13_12_search_keeps_the_best_value_and_records_it():
    weather = pd.Series(np.full(168, 30.0), index=horizon())
    apps = [ApplianceInfo("hvac", "hvac", "air conditioner")]
    fc = forecast_for("hvac", lambda h, wd: 1.5)
    h = hh(apps, thermostat=ThermostatParams(), current_setpoint_c=24.0, device_bounds=(18.0, 27.0))
    acts = price_all(ATL, h, fc, DTE, MADE_AT, weather=weather)
    sp = next(a for a in acts if a.action_type == "hvac_setpoint_away")
    assert sp.params["delta_c"] == 3  # largest delta saves most
    assert sp.params["target_setpoint_c"] == 27.0 and 0 < sp.params["setpoint_factor"] < 1
    assert sp.actuator == "thermostat" and "3 °C warmer" in sp.assumption_text


def test_annex_a3_setpoint_outside_device_bounds_is_not_evaluated():
    weather = pd.Series(np.full(168, 30.0), index=horizon())
    apps = [ApplianceInfo("hvac", "hvac", "air conditioner")]
    fc = forecast_for("hvac", lambda h, wd: 1.5)
    h = hh(apps, thermostat=ThermostatParams(), current_setpoint_c=26.0, device_bounds=(18.0, 27.0))
    acts = price_all(ATL, h, fc, DTE, MADE_AT, weather=weather)
    sp = next(a for a in acts if a.action_type == "hvac_setpoint_away")
    assert sp.params["delta_c"] == 1  # 2 and 3 would leave the 27 °C bound


def test_annex_a3_shift_never_moves_energy_into_peak_and_precool_targets_two_hours_before():
    fc = forecast_for("hvac", lambda h, wd: 2.0 if (15 <= h < 19 and wd) else 0.5)
    apps = [ApplianceInfo("hvac", "hvac", "air conditioner")]
    acts = price_all(ATL, hh(apps, thermostat=ThermostatParams(), current_setpoint_c=24.0), fc, DTE, MADE_AT,
                     weather=pd.Series(np.full(168, 30.0), index=horizon()))
    pre = next(a for a in acts if a.action_type == "hvac_precool")
    assert pre.params["peak_start"] == 15 and pre.params["peak_end"] == 19
    assert pre.saving_usd == pytest.approx(5 * 4 * 2.0 * (0.24133 - 0.18435), rel=1e-6)
    assert "before 15:00" in pre.assumption_text


def test_trs_13_01_maintenance_only_while_alert_open():
    apps = [ApplianceInfo("fridge", "fridge", "fridge")]
    fc = forecast_for("fridge", lambda h, wd: 0.08)
    none = price_all(ATL, hh(apps), fc, DTE, MADE_AT)
    assert not any(a.action_type == "fridge_service" for a in none)
    some = price_all(ATL, hh(apps, open_alert_appliances={"fridge"}), fc, DTE, MADE_AT)
    assert any(a.action_type == "fridge_service" for a in some)


def test_cmp13_template_for_absent_appliance_is_skipped_silently():
    apps = [ApplianceInfo("lap", "laptop", "laptop")]
    fc = forecast_for("lap", lambda h, wd: 0.3)
    acts = price_all(ATL, hh(apps), fc, DTE, MADE_AT)
    assert {a.action_type for a in acts} == {"trim_standby"}


def test_trs_13_10_three_consecutive_dismissals_suppress_for_four_weeks():
    sup = suppressed_action_types({"trim_standby": ["2025-W26", "2025-W27", "2025-W28"], "shift_out_of_peak": ["2025-W27"]}, "2025-W29")
    assert sup == {"trim_standby": ("2025-W29", "2025-W32")}


def test_trs_13_07_simulator_imports_no_learned_component():
    import inspect

    from homewatt.cmp13_simulator import atl, costing, shapes, simulator

    for m in (atl, costing, shapes, simulator):
        src = inspect.getsource(m)
        assert "lightgbm" not in src and "torch" not in src and "sklearn" not in src


def test_annex_a_atl_has_exactly_the_six_v1_templates():
    assert [t.action_type for t in ATL.active] == [
        "shift_out_of_peak", "hvac_setpoint_away", "hvac_precool", "water_heater_setpoint", "trim_standby", "fridge_service",
    ]
    for t in ATL.active:
        assert t.shape in ("shift", "trim", "setpoint", "maintenance")
