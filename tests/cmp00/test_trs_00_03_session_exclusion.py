import numpy as np
import pandas as pd
import pytest

from homewatt.cmp00_activations.consistency import check_session
from homewatt.schema import NUMERIC_FIELDS


def _frame(p, t0=0):
    df = pd.DataFrame({f: np.zeros(len(p), dtype=np.float32) for f in NUMERIC_FIELDS})
    df["p_active_w"] = np.asarray(p, dtype=np.float32)
    df.insert(0, "t_s", t0 + np.arange(len(p)) * 2)
    return df


def test_trs_00_03_consistent_session_retained():
    agg = _frame(np.full(1000, 300.0))
    subs = {"a": _frame(np.full(1000, 100.0)), "b": _frame(np.full(1000, 195.0))}
    c = check_session("x", agg, subs)
    assert c.consistent and abs(c.ratio - 0.983) < 0.01


def test_trs_00_03_session_off_by_more_than_10pct_is_excluded_with_reason():
    agg = _frame(np.full(1000, 300.0))
    subs = {"a": _frame(np.full(1000, 100.0)), "b": _frame(np.full(50, 255.0))}  # b covers 5%
    c = check_session("05-21", agg, subs)
    assert not c.consistent
    assert c.reason and "1.18" in c.reason and "b" in c.reason
    assert c.coverage["b"] < 0.5


@pytest.mark.needs_library
def test_trs_00_03_manifest_excludes_05_21_only():
    import json

    from tests.conftest import LIBRARY

    m = json.loads((LIBRARY / "manifest.json").read_text())
    assert list(m["excluded"]) == ["05-21"]
    assert 1.10 < m["consistency"]["05-21"]["ratio"] < 1.30
    assert all(c["consistent"] for s, c in m["consistency"].items() if s != "05-21")
