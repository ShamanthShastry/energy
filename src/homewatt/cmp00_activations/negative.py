"""TRS-00-05: negative cases for CMP-05 and CMP-09, derived from a real test session:
one aggregate stream with an injected 30 s gap, one with a duplicated timestamp."""

from __future__ import annotations

import numpy as np
import pandas as pd


def inject_gap(agg: pd.DataFrame, gap_s: float = 30.0, at_fraction: float = 0.5) -> pd.DataFrame:
    """Remove every sample inside a window of `gap_s` seconds starting at `at_fraction` of the
    trace, so consecutive timestamps differ by > gap_s there."""
    t = agg["t_s"].to_numpy()
    t0 = t[0] + (t[-1] - t[0]) * at_fraction
    keep = ~((t >= t0) & (t < t0 + gap_s))
    out = agg.loc[keep].reset_index(drop=True)
    out.attrs["gap_start_s"] = float(t0)
    out.attrs["gap_s"] = float(gap_s)
    return out


def inject_duplicate(agg: pd.DataFrame, at_fraction: float = 0.25) -> pd.DataFrame:
    """Repeat one sample (same t_s, same values) immediately after itself."""
    k = int(len(agg) * at_fraction)
    dup = agg.iloc[[k]]
    out = pd.concat([agg.iloc[: k + 1], dup, agg.iloc[k + 1 :]], ignore_index=True)
    out.attrs["duplicate_t_s"] = float(agg["t_s"].iloc[k])
    assert np.sum(out["t_s"].to_numpy() == out.attrs["duplicate_t_s"]) == 2
    return out
