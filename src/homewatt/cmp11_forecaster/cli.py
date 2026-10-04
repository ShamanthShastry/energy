from __future__ import annotations

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    now: str = typer.Option(..., help="simulated now, ISO UTC, e.g. 2025-07-15T04:00:00Z"),
    location: str = typer.Option("ann_arbor"),
    household: str | None = typer.Option(None),
    no_lgbm: bool = typer.Option(False, help="seasonal-naive only"),
):
    """Forecast 168 h per appliance from the store and write forecast rows + metrics."""
    import pandas as pd

    from homewatt.cmp11_forecaster.pipeline import run as _run
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    c = SpacetimeClient.from_settings()
    r = _run(c, household or s.household_id, location, pd.Timestamp(now), s.local_tz, use_lgbm=not no_lgbm)
    typer.echo(f"{'appliance':14} {'model':9} {'mae_model':>10} {'mae_naive':>10} {'p50 kWh/7d':>11}")
    for f in r.forecasts:
        mm = f"{f.mae_model:.4f}" if f.mae_model is not None else "-"
        typer.echo(f"{f.appliance_id:14} {f.model_version:9} {mm:>10} {f.mae_naive:10.4f} {f.frame.kwh_p50.sum():11.2f}")
