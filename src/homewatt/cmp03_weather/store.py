"""CMP-03 store side: write observed/forecast rows, read them back (TRS-03-02, TRS-03-04).

Demo note: the timeline is a replayed past, so the "forecast" for the horizon is the archive
value for those hours, flagged is_forecast=true with fetched_at = the simulated now. That is
perfect foresight and is labelled as such in meta; a live deployment fetches Open-Meteo's real
7-day forecast instead (fetch_forecast)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from homewatt.spacetime import from_us, us, us_array

MAX_FORECAST_AGE = timedelta(hours=24)  # TRS-03-04


def write_weather(client, df: pd.DataFrame, location_id: str, is_forecast: bool, fetched_at: datetime, batch: int = 2000) -> int:
    ts_us = us_array(df["ts"])
    rows = [
        {"ts_us": int(t), "temp_c": float(a), "humidity_pct": float(b) if pd.notna(b) else -1.0, "cloud_cover_pct": float(c) if pd.notna(c) else -1.0}
        for t, a, b, c in zip(ts_us, df["temp_c"], df.get("humidity_pct", pd.Series([None] * len(df))), df.get("cloud_cover_pct", pd.Series([None] * len(df))), strict=True)
    ]
    for i in range(0, len(rows), batch):
        client.call("write_weather", rows[i : i + batch], location_id, bool(is_forecast), us(fetched_at))
    return len(rows)


def read_weather(client, location_id: str, start: datetime, end: datetime, is_forecast: bool) -> pd.DataFrame:
    """Latest fetched_at per hour wins. Columns ts, temp_c, humidity_pct, cloud_cover_pct, fetched_at."""
    df = client.sql(
        f"SELECT * FROM weather WHERE location_id = '{location_id}' AND ts_us >= {us(start)} AND ts_us < {us(end)} "
        f"AND is_forecast = {'true' if is_forecast else 'false'}"
    )
    if df.empty:
        return pd.DataFrame(columns=["ts", "temp_c", "humidity_pct", "cloud_cover_pct", "fetched_at"])
    df = df.sort_values(["ts_us", "fetched_at_us"]).drop_duplicates("ts_us", keep="last")
    return pd.DataFrame({
        "ts": from_us(df["ts_us"]), "temp_c": df["temp_c"].astype(float), "humidity_pct": df["humidity_pct"],
        "cloud_cover_pct": df["cloud_cover_pct"], "fetched_at": from_us(df["fetched_at_us"]),
    }).reset_index(drop=True)


def forecast_age(df: pd.DataFrame, now: datetime) -> timedelta | None:
    if df.empty:
        return None
    return pd.Timestamp(now) - df["fetched_at"].max()
