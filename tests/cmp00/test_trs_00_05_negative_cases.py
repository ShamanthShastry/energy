import numpy as np
import pandas as pd
import pytest

from homewatt.cmp00_activations.negative import inject_duplicate, inject_gap
from homewatt.schema import NUMERIC_FIELDS


def _agg(n=1000):
    df = pd.DataFrame({f: np.ones(n, dtype=np.float32) for f in NUMERIC_FIELDS})
    df["vrms_v"] = 240.0
    df.insert(0, "t_s", np.arange(n) * 2)
    return df


def test_trs_00_05_gap_case_has_a_30s_hole():
    out = inject_gap(_agg(), 30.0, 0.5)
    d = np.diff(out["t_s"].to_numpy())
    assert d.max() >= 30 and (d > 10).sum() == 1
    assert len(out) == 1000 - 15


def test_trs_00_05_duplicate_case_repeats_one_timestamp():
    out = inject_duplicate(_agg(), 0.25)
    vc = out["t_s"].value_counts()
    assert (vc == 2).sum() == 1 and len(out) == 1001


@pytest.mark.needs_library
def test_trs_00_05_negative_files_exist_and_come_from_a_test_session():
    import json

    from homewatt.cmp00_activations.split import read_split
    from tests.conftest import LIBRARY

    m = json.loads((LIBRARY / "manifest.json").read_text())
    split = read_split(LIBRARY / "split.json")
    for key in ("gap30s", "duplicate"):
        rel = m["negative_cases"][key]
        assert (LIBRARY / rel).exists()
        assert rel.split("/")[1].split("_")[0] in split["test"]
