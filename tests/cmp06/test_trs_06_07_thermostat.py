from datetime import datetime

import numpy as np

from homewatt.cmp06_synth import thermostat as th
from homewatt.cmp06_synth.generator import generate
from homewatt.cmp06_synth.profile import ThermostatParams
from homewatt.schema import HARMONICS

START = datetime(2025, 7, 1, 0, 0)


def test_trs_06_07_track_is_zero_below_15c_outdoor():
    r = th.simulate(np.full(600, 10.0), ThermostatParams())
    assert r.p_w.max() == 0.0


def test_trs_06_07_compressor_cycles_with_hysteresis_on_a_hot_day():
    p = ThermostatParams()
    # At 32 °C outdoor the TRS defaults (tau 4 h, 1.5 °C/h) cannot reach 24 °C, so the compressor
    # stays on; 28 °C is a day on which it cycles. Equilibrium while on = outdoor - 6 °C.
    r = th.simulate(np.full(24 * 60, 28.0), p, indoor0_c=28.0)
    assert set(np.unique(r.p_w)) == {0.0, 3000.0}
    # after settling, indoor stays within setpoint ± hysteresis (plus one step of overshoot)
    settled = r.indoor_c[6 * 60 :]
    assert settled.min() > p.setpoint_c - p.hysteresis_c - 0.1
    assert settled.max() < p.setpoint_c + p.hysteresis_c + 0.1
    transitions = np.diff(r.on.astype(int)) != 0
    assert transitions.sum() > 4  # it cycles, it does not sit on


def test_trs_06_07_higher_setpoint_means_less_runtime():
    base = th.simulate(np.full(24 * 60, 28.0), ThermostatParams(setpoint_c=24.0), indoor0_c=28.0)
    warm = th.simulate(np.full(24 * 60, 28.0), ThermostatParams(setpoint_c=26.0), indoor0_c=28.0)
    assert warm.on.mean() < base.on.mean()


def test_trs_06_07_setpoint_override_array_applies_from_an_index_forward():
    sp = np.full(24 * 60, 24.0)
    sp[12 * 60 :] = 27.0
    r = th.simulate(np.full(24 * 60, 28.0), ThermostatParams(), setpoint_c=sp, indoor0_c=28.0)
    assert r.on[2 * 60 : 12 * 60].mean() > r.on[14 * 60 :].mean()


def test_trs_06_08_hvac_harmonics_are_a_fixed_vector_scaled_by_power_and_marked_synthetic(
    fake_library, hot_weather, small_profile
):
    tl = generate(small_profile, fake_library, hot_weather, START, days=1, seed=4)
    assert tl.meta["appliances"]["hvac"]["synthetic"] is True
    assert "synthetic HVAC" in tl.meta["appliances"]["hvac"]["note"]
    on = tl.truth["hvac_w"] > 0
    assert on.any() and (~on).any()
    prof = th.default_harmonic_profile(small_profile.vrms_v, small_profile.thermostat.power_factor)
    # Within hvac-only samples (other tracks zero) aggregate harmonics follow the fixed profile.
    hvac_only = on & (tl.truth[["water_heater_w", "hair_dryer_w"]].sum(axis=1) == 0)
    if hvac_only.any():
        row = tl.aggregate.loc[hvac_only, list(HARMONICS)].iloc[0].to_numpy()
        fridge = tl.truth.loc[hvac_only, "fridge_w"].iloc[0]
        contrib = row - (row[0] - 3000 * prof[0]) * np.array([1 / (k + 1) ** 1.5 for k in range(32)]) * (fridge > 0)
        assert np.corrcoef(contrib, 3000 * prof)[0, 1] > 0.99


def test_trs_06_09_thermostat_parameters_come_from_the_profile_yaml(tmp_path):
    from homewatt.cmp06_synth.profile import Profile

    (tmp_path / "p.yaml").write_text(
        "household_id: x\nappliances: {}\nthermostat: {p_hvac_w: 4500, setpoint_c: 22, tau_h: 2}\n"
    )
    p = Profile.load(tmp_path / "p.yaml")
    assert (p.thermostat.p_hvac_w, p.thermostat.setpoint_c, p.thermostat.tau_h) == (4500, 22, 2)
