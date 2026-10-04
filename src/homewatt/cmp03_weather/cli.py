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
    typer.echo(
        f"{len(df)} hourly rows -> {out} (temp_c {df.temp_c.min():.1f}..{df.temp_c.max():.1f})"
    )
