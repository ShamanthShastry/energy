import numpy as np
import pytest

from homewatt.cmp09_nilm.co import CO, learn_states, metrics
from homewatt.schema import NUMERIC_FIELDS
from tests.conftest import REPO, make_activation


def test_co_separates_two_appliances_with_distinct_power():
    rng = np.random.default_rng(0)
    a = learn_states("kettle", [make_activation(100, 2000.0, rng)])
    b = learn_states("lamp", [make_activation(100, 60.0, rng)])
    model = CO([a, b], use_harmonics=False)
    agg = np.zeros((4, len(NUMERIC_FIELDS)))
    agg[:, 0] = [0, 60, 2000, 2060]
    est = model.disaggregate(agg)
    assert (est["kettle"] > 1000).tolist() == [False, False, True, True]
    assert (est["lamp"] > 30).tolist() == [False, True, False, True]


def test_trs_09_05_metrics_mae_f1_energy_ratio():
    m = metrics(np.array([0, 100, 100, 0]), np.array([0, 100, 0, 0]))
    assert m["mae_w"] == 25 and m["f1_10w"] == pytest.approx(2 / 3) and m["energy_ratio"] == 0.5


def test_trs_09_06_nilm_module_emits_no_money_and_imports_no_tariff():
    for p in (REPO / "src" / "homewatt" / "cmp09_nilm").glob("*.py"):
        t = p.read_text()
        assert "cmp04_tariff" not in t and "usd" not in t.lower(), p.name


@pytest.mark.needs_library
def test_trs_09_03_04_evaluation_uses_only_held_out_real_sessions():
    from homewatt.cmp00_activations.split import read_split
    from homewatt.cmp09_nilm.co import evaluate

    res, model = evaluate(REPO / "data" / "library", use_harmonics=False)
    split = read_split(REPO / "data" / "library" / "split.json")
    assert set(res["session"]) == set(split["test"]) and not set(res["session"]) & set(split["train"])
    assert {"mae_w", "f1_10w", "energy_ratio"} <= set(res.columns)
