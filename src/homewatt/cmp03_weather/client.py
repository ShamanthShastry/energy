"""Open-Meteo hourly archive and forecast (no key). TRS-03-03: temperature in °C.
Only the pieces CMP-06 needs now; TRS-03-01/02/04 (backfill cadence, is_forecast versioning,
staleness) are completed in build-order step 6 with the DB writer."""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,relative_humidity_2m,cloud_cover"

# Ann Arbor, MI (ZIP 48104). ZIP resolution is CMP-14's job; this is the demo default.
ANN_ARBOR = (42.2808, -83.7430)


def _frame(payload: dict, is_forecast: bool) -> pd.DataFrame:
    h = payload["hourly"]
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(h["time"], utc=True),
            "temp_c": h["temperature_2m"],
            "humidity_pct": h["relative_humidity_2m"],
            "cloud_cover_pct": h["cloud_cover"],
            "is_forecast": is_forecast,
        }
    )
    return df.dropna(subset=["temp_c"]).reset_index(drop=True)


def fetch_archive(
    lat: float, lon: float, start: date, end: date, timeout: float = 30.0
) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": HOURLY,
        "timezone": "UTC",
    }
    r = httpx.get(ARCHIVE_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return _frame(r.json(), is_forecast=False)


def fetch_forecast(lat: float, lon: float, days: int = 7, timeout: float = 30.0) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY,
        "forecast_days": days,
        "timezone": "UTC",
    }
    r = httpx.get(FORECAST_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return _frame(r.json(), is_forecast=True)
