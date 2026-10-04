from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def fetch(
    out: Path = typer.Argument(..., help="parquet path, e.g. data/weather/ann_arbor_2025.parquet"),
    start: str = typer.Option("2025-06-01"),
    end: str = typer.Option("2025-09-30"),
    lat: float = typer.Option(42.2808),
    lon: float = typer.Option(-83.7430),
):
    """Fetch hourly archive weather (temp_c, humidity, cloud cover) to a parquet file."""
    from homewatt.cmp03_weather.client import fetch_archive

    df = fetch_archive(lat, lon, date.fromisoformat(start), date.fromisoformat(end))
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    typer.echo(f"{len(df)} hourly rows -> {out} (temp_c {df.temp_c.min():.1f}..{df.temp_c.max():.1f})")


@app.command()
def load(
    file: Path = typer.Argument(..., help="archive parquet from `fetch`"),
    location: str = typer.Option("ann_arbor"),
    forecast_from: str | None = typer.Option(None, help="simulated now (ISO, UTC). Hours from here for 7 days are also written as forecast rows fetched at this time"),
):
    """Write observed rows to the store; optionally a replayed-past 7-day forecast from a simulated now."""
    import pandas as pd

    from homewatt.cmp03_weather.store import write_weather
    from homewatt.spacetime import SpacetimeClient

    c = SpacetimeClient.from_settings()
    df = pd.read_parquet(file)
    now = pd.Timestamp.now(tz="UTC")
    n = write_weather(c, df, location, False, now)
    typer.echo(f"{n} observed rows written for {location}")
    if forecast_from:
        t0 = pd.Timestamp(forecast_from)
        t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0.tz_convert("UTC")
        horizon = df[(df["ts"] >= t0) & (df["ts"] < t0 + pd.Timedelta(days=7))]
        m = write_weather(c, horizon, location, True, t0)
        typer.echo(f"{m} forecast rows written, fetched_at {t0} (replayed past: perfect foresight)")
