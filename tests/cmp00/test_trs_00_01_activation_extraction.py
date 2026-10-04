import numpy as np
import pandas as pd

from homewatt.cmp00_activations.activations import extract_activations, find_runs
from homewatt.schema import NUMERIC_FIELDS


def test_trs_00_01_runs_need_three_samples_over_10w_and_get_five_sample_margin():
    p = np.zeros(100)
    p[20:23] = 50       # 3 samples -> activation
    p[40:42] = 50       # 2 samples -> ignored
    p[60:70] = 11       # 10 samples just above threshold -> activation
    p[80:90] = 10       # at threshold -> not on
    runs = find_runs(p)
    assert [(r.on_start, r.on_end) for r in runs] == [(20, 22), (60, 69)]
    assert [(r.start, r.end) for r in runs] == [(15, 27), (55, 74)]


def test_trs_00_01_margin_is_clipped_at_trace_edges():
    p = np.zeros(10)
    p[0:4] = 100
    r = find_runs(p)[0]
    assert r.start == 0 and r.end == 8


def test_trs_00_01_activation_frame_carries_all_36_fields_and_ids():
    n = 50
    df = pd.DataFrame({f: np.zeros(n, dtype=np.float32) for f in NUMERIC_FIELDS})
    df.insert(0, "t_s", np.arange(n) * 2)
    df.loc[10:20, "p_active_w"] = 500.0
    df.loc[10:20, "h1"] = 2.0
    acts = extract_activations(df, "05-12", "hair_dryer")
    assert set(NUMERIC_FIELDS) <= set(acts.columns)
    assert acts["activation_id"].unique().tolist() == ["05-12:hair_dryer:0000"]
    assert len(acts) == 11 + 10  # run + 5 margin each side
    assert acts["i"].tolist() == list(range(21))
    assert acts["h1"].max() == 2.0
