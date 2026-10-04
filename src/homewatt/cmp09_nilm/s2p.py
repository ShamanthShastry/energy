"""CMP-09 seq2point (OI-03): a 1-D CNN that reads a 299-sample window (2 s, about 10 min) of the
whole-home signal and estimates each appliance at the window's centre sample.

  TRS-09-01  inputs p_active_w, irms_a, power_factor, h1..h32; a power-only variant is the ablation
  TRS-09-02  one shared encoder, one head pair per appliance: watts (>= 0) and on_prob
  TRS-09-03  trained on the 12 train sessions of split.json (plus synthetic days, below), never a
             test session; TRS-09-04 scored on the 3 real held-out sessions
  TRS-09-09  the hvac head learns only from synthesized days (real sessions carry no HVAC, so its
             target there is a true zero); its metrics are labelled synthetic
Inference never imports torch (see NumpyNet). Synthetic days are CMP-06 timelines built from the training sessions' activations only, so no test
session leaks in; there the laptop and screen switch on and off, which the real recordings never
show. Watts only (TRS-09-06).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from homewatt.schema import NUMERIC_FIELDS, ON_THRESHOLD_W

log = logging.getLogger(__name__)

# Watts-head loss, by version (all scored in model_metric): v1 plain MSE over every sample, so rare
# appliances regressed to 0 W; v2 MSE on on-samples only, so a false "on" from the classifier cost an
# appliance's full draw; v3 class-balanced MSE (on and off samples carry equal total weight per
# appliance), which keeps off near 0 W without drowning out the rare ones.
MODEL_VERSION = "s2p-v3"
MODEL_VERSION_POWER = "s2p-v3-power"  # TRS-09-01 ablation
WINDOW = 299  # TRS-09 inputs: W = 299 at 2 s
HALF = WINDOW // 2
APPLIANCES = ("fridge", "water_heater", "hair_dryer", "straightener", "iron", "laptop", "screen", "hvac")
FEATS = ("p_active_w", "irms_a", "power_factor", *(f"h{k}" for k in range(1, 33)))
FEATS_POWER = ("p_active_w",)
FEAT_IDX = {f: NUMERIC_FIELDS.index(f) for f in FEATS}


# ---------------------------------------------------------------- data
@dataclass
class Series:
    """One continuous recording: features (n, F) in NUMERIC_FIELDS order and targets (n, A) watts."""

    name: str
    x: np.ndarray
    y: np.ndarray
    synthetic: bool


def real_sessions(library_dir: Path, ids: list[str]) -> list[Series]:
    out = []
    for sid in ids:
        df = pd.read_parquet(library_dir / "sessions" / f"{sid}.parquet")
        df = df[df["labelled"]]
        y = np.stack([df[f"{a}_w"].to_numpy(np.float32) if f"{a}_w" in df else np.zeros(len(df), np.float32) for a in APPLIANCES], 1)
        out.append(Series(sid, df[list(NUMERIC_FIELDS)].to_numpy(np.float32), np.nan_to_num(y), False))
    return out


def synthetic_days(timeline_dir: Path, first_day: int, last_day: int) -> list[Series]:
    """Days [first_day, last_day) of a CMP-06 timeline, one Series per day."""
    agg = pd.read_parquet(timeline_dir / "aggregate.parquet")
    truth = pd.read_parquet(timeline_dir / "truth.parquet")
    df = agg.merge(truth, on="ts")
    t0 = df["ts"].min()
    out = []
    for d in range(first_day, last_day):
        g = df[(df["ts"] >= t0 + pd.Timedelta(days=d)) & (df["ts"] < t0 + pd.Timedelta(days=d + 1))]
        if g.empty:
            continue
        y = np.stack([g[f"{a}_w"].to_numpy(np.float32) for a in APPLIANCES], 1)
        out.append(Series(f"synthetic day {d + 1}", g[list(NUMERIC_FIELDS)].to_numpy(np.float32), y, True))
    return out


def _windows(x: np.ndarray, centres: np.ndarray) -> np.ndarray:
    """(len(centres), WINDOW, F) with edge padding, so every sample gets an estimate."""
    pad = np.pad(x, ((HALF, HALF), (0, 0)), mode="edge")
    idx = centres[:, None] + np.arange(WINDOW)[None, :]
    return pad[idx]


# ---------------------------------------------------------------- model
def _torch():
    import torch

    return torch


def best_device() -> str:
    """Training device: the Mac's GPU (MPS) when present, else CPU."""
    torch = _torch()
    return "mps" if torch.backends.mps.is_available() else "cpu"


def build_net(n_feat: int, n_app: int):
    torch = _torch()
    nn = torch.nn

    class Seq2Point(nn.Module):
        """Shared encoder (TRS-10-01 freezes it for per-home fine-tuning) + per-appliance heads."""

        def __init__(self):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Conv1d(n_feat, 32, 9, padding=4), nn.ReLU(),
                nn.Conv1d(32, 32, 7, padding=3, stride=2), nn.ReLU(),
                nn.Conv1d(32, 48, 5, padding=2, stride=2), nn.ReLU(),
                nn.Conv1d(48, 64, 5, padding=2, stride=2), nn.ReLU(),
                nn.Conv1d(64, 64, 3, padding=1, stride=2), nn.ReLU(),
                nn.Flatten(), nn.Linear(64 * 19, 256), nn.ReLU(), nn.Dropout(0.1),
            )
            self.watts = nn.Linear(256, n_app)
            self.on = nn.Linear(256, n_app)

        def forward(self, x):  # x: (B, W, F)
            z = self.encoder(x.transpose(1, 2))
            return nn.functional.softplus(self.watts(z)), self.on(z)

    return Seq2Point()


# ---------------------------------------------------------------- inference without torch
# Daily runs and the API load the weights as .npz and run the forward pass in numpy. PyTorch and
# LightGBM (CMP-11) each bundle an OpenMP runtime and crash a macOS process that loads both, so
# torch is imported only by training (`homewatt cmp09 s2p-train`), which runs on its own.
CONV = (  # (kernel, padding, stride) per encoder conv, in order; must match build_net
    (9, 4, 1), (7, 3, 2), (5, 2, 2), (5, 2, 2), (3, 1, 2),
)


def _conv1d(x: np.ndarray, w: np.ndarray, b: np.ndarray, k: int, p: int, s: int) -> np.ndarray:
    """x (B, C, L) -> (B, O, L'), same arithmetic as torch.nn.Conv1d."""
    xp = np.pad(x, ((0, 0), (0, 0), (p, p)))
    L = (xp.shape[2] - k) // s + 1
    idx = np.arange(L)[:, None] * s + np.arange(k)[None, :]
    xw = xp[:, :, idx]  # (B, C, L', k)
    return np.einsum("bclk,ock->bol", xw, w, optimize=True) + b[None, :, None]


def _softplus(x: np.ndarray) -> np.ndarray:
    return np.where(x > 20, x, np.log1p(np.exp(np.minimum(x, 20))))


class NumpyNet:
    """The trained Seq2Point as numpy arrays (encoder.{0,2,4,6,8}.weight/bias, encoder.11 linear, watts, on)."""

    def __init__(self, weights: dict[str, np.ndarray]):
        self.w = {k: np.asarray(v, np.float32) for k, v in weights.items()}

    def __call__(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = np.transpose(x, (0, 2, 1)).astype(np.float32)  # (B, F, W)
        for i, (k, p, s) in zip((0, 2, 4, 6, 8), CONV, strict=True):
            h = np.maximum(_conv1d(h, self.w[f"encoder.{i}.weight"], self.w[f"encoder.{i}.bias"], k, p, s), 0.0)
        z = h.reshape(len(h), -1) @ self.w["encoder.11.weight"].T + self.w["encoder.11.bias"]
        z = np.maximum(z, 0.0)
        watts = _softplus(z @ self.w["watts.weight"].T + self.w["watts.bias"])
        logit = z @ self.w["on.weight"].T + self.w["on.bias"]
        return watts, 1.0 / (1.0 + np.exp(-logit))


@dataclass
class S2P:
    feats: tuple[str, ...]
    version: str
    mean: np.ndarray = field(default_factory=lambda: np.zeros(0))
    std: np.ndarray = field(default_factory=lambda: np.ones(0))
    scale: np.ndarray = field(default_factory=lambda: np.ones(len(APPLIANCES)))  # watts per unit output
    net: object = None
    names: list[str] = field(default_factory=lambda: list(APPLIANCES))

    def _x(self, raw: np.ndarray) -> np.ndarray:
        x = raw[:, [FEAT_IDX[f] for f in self.feats]].astype(np.float32)
        return (x - self.mean) / self.std

    def predict(self, raw: np.ndarray, batch: int = 2048) -> tuple[np.ndarray, np.ndarray]:
        """Watts (n, A) and on_prob (n, A) for every sample of a continuous recording. Runs the
        numpy net when the model was loaded from .npz, else the torch net (training process)."""
        x = self._x(raw)
        w_out, p_out = [], []
        if isinstance(self.net, NumpyNet):
            for i in range(0, len(x), batch):
                w, prob = self.net(_windows(x, np.arange(i, min(i + batch, len(x)))))
                w_out.append((w * self.scale).astype(np.float32))
                p_out.append(prob.astype(np.float32))
        else:
            torch = _torch()
            dev = next(self.net.parameters()).device
            self.net.eval()
            with torch.no_grad():
                for i in range(0, len(x), batch):
                    xb = torch.from_numpy(_windows(x, np.arange(i, min(i + batch, len(x))))).to(dev)
                    w, logit = self.net(xb)
                    w_out.append((w.cpu().numpy() * self.scale).astype(np.float32))
                    p_out.append(torch.sigmoid(logit).cpu().numpy().astype(np.float32))
        w, p = np.concatenate(w_out), np.concatenate(p_out)
        w[p < 0.5] = 0.0  # TRS-09-02: off when the classifier says off
        return w, p

    # same interface as DeployedCO, so the runner can serve either (TRS-09-10)
    def disaggregate_window(self, agg: np.ndarray) -> tuple[pd.DataFrame, float]:
        w, _ = self.predict(agg)
        est = pd.DataFrame(w, columns=self.names)
        resid = agg[:, NUMERIC_FIELDS.index("p_active_w")] - w.sum(axis=1)
        return est, float(max(np.median(resid), 0.0))

    def save(self, path: Path, provenance: dict) -> None:
        """.pt for retraining or fine-tuning (CMP-10), .npz for every torch-free run, .json metadata."""
        torch = _torch()
        path.parent.mkdir(parents=True, exist_ok=True)
        sd = {k: v.detach().cpu() for k, v in self.net.state_dict().items()}
        torch.save(sd, path.with_suffix(".pt"))
        np.savez(path.with_suffix(".npz"), **{k: v.numpy() for k, v in sd.items()})
        path.with_suffix(".json").write_text(json.dumps({
            "model_version": self.version, "kind": "seq2point", "feats": list(self.feats), "appliances": self.names,
            "mean": self.mean.tolist(), "std": self.std.tolist(), "scale": self.scale.tolist(), "window": WINDOW,
            "provenance": provenance,
        }, indent=1))

    @classmethod
    def load(cls, path: Path) -> S2P:
        """Torch-free: weights from .npz, forward pass in numpy."""
        meta = json.loads(path.with_suffix(".json").read_text())
        m = cls(tuple(meta["feats"]), meta["model_version"], np.asarray(meta["mean"], np.float32), np.asarray(meta["std"], np.float32),
                np.asarray(meta["scale"], np.float32), names=list(meta["appliances"]))
        with np.load(path.with_suffix(".npz")) as z:
            m.net = NumpyNet({k: z[k] for k in z.files})
        return m


# ---------------------------------------------------------------- training
def train(series: list[Series], feats: tuple[str, ...], version: str, epochs: int = 8, per_epoch: int = 160_000,
          seed: int = 7, device: str | None = None) -> S2P:
    torch = _torch()
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = device or best_device()
    m = S2P(feats, version)
    allx = np.concatenate([s.x[:, [FEAT_IDX[f] for f in feats]] for s in series])
    m.mean = allx.mean(axis=0).astype(np.float32)
    m.std = (allx.std(axis=0) + 1e-6).astype(np.float32)
    ally = np.concatenate([s.y for s in series])
    m.scale = np.maximum(np.quantile(np.where(ally > ON_THRESHOLD_W, ally, np.nan), 0.95, axis=0, method="linear"), 10.0)
    m.scale = np.nan_to_num(m.scale, nan=100.0).astype(np.float32)
    xs = [np.pad(m._x(s.x), ((HALF, HALF), (0, 0)), mode="edge") for s in series]  # padded once
    ar = np.arange(WINDOW)
    lens = np.array([len(s.x) for s in series])
    # sample windows: rarer appliances' on-samples weighted up so small loads are seen often
    on_frac = (ally > ON_THRESHOLD_W).mean(axis=0) + 1e-3
    weights = [1.0 + ((s.y > ON_THRESHOLD_W) / on_frac).sum(axis=1) / len(APPLIANCES) for s in series]
    probs = np.concatenate(weights)
    probs /= probs.sum()
    offsets = np.concatenate([[0], np.cumsum(lens)[:-1]])
    m.net = build_net(len(feats), len(APPLIANCES)).to(device)
    opt = torch.optim.Adam(m.net.parameters(), lr=1e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    scale_t = torch.from_numpy(m.scale).to(device)
    bce = torch.nn.BCEWithLogitsLoss()
    bs = 512
    for ep in range(epochs):
        t0 = time.time()
        m.net.train()
        pick = rng.choice(len(probs), size=per_epoch, p=probs)
        sid = np.searchsorted(offsets, pick, side="right") - 1
        loss_sum = 0.0
        for i in range(0, per_epoch, bs):
            p, s_ = pick[i : i + bs], sid[i : i + bs]
            xb = np.empty((len(p), WINDOW, len(feats)), np.float32)
            yb = np.empty((len(p), len(APPLIANCES)), np.float32)
            for k in np.unique(s_):
                sel = s_ == k
                c = p[sel] - offsets[k]
                xb[sel] = xs[k][c[:, None] + ar[None, :]]
                yb[sel] = series[k].y[c]
            xt, yt = torch.from_numpy(xb).to(device), torch.from_numpy(yb).to(device)
            w, logit = m.net(xt)
            on = (yt > ON_THRESHOLD_W).float()
            # class-balanced watts loss (v3): per appliance, on and off samples weigh the same in total
            n_on = on.sum(dim=0).clamp(min=1.0)
            n_off = (1 - on).sum(dim=0).clamp(min=1.0)
            sw = on / n_on + (1 - on) / n_off  # each column sums to 2
            reg = (((w - yt / scale_t) ** 2) * sw).sum() / (2 * w.shape[1])
            loss = reg + bce(logit, on)
            opt.zero_grad()
            loss.backward()
            opt.step()
            loss_sum += float(loss.detach()) * len(p)
        sched.step()
        log.info("%s epoch %d/%d loss %.4f (%.0f s)", version, ep + 1, epochs, loss_sum / per_epoch, time.time() - t0)
    return m  # stays on the training device so evaluation is fast; save() writes CPU tensors


def evaluate(model: S2P, real: list[Series], synthetic: list[Series]) -> pd.DataFrame:
    """TRS-09-05 per appliance on the real held-out sessions; hvac on synthetic days (TRS-09-09)."""
    from homewatt.cmp09_nilm.co import metrics

    rows = []
    for s in real:
        w, _ = model.predict(s.x)
        for j, a in enumerate(model.names):
            if a != "hvac":
                rows.append({"session": s.name, "appliance": a, "synthetic": False, **metrics(s.y[:, j], w[:, j])})
    for s in synthetic:
        w, _ = model.predict(s.x)
        j = model.names.index("hvac")
        rows.append({"session": s.name, "appliance": "hvac", "synthetic": True, **metrics(s.y[:, j], w[:, j])})
    return pd.DataFrame(rows)
