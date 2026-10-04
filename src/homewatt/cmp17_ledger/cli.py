from __future__ import annotations

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command("close-week")
def close_week(
    now: str = typer.Option(..., help="simulated now, ISO UTC; every week before the one containing it is closed"),
    household: str | None = typer.Option(None),
):
    """TRS-17-06: dismiss (reason 'expired') every action still proposed in a week that has ended."""
    import pandas as pd

    from homewatt.cmp17_ledger.ledger import close_ended_weeks
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    through = close_ended_weeks(SpacetimeClient.from_settings(), household or s.household_id, pd.Timestamp(now), s.local_tz)
    typer.echo(f"closed weeks through {through}")


@app.command()
def dismiss(action_id: str):
    """Dismiss a proposed action (what the Actions tab Dismiss button will call through CMP-15)."""
    from homewatt.cmp17_ledger.ledger import dismiss as _dismiss
    from homewatt.spacetime import SpacetimeClient

    _dismiss(SpacetimeClient.from_settings(), action_id)
    typer.echo(f"dismissed {action_id}")


@app.command("list")
def list_actions(household: str | None = typer.Option(None)):
    """Every action in the ledger with status and reason, newest week first."""
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    df = SpacetimeClient.from_settings().sql(f"SELECT action_id, week_id, appliance_id, action_type, status, status_reason, saving_usd FROM action WHERE household_id = '{household or s.household_id}'")
    if df.empty:
        typer.echo("no actions")
        return
    typer.echo(df.sort_values(["week_id", "saving_usd"], ascending=[False, False]).to_string(index=False))
