"""Combinatorial optimisation, the classic NILM baseline (Hart 1992; NILMTK's CO).

Each appliance gets a few power states learned from its training activations (off plus one or
two on-levels). For every aggregate sample the model picks the combination of states whose
summed signature is closest to the measurement. Two variants (TRS-09-01 ablation):
  co-v1             matches active power only;
  co-v1-harmonics   matches active power and current harmonics h1..h32, each feature scaled.
Evaluation is on the held-out sessions of split.json only (TRS-09-03/04, TRS-SYS-07).
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from homewatt.schema import HARMONICS, IDX_H1, IDX_P_ACTIVE, NUMERIC_FIELDS, ON_THRESHOLD_W

log = logging.getLogger(__name__)
MODEL_VERSION = "co-v1"
MODEL_VERSION_H = "co-v1-harmonics"
FEATS_H = [IDX_P_ACTIVE, *range(IDX_H1, IDX_H1 + 32)]


@dataclass
class ApplianceStates:
    appliance: str
    watts: np.ndarray  # (k,) including off = 0
    signature: np.ndarray  # (k, 33) mean [p, h1..h32] per state, off = zeros


def _kmeans_1d(x: np.ndarray, k: int, iters: int = 30) -> np.ndarray:
    c = np.quantile(x, np.linspace(0.2, 0.8, k))
    for _ in range(iters):
        lab = np.argmin(np.abs(x[:, None] - c[None, :]), axis=1)
        new = np.array([x[lab == j].mean() if np.any(lab == j) else c[j] for j in range(k)])
        if np.allclose(new, c):
            break
        c = new
    return c


def learn_states(appliance: str, activations: list[np.ndarray]) -> ApplianceStates | None:
    """Off plus one on-level, or two when the on-power spread is wide (heating elements that idle)."""
    if not activations:
        return None
    on = np.concatenate([a[a[:, IDX_P_ACTIVE] > ON_THRESHOLD_W] for a in activations])
    if len(on) < 10:
        return None
    p = on[:, IDX_P_ACTIVE]
    k = 2 if np.quantile(p, 0.9) / max(np.quantile(p, 0.1), 1.0) > 3 else 1
    centers = np.sort(_kmeans_1d(p, k))
    lab = np.argmin(np.abs(p[:, None] - centers[None, :]), axis=1)
    sig = [np.zeros(33)] + [on[lab == j][:, FEATS_H].mean(axis=0) for j in range(k)]
    return ApplianceStates(appliance, np.concatenate([[0.0], centers]), np.array(sig))


class CO:
    def __init__(self, states: list[ApplianceStates], use_harmonics: bool, baseload_w: float = 0.0):
        self.states = states
        self.names = [s.appliance for s in states]
        self.use_harmonics = use_harmonics
        self.baseload_w = baseload_w
        combos = list(itertools.product(*[range(len(s.watts)) for s in states]))
        self.combos = np.array(combos, dtype=np.int16)  # (C, A)
        self.combo_sig = np.zeros((len(combos), 33))
        for a, s in enumerate(states):
            self.combo_sig += s.signature[self.combos[:, a]]
        self.version = MODEL_VERSION_H if use_harmonics else MODEL_VERSION

    def disaggregate(self, agg: np.ndarray, chunk: int = 20000) -> pd.DataFrame:
        """agg: (n, 36) in NUMERIC_FIELDS order. Returns watts per appliance per sample."""
        x = agg[:, FEATS_H].astype(np.float64).copy()
        x[:, 0] = np.maximum(x[:, 0] - self.baseload_w, 0.0)
        if self.use_harmonics:
            scale = x.std(axis=0)
            scale[scale == 0] = 1.0
            scale[0] = scale[0] / 4.0  # weight active power more than any single harmonic
            xs, cs = x / scale, self.combo_sig / scale
        else:
            xs, cs = x[:, :1], self.combo_sig[:, :1]
        best = np.empty(len(x), dtype=np.int64)
        cn = (cs**2).sum(axis=1)
        for i in range(0, len(x), chunk):
            b = xs[i : i + chunk]
            d = (b**2).sum(axis=1)[:, None] - 2 * b @ cs.T + cn[None, :]
            best[i : i + chunk] = np.argmin(d, axis=1)
        idx = self.combos[best]
        out = {name: self.states[a].watts[idx[:, a]] for a, name in enumerate(self.names)}
        return pd.DataFrame(out)


def metrics(true_w: np.ndarray, est_w: np.ndarray, dt_s: float = 2.0) -> dict[str, float]:
    """TRS-09-05: MAE in watts, F1 of on/off at 10 W, estimated kWh / true kWh."""
    t, e = np.asarray(true_w, float), np.asarray(est_w, float)
    ok = ~np.isnan(t)
    t, e = t[ok], e[ok]
    mae = float(np.abs(t - e).mean()) if len(t) else float("nan")
    ton, eon = t > ON_THRESHOLD_W, e > ON_THRESHOLD_W
    tp, fp, fn = int((ton & eon).sum()), int((~ton & eon).sum()), int((ton & ~eon).sum())
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else float("nan")
    ratio = float(e.sum() / t.sum()) if t.sum() > 0 else float("nan")
    return {"mae_w": mae, "f1_10w": f1, "energy_ratio": ratio}


def evaluate(library_dir, use_harmonics: bool) -> tuple[pd.DataFrame, CO]:
    """Learn states on train sessions, score on the held-out real sessions (TRS-09-04)."""
    from homewatt.cmp00_activations.library import ActivationLibrary
    from homewatt.schema import DATASET_APPLIANCE_TYPES

    lib = ActivationLibrary(library_dir)  # train sessions only
    states = [s for s in (learn_states(a, lib.activations(a)) for a in DATASET_APPLIANCE_TYPES) if s is not None]
    model = CO(states, use_harmonics)
    rows = []
    for sid in lib.split["test"]:
        df = pd.read_parquet(library_dir / "sessions" / f"{sid}.parquet")
        df = df[df["labelled"]]
        est = model.disaggregate(df[list(NUMERIC_FIELDS)].to_numpy())
        for a in model.names:
            m = metrics(df[f"{a}_w"].to_numpy(), est[a].to_numpy())
            rows.append({"session": sid, "appliance": a, **m})
    res = pd.DataFrame(rows)
    return res, model


def summarise(res: pd.DataFrame) -> pd.DataFrame:
    return res.groupby("appliance")[["mae_w", "f1_10w", "energy_ratio"]].mean()


__all__ = ["CO", "learn_states", "metrics", "evaluate", "summarise", "HARMONICS"]
