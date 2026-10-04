"""CMP-01 V1 replay (TRS-01-04, TRS-05-06): read a timeline file and feed samples through
IngestionService.submit at N× real time. Timestamps come from the file, never from the clock.

A live sensor source would be another iterator over Sample; it calls the same `submit`."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from homewatt.cmp05_ingest.models import ApplianceSample, Sample
from homewatt.cmp05_ingest.service import IngestionService
from homewatt.schema import NUMERIC_FIELDS, SAMPLE_PERIOD_S

log = logging.getLogger(__name__)


def read_timeline(path: Path, household_id: str | None = None) -> pd.DataFrame:
    """Load a 37-field timeline. Accepts CMP-06 aggregate.parquet (has ts + household_id) or a
    CMP-00 session/negative parquet (has t_s; household_id and an epoch must be supplied via
    `household_id` and the t_s offset is taken from 2025-07-01T00:00Z)."""
    df = pd.read_parquet(path)
    if "ts" not in df.columns:
        if "t_s" not in df.columns:
            raise ValueError(f"{path} has neither ts nor t_s")
        epoch = pd.Timestamp("2025-07-01T00:00:00Z")
        df = df.assign(ts=epoch + pd.to_timedelta(df["t_s"], unit="s"))
    if "household_id" not in df.columns:
        if household_id is None:
            raise ValueError("household_id required for a timeline without one")
        df = df.assign(household_id=household_id)
    missing = [c for c in NUMERIC_FIELDS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing fields {missing}")
    return df[["household_id", "ts", *NUMERIC_FIELDS]]


def iter_samples(df: pd.DataFrame) -> Iterator[Sample]:
    vals = df[list(NUMERIC_FIELDS)].to_numpy(dtype=np.float32)
    ts = df["ts"].dt.to_pydatetime()
    hh = df["household_id"].to_numpy()
    for i in range(len(df)):
        yield Sample(str(hh[i]), ts[i], vals[i])


def run_replay(
    df: pd.DataFrame, service: IngestionService, speed: float = 0.0, log_every: int = 50_000
) -> dict:
    """speed = N means N× real time; 0 means as fast as possible. Returns the counters."""
    period = SAMPLE_PERIOD_S / speed if speed > 0 else 0.0
    t_start = time.monotonic()
    n = 0
    next_due = t_start
    for s in iter_samples(df):
        service.submit(s)
        n += 1
        if period:
            next_due += period
            lag = next_due - time.monotonic()
            if lag > 0:
                time.sleep(lag)
            service.tick()
        if n % log_every == 0:
            log.info("replayed %d samples, counters %s", n, service.counters.as_dict())
    service.flush()
    elapsed = time.monotonic() - t_start
    log.info(
        "replay done: %d samples in %.1f s (%.0f samples/s)",
        n,
        elapsed,
        n / elapsed if elapsed else 0,
    )
    return service.counters.as_dict()


def read_tracks(truth_path: Path, meta_path: Path, period_s: float = 60.0) -> tuple[pd.DataFrame, str]:
    """CMP-06 truth.parquet -> long frame of per-appliance means at `period_s` cadence.
    Returns (frame[household_id, appliance_id, ts, watts], model_version). The hvac and
    baseload tracks are included; the fault marker is not a track."""
    import json

    meta = json.loads(Path(meta_path).read_text())
    truth = pd.read_parquet(truth_path)
    return tracks_from_truth(truth, meta["household_id"], period_s), sim_model_version(meta)


def sim_model_version(meta: dict) -> str:
    """One model_version per base timeline (seed + profile), stable across behaviour
    regenerations, so the simulated feed stays one continuous series (TRS-SYS-02)."""
    return f"cmp06-seed{meta['seed']}-{meta['profile_sha256'][:8]}"


def tracks_from_truth(truth: pd.DataFrame, household_id: str, period_s: float = 60.0) -> pd.DataFrame:
    cols = [c for c in truth.columns if c.endswith("_w")]
    t = truth.set_index("ts")[cols].astype("float64")
    means = t.resample(f"{int(period_s)}s", label="left", closed="left").mean()
    long = means.reset_index().melt(id_vars="ts", var_name="appliance_id", value_name="watts")
    long["appliance_id"] = long["appliance_id"].str.removesuffix("_w")
    long["household_id"] = household_id
    long = long.dropna(subset=["watts"]).sort_values(["appliance_id", "ts"]).reset_index(drop=True)
    return long[["household_id", "appliance_id", "ts", "watts"]]


def run_tracks(df: pd.DataFrame, model_version: str, service: IngestionService, period_s: float = 60.0) -> dict:
    """Feed simulated per-appliance rows (source='sim') through the ingestion service."""
    n = 0
    for r in df.itertuples(index=False):
        service.submit_plug(
            ApplianceSample(r.household_id, r.appliance_id, r.ts.to_pydatetime(), float(r.watts), "sim", model_version, period_s)
        )
        n += 1
    service.flush()
    log.info("tracks done: %d sim rows for %d appliances", n, df["appliance_id"].nunique())
    return service.counters.as_dict()
