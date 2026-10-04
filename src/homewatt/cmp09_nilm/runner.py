"""CMP-09 deployment (OI-13, resolved v0.10): run the deployed splitter on a household's stored
aggregate and keep its output as 60 s means, the cadence of the simulated feed.

  fit      learn co-v2 once and save it to data/models/co-v2.json, so every run and every
           household uses the same model version (TRS-09-08).
  run_day  read one window from raw_aggregate (CMP-07, the only input; TRS-09 inputs), skip
           gapped minutes (CMP-09 error handling), write per-appliance 60 s means plus the
           'baseload' residual (TRS-08-05) as source='nilm' through write_appliance_power.

The writer adds rows under the model version and never replaces them (TRS-08-06). Readers prefer
plug, then sim, then nilm (TRS-08-01), so a household without a simulated feed runs on these
estimates. Watts only (TRS-09-06)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from homewatt.cmp09_nilm.co import MODEL_VERSION_DEPLOY, ApplianceStates, DeployedCO
from homewatt.config import REPO_ROOT
from homewatt.schema import NUMERIC_FIELDS

log = logging.getLogger(__name__)

PERIOD_S = 60.0
GAP_S = 10.0  # TRS-05-03
MODEL_DIR = REPO_ROOT / "data" / "models"


def model_path(version: str = MODEL_VERSION_DEPLOY) -> Path:
    return MODEL_DIR / f"{version}.json"


def save_model(model: DeployedCO, path: Path, provenance: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "model_version": model.version,
        "always_on_w": model.always_on_w,
        "states": [{"appliance": str(s.appliance), "watts": [float(w) for w in s.watts]} for s in model.states],
        "provenance": provenance,
    }
    path.write_text(json.dumps(doc, indent=2))


def load_model(path: Path | None = None) -> DeployedCO:
    doc = json.loads((path or model_path()).read_text())
    states = []
    for s in doc["states"]:
        w = np.asarray(s["watts"], float)
        sig = np.zeros((len(w), 33))
        sig[:, 0] = w
        states.append(ApplianceStates(s["appliance"], w, sig))
    m = DeployedCO(states, set())
    m.version = doc["model_version"]
    m.always_on_w = float(doc["always_on_w"])
    return m


def minute_means(ts: pd.Series, est: pd.DataFrame, agg_w: np.ndarray, gaps: list[tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    """60 s means per appliance plus the baseload residual; minutes touched by a gap are dropped."""
    df = est.copy()
    df["baseload"] = np.maximum(agg_w - est.sum(axis=1).to_numpy(), 0.0)  # TRS-08-05
    df["ts"] = ts.to_numpy()
    t = pd.to_datetime(df["ts"], utc=True)
    d = t.diff().dt.total_seconds().to_numpy()
    bad = [(t.iloc[i - 1], t.iloc[i]) for i in np.where(d > GAP_S)[0]] + list(gaps)
    means = df.set_index("ts").resample(f"{int(PERIOD_S)}s", label="left", closed="left").mean().dropna(how="all")
    if bad and len(means):
        idx = means.index
        keep = np.ones(len(idx), dtype=bool)
        for g0, g1 in bad:
            keep &= ~((idx + pd.Timedelta(seconds=PERIOD_S) > g0) & (idx < g1))
        means = means[keep]
    return means


def run_day(client, household_id: str, start: datetime, end: datetime, model: DeployedCO | None = None) -> dict:
    """Disaggregate [start, end) from the store and write 60 s nilm rows. Returns a small report."""
    from homewatt.cmp07_raw_store.reader import read_gaps, read_window
    from homewatt.cmp08_appliance_store.writer import AppliancePowerWriter

    model = model or load_model()
    win = read_window(client, household_id, start, end)
    if win.empty:
        return {"rows": 0, "reason": "no raw data"}
    apps = client.sql(f"SELECT appliance_id, type FROM appliance WHERE household_id = '{household_id}'")
    by_type: dict[str, str] = {}
    for r in apps.to_dict("records") if len(apps) else []:
        by_type.setdefault(str(r["type"]), str(r["appliance_id"]))
    est, baseload = model.disaggregate_window(win[list(NUMERIC_FIELDS)].to_numpy())
    gaps = read_gaps(client, household_id, start, end)
    means = minute_means(win["ts"], est, win["p_active_w"].to_numpy(dtype=float),
                         list(zip(gaps["gap_start"], gaps["gap_end"], strict=True)) if len(gaps) else [])
    cols = {c: by_type[c] for c in model.names if c in by_type}  # appliances the household lacks are skipped
    cols["baseload"] = "baseload"
    long = means[list(cols)].rename(columns=cols).reset_index().melt(id_vars="ts", var_name="appliance_id", value_name="watts")
    long["household_id"] = household_id
    n = AppliancePowerWriter(client).write_frame(long[["household_id", "appliance_id", "ts", "watts"]], "nilm", model.version, PERIOD_S)
    return {"rows": n, "minutes": len(means), "baseload_w": round(baseload, 1), "model_version": model.version}


def fit_provenance(library_dir: Path, hvac_source: str) -> dict:
    split = json.loads((library_dir / "split.json").read_text())
    return {"fitted_at": pd.Timestamp.now(tz="UTC").isoformat(), "train_sessions": split["train"], "hvac_source": hvac_source,
            "note": "power only; hvac state from synthesized data (TRS-09-09); baseload estimated per window"}


__all__ = ["PERIOD_S", "fit_provenance", "load_model", "minute_means", "model_path", "run_day", "save_model"]
