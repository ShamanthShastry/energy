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


# ---------------------------------------------------------------- deployed model (OI-13, v0.10)
# co-v2 is what runs on a household's stored aggregate. Power only: the harmonics variant did not
# help CO net (TRS-09-01). It adds two things co-v1 lacks, both needed on a real home:
#   1. an hvac state learned from the synthesized track only (TRS-09-09), since the dataset has none;
#   2. a per-day baseload estimate, so standby load is not explained as small appliances.
# co-v2 (first fit, 2026-10-04) also counted the dataset laptop as always on; its 12,960 rows for
# 2025-06-30 and its metrics stay under that version (TRS-08-06). co-v2.1 counts the fridge only.
MODEL_VERSION_DEPLOY = "co-v2.1"
ALWAYS_ON_FRACTION = 0.95  # TRS-00-04 on-time fraction above which an appliance counts as always on
# Only appliance types that run continuously by nature. The dataset laptop is a charger left in all
# session (on-time 0.99) but households use laptops in sessions, so on-time alone over-counts.
ALWAYS_ON_TYPES = frozenset({"fridge"})
BASELOAD_QUANTILE = 0.01


def always_on_types(library_dir) -> set[str]:
    import json

    per = json.loads((library_dir / "manifest.json").read_text())["per_appliance"]
    return {a for a, v in per.items() if v.get("on_time_fraction_mean", 0.0) >= ALWAYS_ON_FRACTION and a in ALWAYS_ON_TYPES}


def synthetic_hvac_state(hvac_w: np.ndarray) -> ApplianceStates | None:
    """Off plus one on-level from the synthesized hvac track (TRS-09-09: synthetic data only)."""
    on = np.asarray(hvac_w, float)
    on = on[on > ON_THRESHOLD_W]
    if len(on) < 10:
        return None
    w = float(np.median(on))
    sig = np.zeros((2, 33))
    sig[1, 0] = w
    return ApplianceStates("hvac", np.array([0.0, w]), sig)


class DeployedCO(CO):
    """CO with a per-window baseload estimate: the low quantile of active power minus the
    always-on appliances' levels, floored at zero."""

    def __init__(self, states: list[ApplianceStates], always_on: set[str]):
        super().__init__(states, use_harmonics=False)
        self.version = MODEL_VERSION_DEPLOY
        self.always_on_w = float(sum(s.watts[-1] for s in states if s.appliance in always_on))

    def estimate_baseload(self, p_active_w: np.ndarray) -> float:
        if len(p_active_w) == 0:
            return 0.0
        return max(float(np.quantile(p_active_w, BASELOAD_QUANTILE)) - self.always_on_w, 0.0)

    def disaggregate_window(self, agg: np.ndarray) -> tuple[pd.DataFrame, float]:
        self.baseload_w = self.estimate_baseload(agg[:, IDX_P_ACTIVE])
        return self.disaggregate(agg), self.baseload_w


def build_deployed(library_dir, hvac_w: np.ndarray | None) -> DeployedCO:
    from homewatt.cmp00_activations.library import ActivationLibrary
    from homewatt.schema import DATASET_APPLIANCE_TYPES

    lib = ActivationLibrary(library_dir)  # train sessions only
    states = [s for s in (learn_states(a, lib.activations(a)) for a in DATASET_APPLIANCE_TYPES) if s is not None]
    hv = synthetic_hvac_state(hvac_w) if hvac_w is not None else None
    if hv is not None:
        states.append(hv)
    return DeployedCO(states, always_on_types(library_dir))


def evaluate_deployed(library_dir, model: DeployedCO, synthetic: pd.DataFrame | None = None) -> pd.DataFrame:
    """TRS-09-04/05 on the held-out real sessions; hvac scored separately on synthetic data and
    flagged synthetic (TRS-09-09). `synthetic`: aggregate fields + hvac_w, not used to learn hvac."""
    from homewatt.cmp00_activations.split import read_split

    rows = []
    for sid in read_split(library_dir / "split.json")["test"]:
        df = pd.read_parquet(library_dir / "sessions" / f"{sid}.parquet")
        df = df[df["labelled"]]
        est, _ = model.disaggregate_window(df[list(NUMERIC_FIELDS)].to_numpy())
        for a in model.names:
            if f"{a}_w" in df:
                rows.append({"session": sid, "appliance": a, "synthetic": False, **metrics(df[f"{a}_w"].to_numpy(), est[a].to_numpy())})
    if synthetic is not None and "hvac" in model.names and len(synthetic):
        for day, g in synthetic.groupby(synthetic["ts"].dt.floor("D")):
            est, _ = model.disaggregate_window(g[list(NUMERIC_FIELDS)].to_numpy())
            rows.append({"session": f"synthetic {day.date()}", "appliance": "hvac", "synthetic": True,
                         **metrics(g["hvac_w"].to_numpy(), est["hvac"].to_numpy())})
    return pd.DataFrame(rows)


__all__ = ["CO", "DeployedCO", "learn_states", "metrics", "evaluate", "summarise", "build_deployed", "evaluate_deployed", "HARMONICS"]
