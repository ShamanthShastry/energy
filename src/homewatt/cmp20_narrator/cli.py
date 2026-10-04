from __future__ import annotations

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def run():
    """Narrate this week's actions whose inputs changed (TRS-20-06)."""
    from homewatt.clock import now
    from homewatt.cmp13_simulator.simulator import iso_week_id
    from homewatt.cmp20_narrator.narrator import default_backend
    from homewatt.cmp20_narrator.narrator import run as _run
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    c = SpacetimeClient.from_settings()
    week = iso_week_id(now(c, s.household_id), s.local_tz)
    for st in _run(c, s.household_id, week, default_backend()):
        typer.echo(f"{'narrated  ' if st.narrated else 'fallback  '} {st.text}" + (f"   [{st.reason}]" if st.reason else ""))
