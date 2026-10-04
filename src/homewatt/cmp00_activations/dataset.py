"""Loading the Dinar et al. dataset (Sensors 2025, 25, 4601).

Each session folder `MM-DD Nh` holds nine CSVs: eight sub-meters and the aggregate S1P3.
The `time` column is seconds from session start (not wall clock); files within a session start
a few seconds apart and may differ in length, so alignment is by nearest timestamp.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from homewatt.schema import (
    DATASET_AGGREGATE_FILE,
    DATASET_COLUMN_MAP,
    DATASET_FILES,
    NUMERIC_FIELDS,
)

_SESSION_RE = re.compile(r"^(\d{2}-\d{2})\s+\d+h$")


def session_id(folder: Path) -> str:
    m = _SESSION_RE.match(folder.name)
    if not m:
        raise ValueError(f"not a session folder: {folder}")
    return m.group(1)


def list_sessions(root: Path) -> dict[str, Path]:
    """Map session id ('05-12') -> folder, sorted by id."""
    data = root / "data"
    if not data.is_dir():
        raise FileNotFoundError(f"dataset not found at {root}; clone fariddinar/nilm-dataset there")
    out = {session_id(p): p for p in data.iterdir() if p.is_dir() and _SESSION_RE.match(p.name)}
    return dict(sorted(out.items()))


def load_file(path: Path) -> pd.DataFrame:
    """Load one CSV as canonical columns: t_s (int seconds) + the 36 numeric fields (float32)."""
    df = pd.read_csv(path)
    df = df.rename(columns=DATASET_COLUMN_MAP)
    out = pd.DataFrame({"t_s": df["time"].astype(np.int64)})
    for f in NUMERIC_FIELDS:
        out[f] = df[f].astype(np.float32)
    # Drop exact duplicate timestamps (rare) keeping the first; sort by time.
    out = out.drop_duplicates("t_s", keep="first").sort_values("t_s").reset_index(drop=True)
    return out


def load_session(folder: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Return (aggregate, {appliance_type: sub-meter frame}) for one session."""
    agg = load_file(folder / DATASET_AGGREGATE_FILE)
    subs = {app: load_file(folder / fname) for fname, app in DATASET_FILES.items()}
    return agg, subs
