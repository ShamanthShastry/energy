from __future__ import annotations

import json
from datetime import date

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(day: str = typer.Option(..., help="local date YYYY-MM-DD")):
    """Compute one day's features and raise/close alerts (TRS-12-01..06)."""
    from homewatt.cmp12_anomaly.detector import run_day
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    for dcs in run_day(SpacetimeClient.from_settings(), s.household_id, date.fromisoformat(day), s.local_tz):
        typer.echo(json.dumps(dcs, default=str))
