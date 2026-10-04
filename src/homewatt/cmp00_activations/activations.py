"""TRS-00-01: an activation is a contiguous run where sub-metered p_active_w > 10 W for
>= 3 samples, stored with all 37 fields and a 5-sample margin either side."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from homewatt.schema import NUMERIC_FIELDS, ON_THRESHOLD_W


@dataclass(frozen=True)
class Run:
    start: int  # first index of the run (after margin), inclusive
    end: int  # last index, inclusive
    on_start: int  # first index above threshold
    on_end: int  # last index above threshold


def find_runs(
    p_active: np.ndarray,
    on_threshold_w: float = ON_THRESHOLD_W,
    min_samples: int = 3,
    margin: int = 5,
) -> list[Run]:
    """Contiguous runs of p_active > threshold lasting >= min_samples, widened by `margin`
    samples each side and clipped to the array bounds. Runs are never merged, so two
    activations closer than 2*margin may overlap in the margin only."""
    on = np.asarray(p_active) > on_threshold_w
    if on.size == 0 or not on.any():
        return []
    d = np.diff(on.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1) - 1
    runs: list[Run] = []
    n = on.size
    for s, e in zip(starts, ends, strict=True):
        if e - s + 1 < min_samples:
            continue
        runs.append(Run(max(0, s - margin), min(n - 1, e + margin), int(s), int(e)))
    return runs


def extract_activations(
    sub: pd.DataFrame,
    session: str,
    appliance: str,
    on_threshold_w: float = ON_THRESHOLD_W,
    min_samples: int = 3,
    margin: int = 5,
) -> pd.DataFrame:
    """Long-format frame: one row per sample of every activation in one sub-meter trace.

    Columns: session, appliance, activation_id, i (sample index within the activation),
    t_s (session-relative seconds), the 36 numeric fields.
    """
    runs = find_runs(sub["p_active_w"].to_numpy(), on_threshold_w, min_samples, margin)
    parts = []
    for k, r in enumerate(runs):
        seg = sub.iloc[r.start : r.end + 1].reset_index(drop=True)
        seg.insert(0, "i", np.arange(len(seg), dtype=np.int32))
        seg.insert(0, "activation_id", f"{session}:{appliance}:{k:04d}")
        seg.insert(0, "appliance", appliance)
        seg.insert(0, "session", session)
        parts.append(seg)
    if not parts:
        return pd.DataFrame(
            columns=["session", "appliance", "activation_id", "i", "t_s", *NUMERIC_FIELDS]
        )
    return pd.concat(parts, ignore_index=True)


def on_time_fraction(sub: pd.DataFrame, on_threshold_w: float = ON_THRESHOLD_W) -> float:
    if len(sub) == 0:
        return 0.0
    return float((sub["p_active_w"] > on_threshold_w).mean())
