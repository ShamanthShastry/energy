"""OI-13 (v0.10): the deployed splitter co-v2.1 and its 60 s nilm output."""

import numpy as np
import pandas as pd

from homewatt.cmp09_nilm.co import (
    MODEL_VERSION_DEPLOY,
    DeployedCO,
    learn_states,
    synthetic_hvac_state,
)
from homewatt.cmp09_nilm.runner import PERIOD_S, load_model, minute_means, save_model
from homewatt.cmp15_api.data import latest_nilm
from homewatt.schema import NUMERIC_FIELDS
from tests.conftest import REPO, make_activation


def _model():
    rng = np.random.default_rng(1)
    fridge = learn_states("fridge", [make_activation(200, 58.0, rng)])
    laptop = learn_states("laptop", [make_activation(200, 36.0, rng)])
    return DeployedCO([fridge, laptop, synthetic_hvac_state(np.r_[np.zeros(50), np.full(50, 3000.0)])], {"fridge"})


def test_trs_09_09_hvac_state_comes_from_the_synthesized_track_only():
    hv = synthetic_hvac_state(np.r_[np.zeros(100), np.full(100, 3000.0)])
    assert hv.appliance == "hvac" and hv.watts.tolist() == [0.0, 3000.0]
    assert synthetic_hvac_state(np.zeros(100)) is None


def test_oi_13_baseload_estimate_keeps_standby_out_of_small_appliances():
    m = _model()
    agg = np.zeros((1000, len(NUMERIC_FIELDS)))
    agg[:, 0] = 58.0 + 60.0  # fridge + 60 W standby, nothing else on
    agg[500:, 0] += 3000.0
    est, baseload = m.disaggregate_window(agg)
    assert abs(baseload - 60.0) < 2.0
    assert (est["laptop"] == 0).all() and (est["fridge"] > 50).all()
    assert (est["hvac"][500:] > 2900).all() and (est["hvac"][:500] == 0).all()


def test_oi_13_minute_means_write_baseload_residual_and_drop_gapped_minutes():
    m = _model()
    ts = pd.Series(pd.date_range("2025-07-01 04:00", periods=90, freq="2s", tz="UTC"))
    ts = pd.concat([ts, pd.Series(pd.date_range("2025-07-01 04:04", periods=60, freq="2s", tz="UTC"))], ignore_index=True)
    agg = np.zeros((len(ts), len(NUMERIC_FIELDS)))
    agg[:, 0] = 118.0
    est, _ = m.disaggregate_window(agg)
    means = minute_means(ts, est, agg[:, 0], [])
    # 04:00 and 04:01 are whole; 04:02 is touched by the 04:02:58 -> 04:04:00 gap; 04:03 is empty
    assert [t.strftime("%H:%M") for t in means.index] == ["04:00", "04:01", "04:04", "04:05"]
    assert "baseload" in means and (means["baseload"] >= 0).all()
    assert PERIOD_S == 60.0


def test_trs_09_08_saved_model_round_trips_with_its_version(tmp_path):
    m = _model()
    p = tmp_path / "m.json"
    save_model(m, p, {"note": "test"})
    m2 = load_model(p)
    assert m2.version == MODEL_VERSION_DEPLOY == "co-v2.1"
    assert m2.names == [str(n) for n in m.names] and m2.always_on_w == m.always_on_w


def test_trs_08_06_api_reads_the_deployed_nilm_version_not_an_older_one():
    h = pd.DataFrame({"source": ["sim", "nilm", "nilm"], "model_version": ["cmp06", "co-v2", MODEL_VERSION_DEPLOY], "kwh": [1, 2, 3]})
    rows, mv = latest_nilm(h)
    assert mv == MODEL_VERSION_DEPLOY and rows["kwh"].tolist() == [3]


def test_trs_05_05_nilm_runner_never_touches_raw_aggregate_writes():
    t = (REPO / "src" / "homewatt" / "cmp09_nilm" / "runner.py").read_text()
    assert "ingest_batch" not in t and "read_window" in t
