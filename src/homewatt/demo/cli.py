from __future__ import annotations

import json
import subprocess

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def reset(wipe: bool = typer.Option(False, "--wipe", help="required: deletes ALL data in the configured SpacetimeDB database")):
    """Wipe the demo database (republish with --delete-data) and the local demo state. Demo reset only."""
    from homewatt.config import get_settings
    from homewatt.demo.driver import DEMO_DIR

    if not wipe:
        typer.echo("refusing without --wipe: this deletes every row in the database")
        raise typer.Exit(2)
    s = get_settings()
    cmd = ["spacetime", "publish", s.spacetime_database, "--delete-data=always", "--yes", "--module-path", str(s.spacetime_module_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        typer.echo("publish failed (output withheld: it can contain the auth token)")
        raise typer.Exit(r.returncode)
    import shutil

    shutil.rmtree(DEMO_DIR, ignore_errors=True)
    typer.echo("database wiped and republished; demo state cleared")


@app.command()
def init(
    start: str = typer.Option("2025-06-30T00:00", help="local start (a Monday keeps weeks aligned)"),
    days: int = typer.Option(28),
    seed: int = typer.Option(7),
):
    """Create the demo state, generate the base timeline, seed household, tariff, weather, clock."""
    import pandas as pd

    from homewatt.clock import set_now
    from homewatt.demo.driver import DemoState, _tz, ensure_timeline
    from homewatt.demo.driver import seed as _seed
    from homewatt.spacetime import SpacetimeClient

    c = SpacetimeClient.from_settings()
    st = DemoState(start_local=start, days=days, seed=seed)
    st.save()
    _seed(c, st)
    ensure_timeline(c, st)
    set_now(c, st.household_id, pd.Timestamp(start, tz=_tz(st)).tz_convert("UTC"))
    typer.echo(f"demo ready: {days} days from {start} local, seed {seed}")


@app.command()
def advance(to: str = typer.Option(..., help="local date-time to replay up to, e.g. 2025-07-14 (exclusive)")):
    """Replay whole days up to `to`, running the daily detector and Monday weekly jobs."""
    from homewatt.demo.driver import advance as _advance
    from homewatt.spacetime import SpacetimeClient

    for rep in _advance(SpacetimeClient.from_settings(), to):
        line = {"day": rep["day"]}
        if rep["anomaly"]:
            line["anomaly"] = rep["anomaly"]
        if "weekly" in rep:
            line["weekly"] = rep["weekly"]
        typer.echo(json.dumps(line, default=str))


@app.command()
def status():
    """Where the demo clock is and what the timeline holds."""
    from homewatt.demo.driver import DemoState

    st = DemoState.load()
    typer.echo(json.dumps({k: v for k, v in st.__dict__.items() if k != "history"}, indent=2))
    for h in st.history[-5:]:
        typer.echo(f"  {h}")
