"""Writes appliance_power rows through the write_appliance_power reducer, which assigns dt_s
and maintains the hourly/daily rollups (see rollup.py and spacetimedb/src/index.ts).
Used by CMP-05 for plug and sim rows and by CMP-09 for NILM rows. TRS-08-02: nilm and sim
rows need a model_version; TRS-08-03: the caller declares the stream's sample period;
TRS-08-06: a new model_version adds rows under its own key."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from homewatt.cmp05_ingest.models import ApplianceSample

BATCH = 2000


class AppliancePowerWriter:
    def __init__(self, client):
        self.client = client

    def write_frame(self, df: pd.DataFrame, source: str, model_version: str = "", period_s: float = 2.0) -> int:
        """df columns: household_id, appliance_id, ts, watts[, on_prob]. Returns rows sent."""
        from homewatt.spacetime import us_array

        if source not in ("plug", "nilm", "sim"):
            raise ValueError(f"bad source '{source}'")
        if source != "plug" and not model_version:
            raise ValueError("TRS-08-02: nilm and sim rows require a non-empty model_version")
        if source == "plug" and model_version:
            raise ValueError("plug rows carry no model_version")
        if df.empty:
            return 0
        df = df.sort_values(["household_id", "appliance_id", "ts"])
        ts_us = us_array(df["ts"])
        on_prob = df["on_prob"].fillna(-1.0).to_numpy() if "on_prob" in df else [-1.0] * len(df)
        rows = [
            {"household_id": h, "appliance_id": a, "ts_us": int(t), "watts": float(w), "on_prob": float(p)}
            for h, a, t, w, p in zip(df["household_id"], df["appliance_id"], ts_us, df["watts"], on_prob, strict=True)
        ]
        for i in range(0, len(rows), BATCH):
            self.client.call("write_appliance_power", rows[i : i + BATCH], source, model_version, float(period_s))
        return len(rows)

    def write_samples(self, rows: list[ApplianceSample]) -> int:
        groups: dict[tuple[str, str, float], list[ApplianceSample]] = defaultdict(list)
        for r in rows:
            groups[(r.source, r.model_version, r.period_s)].append(r)
        n = 0
        for (source, mv, period), rs in groups.items():
            df = pd.DataFrame(
                {
                    "household_id": [r.household_id for r in rs],
                    "appliance_id": [r.appliance_id for r in rs],
                    "ts": pd.to_datetime([r.ts for r in rs], utc=True),
                    "watts": [r.watts for r in rs],
                }
            )
            n += self.write_frame(df, source=source, model_version=mv, period_s=period)
        return n

    def write_plug(self, rows: list[ApplianceSample]) -> int:
        return self.write_samples(rows)
