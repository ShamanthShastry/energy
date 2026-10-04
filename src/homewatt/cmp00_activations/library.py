"""Build the activation library, aligned session ground truth, split file, manifest and
negative cases under data/library (TRS-00-01 .. TRS-00-06).

Layout:
  data/library/activations/<appliance>.parquet   long format, one row per sample (TRS-00-01)
  data/library/sessions/<session>.parquet        aggregate 37 fields + per-appliance watts,
                                                 aligned to the aggregate grid; `labelled`
                                                 is false where any sub-meter has no sample
  data/library/split.json                        TRS-00-02, written once
  data/library/manifest.json                     TRS-00-03 consistency, TRS-00-04 counts
  data/library/negative/<session>_gap30s.parquet TRS-00-05
  data/library/negative/<session>_dup.parquet
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from homewatt.cmp00_activations.activations import extract_activations, on_time_fraction
from homewatt.cmp00_activations.consistency import check_session
from homewatt.cmp00_activations.dataset import list_sessions, load_session
from homewatt.cmp00_activations.negative import inject_duplicate, inject_gap
from homewatt.cmp00_activations.split import make_split, read_split, write_split
from homewatt.schema import DATASET_APPLIANCE_TYPES, NUMERIC_FIELDS, SAMPLE_PERIOD_S

log = logging.getLogger(__name__)

#: Appliances with fewer activations than this across the training split are flagged (TRS-00-04).
LOW_ACTIVATION_COUNT = 20
ALIGN_TOLERANCE_S = 1.5


def align_session(agg: pd.DataFrame, subs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate grid + one `<appliance>_w` column per sub-meter matched by nearest t_s within
    ALIGN_TOLERANCE_S. Unmatched -> NaN and labelled=false."""
    out = agg.copy()
    labelled = np.ones(len(out), dtype=bool)
    for app, sub in subs.items():
        m = pd.merge_asof(
            out[["t_s"]],
            sub[["t_s", "p_active_w"]].rename(columns={"p_active_w": f"{app}_w"}),
            on="t_s",
            direction="nearest",
            tolerance=int(np.ceil(ALIGN_TOLERANCE_S)),
        )
        col = m[f"{app}_w"].to_numpy()
        labelled &= ~np.isnan(col)
        out[f"{app}_w"] = col.astype(np.float32)
    out["labelled"] = labelled
    return out


def build_library(dataset_root: Path, out_dir: Path, force_split: bool = False) -> dict:
    sessions = list_sessions(dataset_root)
    (out_dir / "activations").mkdir(parents=True, exist_ok=True)
    (out_dir / "sessions").mkdir(exist_ok=True)
    (out_dir / "negative").mkdir(exist_ok=True)

    consistency: dict[str, dict] = {}
    excluded: dict[str, str] = {}
    per_app_frames: dict[str, list[pd.DataFrame]] = {a: [] for a in DATASET_APPLIANCE_TYPES}
    counts: dict[str, dict[str, int]] = {a: {} for a in DATASET_APPLIANCE_TYPES}
    on_frac: dict[str, dict[str, float]] = {a: {} for a in DATASET_APPLIANCE_TYPES}
    aligned: dict[str, pd.DataFrame] = {}

    for sid, folder in sessions.items():
        agg, subs = load_session(folder)
        c = check_session(sid, agg, subs)
        consistency[sid] = c.as_dict()
        if not c.consistent:
            excluded[sid] = c.reason or "inconsistent"
            log.warning("session %s EXCLUDED (TRS-00-03): %s", sid, c.reason)
            continue
        for app, sub in subs.items():
            acts = extract_activations(sub, sid, app)
            n = acts["activation_id"].nunique() if len(acts) else 0
            counts[app][sid] = int(n)
            on_frac[app][sid] = round(on_time_fraction(sub), 4)
            if len(acts):
                per_app_frames[app].append(acts)
        aligned[sid] = align_session(agg, subs)
        log.info(
            "session %s: %d aggregate rows, activations %s",
            sid,
            len(agg),
            {a: counts[a][sid] for a in DATASET_APPLIANCE_TYPES},
        )

    retained = [s for s in sessions if s not in excluded]
    split_path = out_dir / "split.json"
    if split_path.exists() and not force_split:
        split = read_split(split_path)
        log.info("split.json exists; reusing it (TRS-00-02)")
    else:
        split = make_split(retained, excluded)
        write_split(split_path, split, force=force_split)
        log.info("wrote %s: train=%s test=%s", split_path, split["train"], split["test"])

    for app, frames in per_app_frames.items():
        if frames:
            df = pd.concat(frames, ignore_index=True)
        else:
            df = pd.DataFrame(
                columns=["session", "appliance", "activation_id", "i", "t_s", *NUMERIC_FIELDS]
            )
        df.to_parquet(out_dir / "activations" / f"{app}.parquet", index=False)

    for sid, df in aligned.items():
        df.to_parquet(out_dir / "sessions" / f"{sid}.parquet", index=False)

    # TRS-00-05: negative cases from the first test session's aggregate.
    neg_session = split["test"][0]
    neg_agg = aligned[neg_session][["t_s", *NUMERIC_FIELDS]]
    inject_gap(neg_agg, 30.0).to_parquet(
        out_dir / "negative" / f"{neg_session}_gap30s.parquet", index=False
    )
    inject_duplicate(neg_agg).to_parquet(
        out_dir / "negative" / f"{neg_session}_dup.parquet", index=False
    )

    per_appliance = {}
    for app in DATASET_APPLIANCE_TYPES:
        train_n = sum(counts[app].get(s, 0) for s in split["train"])
        test_n = sum(counts[app].get(s, 0) for s in split["test"])
        per_appliance[app] = {
            "activations_total": train_n + test_n,
            "activations_train": train_n,
            "activations_test": test_n,
            "activations_by_session": counts[app],
            "on_time_fraction_by_session": on_frac[app],
            "on_time_fraction_mean": round(float(np.mean(list(on_frac[app].values()))), 4)
            if on_frac[app]
            else 0.0,
            "flag_low_activations": train_n < LOW_ACTIVATION_COUNT,
        }
    manifest = {
        "trs": ["TRS-00-01", "TRS-00-03", "TRS-00-04", "TRS-00-05"],
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": "Dinar, Paris, Busvelle, Sensors 2025, 25, 4601 (github.com/fariddinar/nilm-dataset)",
        "sample_period_s": SAMPLE_PERIOD_S,
        "extraction": {"on_threshold_w": 10.0, "min_samples": 3, "margin_samples": 5},
        "sessions": {
            s: {
                "rows": consistency[s]["aggregate_rows"],
                "hours": round(consistency[s]["aggregate_rows"] * SAMPLE_PERIOD_S / 3600, 2),
            }
            for s in sessions
        },
        "consistency": consistency,
        "excluded": excluded,
        "per_appliance": per_appliance,
        "negative_cases": {
            "gap30s": f"negative/{neg_session}_gap30s.parquet",
            "duplicate": f"negative/{neg_session}_dup.parquet",
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


class ActivationLibrary:
    """Read side of the library, used by CMP-06. Filters to a set of allowed sessions so that
    excluded sessions (TRS-06-04) and, by default, test sessions never enter a synthetic
    timeline."""

    def __init__(self, library_dir: Path, sessions: list[str] | None = None):
        self.dir = Path(library_dir)
        self.split = read_split(self.dir / "split.json")
        self.manifest = json.loads((self.dir / "manifest.json").read_text())
        self.sessions = sessions if sessions is not None else list(self.split["train"])
        bad = set(self.sessions) & set(self.split["excluded"])
        if bad:
            raise ValueError(f"excluded sessions requested (TRS-06-04): {sorted(bad)}")
        self._cache: dict[str, list[np.ndarray]] = {}

    def activations(self, appliance: str) -> list[np.ndarray]:
        """List of (n_samples, 36) float32 arrays in NUMERIC_FIELDS order."""
        if appliance in self._cache:
            return self._cache[appliance]
        path = self.dir / "activations" / f"{appliance}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"no activation file for '{appliance}' at {path}")
        df = pd.read_parquet(path)
        df = df[df["session"].isin(self.sessions)]
        acts = [
            g.sort_values("i")[list(NUMERIC_FIELDS)].to_numpy(dtype=np.float32)
            for _, g in df.groupby("activation_id", sort=True)
        ]
        self._cache[appliance] = acts
        return acts

    def fingerprint(self) -> str:
        """SHA-256 over the activation parquet files, for CMP-06 provenance (TRS-06-03)."""
        import hashlib

        h = hashlib.sha256()
        for p in sorted((self.dir / "activations").glob("*.parquet")):
            h.update(p.name.encode())
            h.update(p.read_bytes())
        return h.hexdigest()
