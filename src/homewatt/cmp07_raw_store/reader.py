"""Read side of CMP-07 over the SpacetimeDB SQL endpoint. SpacetimeDB SQL has no ORDER BY, so
results are sorted here. Nothing in this package writes raw_aggregate."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from homewatt.schema import NUMERIC_FIELDS

# The SDK renders camelCase column names as snake_case, so `h1` becomes `h_1` in SQL results.
SQL_COLUMN = {f: (f"h_{f[1:]}" if f.startswith("h") and f[1:].isdigit() else f) for f in NUMERIC_FIELDS}


def read_window(client, household_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Window read for CMP-09: ts + 36 fields, ordered by ts, half-open [start, end)."""
    from homewatt.spacetime import from_us, us

    df = client.sql(
        f"SELECT * FROM raw_aggregate WHERE household_id = '{household_id}' "
        f"AND ts_us >= {us(start)} AND ts_us < {us(end)}"
    )
    if df.empty:
        return pd.DataFrame(columns=["ts", *NUMERIC_FIELDS])
    df = df.sort_values("ts_us").reset_index(drop=True)
    out = pd.DataFrame({"ts": from_us(df["ts_us"])})
    for f in NUMERIC_FIELDS:
        out[f] = df[SQL_COLUMN[f]].astype("float32")
    return out


def read_gaps(client, household_id: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Gap events overlapping [start, end) so CMP-09 can skip gapped spans."""
    from homewatt.spacetime import from_us, us

    df = client.sql(
        f"SELECT gap_start_us, gap_end_us, samples_dropped FROM ingest_log WHERE household_id = '{household_id}' "
        f"AND kind = 'gap' AND gap_end_us >= {us(start)} AND gap_start_us < {us(end)}"
    )
    if df.empty:
        return pd.DataFrame(columns=["gap_start", "gap_end", "samples_dropped"])
    return pd.DataFrame(
        {"gap_start": from_us(df["gap_start_us"]), "gap_end": from_us(df["gap_end_us"]), "samples_dropped": df["samples_dropped"]}
    ).sort_values("gap_start").reset_index(drop=True)


def read_stats(client, household_id: str) -> dict | None:
    df = client.sql(f"SELECT * FROM ingest_stats WHERE household_id = '{household_id}'")
    return df.iloc[0].to_dict() if len(df) else None
