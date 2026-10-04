from __future__ import annotations

from pathlib import Path

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    now: str = typer.Option(..., help="simulated now, ISO UTC"),
    tariff: Path = typer.Option(Path("config/tariffs/dte_d1_11.yaml")),
    atl: Path = typer.Option(Path("config/atl.yaml")),
    profile: Path = typer.Option(Path("config/profiles/demo_household.yaml"), help="for the thermostat model parameters"),
    location: str = typer.Option("ann_arbor"),
    household: str | None = typer.Option(None),
):
    """Price every applicable ATL template against the latest forecast and propose the top 3."""
    import pandas as pd

    from homewatt.cmp04_tariff.model import load_tariff
    from homewatt.cmp06_synth.profile import Profile
    from homewatt.cmp13_simulator.atl import load_atl
    from homewatt.cmp13_simulator.pipeline import run as _run
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    c = SpacetimeClient.from_settings()
    tp = Profile.load(profile).thermostat
    batch, all_actions = _run(c, household or s.household_id, load_tariff(tariff), load_atl(atl), location, pd.Timestamp(now), tp)
    typer.echo(f"week batch ({len(batch)}):")
    typer.echo(f"     {'appliance':13} {'action_type':22} {'status':9} {'$/7d':>7} {'$/mo':>7} {'kgCO2':>6}  assumption")
    for r in batch.itertuples():
        typer.echo(f"     {r.appliance_id:13} {r.action_type:22} {r.status:9} {r.saving_usd:7.2f} {r.saving_usd * 30.4375 / 7:7.2f} {r.saving_kg_co_2:6.2f}  {r.assumption_text}")
    typer.echo("--- computed but not surfaced:")
    for a in all_actions:
        if not a.surfaced:
            typer.echo(f"     {a.appliance_id:13} {a.action_type:22} {a.saving_usd:7.2f} {a.saving_usd_month:7.2f}  [{a.not_surfaced_reason}]")
