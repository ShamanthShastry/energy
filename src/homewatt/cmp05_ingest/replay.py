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

from homewatt.cmp05_ingest.models import Sample
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
