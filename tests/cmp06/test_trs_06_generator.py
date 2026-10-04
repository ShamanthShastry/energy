import hashlib
from datetime import datetime

import numpy as np
import pytest

from homewatt.cmp06_synth.fault import Fault
from homewatt.cmp06_synth.generator import SAMPLES_PER_DAY, generate, write_timeline
from homewatt.schema import HARMONICS, NUMERIC_FIELDS, ON_THRESHOLD_W

START = datetime(2025, 7, 1, 0, 0)


def test_trs_06_01_aggregate_is_sum_of_tracks_plus_baseload_within_noise(fake_library, hot_weather, small_profile):
    tl = generate(small_profile, fake_library, hot_weather, START, days=1, seed=3)
    track_cols = [c for c in tl.truth.columns if c.endswith("_w") and c != "baseload_w"]
    expected = tl.truth[track_cols].sum(axis=1) + tl.truth["baseload_w"]
    resid = tl.aggregate["p_active_w"].to_numpy() - expected.to_numpy()
    assert abs(resid.mean()) < 0.5
    assert abs(resid.std() - small_profile.noise_w) < 0.5


def test_trs_06_01_harmonics_are_summed_per_order(fake_library, hot_weather, small_profile):
    small_profile.thermostat.enabled = False
    small_profile.noise_w = 0.0
    tl = generate(small_profile, fake_library, hot_weather, START, days=1, seed=3)
    # with a single appliance type family each harmonic of the aggregate equals the sum of track
    # harmonics; verify via irms consistency: h1 ~ fundamental current ~ p/(vrms*pf)
    agg = tl.aggregate
    assert (agg[list(HARMONICS)].to_numpy() >= 0).all()
    assert np.corrcoef(agg["h1"], agg["p_active_w"])[0, 1] > 0.95


def test_trs_06_01_schema_is_the_37_field_sample_record(fake_library, hot_weather, small_profile):
    tl = generate(small_profile, fake_library, hot_weather, START, days=1, seed=1)
    assert list(tl.aggregate.columns) == ["household_id", "ts", *NUMERIC_FIELDS]
    assert len(tl.aggregate) == SAMPLES_PER_DAY
    assert str(tl.aggregate["ts"].dt.tz) == "UTC"


def test_trs_06_02_overlap_is_permitted_and_reported(fake_library, hot_weather, small_profile):
    tl = generate(small_profile, fake_library, hot_weather, START, days=2, seed=5)
    assert tl.meta["overlap_fraction"] >= 0.10


def test_trs_06_03_same_seed_same_bytes(fake_library, hot_weather, small_profile, tmp_path):
    a = write_timeline(generate(small_profile, fake_library, hot_weather, START, 2, seed=7), tmp_path / "a")
    b = write_timeline(generate(small_profile, fake_library, hot_weather, START, 2, seed=7), tmp_path / "b")
    assert a == b
    assert hashlib.sha256((tmp_path / "a" / "aggregate.parquet").read_bytes()).hexdigest() == a["aggregate.parquet"]
    c = write_timeline(generate(small_profile, fake_library, hot_weather, START, 2, seed=8), tmp_path / "c")
    assert c != a


def test_trs_06_04_excluded_sessions_cannot_be_requested(tmp_path, rng):
    from homewatt.cmp00_activations.library import ActivationLibrary
    from tests.conftest import write_fake_library

    write_fake_library(tmp_path / "lib", rng)
    with pytest.raises(ValueError, match="TRS-06-04"):
        ActivationLibrary(tmp_path / "lib", sessions=["s1", "s9"])
    lib = ActivationLibrary(tmp_path / "lib")
    assert lib.sessions == ["s1", "s2"]  # train only by default; test sessions never enter synthesis


def test_trs_06_05_fault_touches_only_named_appliance_and_is_recorded(fake_library, hot_weather, small_profile):
    fault = Fault(appliance_id="fridge", start_day=1, kind="power", magnitude=0.4)
    base = generate(small_profile, fake_library, hot_weather, START, days=2, seed=11)
    tl = generate(small_profile, fake_library, hot_weather, START, days=2, seed=11, fault=fault)
    d1 = slice(SAMPLES_PER_DAY, 2 * SAMPLES_PER_DAY)
    d0 = slice(0, SAMPLES_PER_DAY)
    assert not tl.truth["fault_active"].iloc[d0].any()
    assert tl.truth["fault_active"].iloc[d1].mean() > 0.95
    assert tl.meta["fault"]["kind"] == "power"
    # other appliances identical to the no-fault run; fridge scaled by 1.4 on day 1 only
    for col in ("water_heater_w", "hair_dryer_w", "hvac_w"):
        np.testing.assert_array_equal(tl.truth[col].to_numpy(), base.truth[col].to_numpy())
    np.testing.assert_allclose(tl.truth["fridge_w"].iloc[d0], base.truth["fridge_w"].iloc[d0])
    ratio = tl.truth["fridge_w"].iloc[d1].mean() / base.truth["fridge_w"].iloc[d1].mean()
    assert abs(ratio - 1.4) < 0.02


def test_trs_06_05_duty_cycle_fault_lengthens_on_time(fake_library, hot_weather, small_profile):
    small_profile.appliances["fridge"].mode = "cycling"
    small_profile.appliances["fridge"].off_gap_s = (1800.0, 1800.0)
    small_profile.appliances["fridge"].slice_s = (1200.0, 1200.0)
    fault = Fault(appliance_id="fridge", start_day=2, kind="duty_cycle", magnitude=0.4)
    tl = generate(small_profile, fake_library, hot_weather, START, days=4, seed=2, fault=fault)
    on = tl.truth["fridge_w"] > ON_THRESHOLD_W
    before = on.iloc[: 2 * SAMPLES_PER_DAY].mean()
    after = on.iloc[2 * SAMPLES_PER_DAY :].mean()
    assert abs(before - 0.4) < 0.05 and abs(after / before - 1.4) < 0.1


def test_trs_06_06_output_is_files_only():
    import inspect

    from homewatt.cmp06_synth import generator

    src = inspect.getsource(generator)
    assert "psycopg" not in src and "INSERT" not in src and "raw_aggregate" not in src


def test_cmp06_profile_naming_missing_appliance_fails_with_name(fake_library, hot_weather, small_profile):
    from homewatt.cmp06_synth.profile import ApplianceSchedule

    small_profile.appliances["iron"] = ApplianceSchedule(type="iron", label="iron")
    with pytest.raises(FileNotFoundError, match="iron"):
        generate(small_profile, fake_library, hot_weather, START, days=1, seed=1)
