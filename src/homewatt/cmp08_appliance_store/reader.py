"""Rollup reads (CMP-11, CMP-12, CMP-13, CMP-15 inputs). Sorted here; SpacetimeDB SQL has no ORDER BY."""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def read_hourly(client, household_id: str, start: datetime, end: datetime, appliance_id: str | None = None) -> pd.DataFrame:
    from homewatt.spacetime import from_us, us

    q = (
        f"SELECT * FROM appliance_hourly WHERE household_id = '{household_id}' "
        f"AND bucket_us >= {us(start)} AND bucket_us < {us(end)}"
    )
    if appliance_id:
        q += f" AND appliance_id = '{appliance_id}'"
    df = client.sql(q)
    if df.empty:
        return df
    df["bucket"] = from_us(df["bucket_us"])
    return df.sort_values(["appliance_id", "source", "model_version", "bucket_us"]).reset_index(drop=True)


def read_daily(client, household_id: str, start: datetime, end: datetime, appliance_id: str | None = None) -> pd.DataFrame:
    from homewatt.spacetime import from_us, us

    q = (
        f"SELECT * FROM appliance_daily WHERE household_id = '{household_id}' "
        f"AND bucket_us >= {us(start)} AND bucket_us < {us(end)}"
    )
    if appliance_id:
        q += f" AND appliance_id = '{appliance_id}'"
    df = client.sql(q)
    if df.empty:
        return df
    df["bucket"] = from_us(df["bucket_us"])
    return df.sort_values(["appliance_id", "source", "model_version", "bucket_us"]).reset_index(drop=True)
