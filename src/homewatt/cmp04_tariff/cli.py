from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def check(path: Path = typer.Argument(..., help="tariff YAML")):
    """Validate coverage (TRS-04-01) and print a few sample rates."""
    import pandas as pd

    from homewatt.cmp04_tariff.model import load_tariff

    t = load_tariff(path)
    typer.echo(f"{t.tariff_id}: {len(t.seasons)} seasons, flat={t.is_flat}, valid_from={t.valid_from}")
    for ts in ("2025-07-08T17:00", "2025-07-08T21:00", "2025-07-12T17:00", "2025-11-04T17:00"):
        local = pd.Timestamp(ts, tz=t.timezone)
        r = t.rate(local.tz_convert("UTC"))
        typer.echo(f"  {local:%a %Y-%m-%d %H:%M} local -> {r.period_name:9} {r.season:11} ${r.usd_per_kwh:.5f}/kWh")


@app.command()
def load(path: Path = typer.Argument(..., help="tariff YAML")):
    """Validate and write the tariff rows to the store (TRS-04-04)."""
    from homewatt.cmp04_tariff.model import load_tariff
    from homewatt.spacetime import SpacetimeClient

    t = load_tariff(path)
    c = SpacetimeClient.from_settings()
    c.call("upsert_tariff", t.period_rows(), t.tariff_id, t.valid_from.isoformat(), float(t.fixed_usd_per_month))
    typer.echo(f"loaded {len(t.period_rows())} periods for {t.tariff_id}")
