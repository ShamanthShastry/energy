from __future__ import annotations

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def run():
    """Verify due accepted actions and recompute success scores at the demo clock's now (TRS-18-06)."""
    from homewatt.clock import now
    from homewatt.cmp04_tariff.model import load_tariff
    from homewatt.cmp18_verifier.verifier import run_week
    from homewatt.spacetime import SpacetimeClient

    s = get_settings()
    c = SpacetimeClient.from_settings()
    verified, scores = run_week(c, s.household_id, now(c, s.household_id), load_tariff(s.tariff_dir / "dte_d1_11.yaml"))
    for v in verified:
        typer.echo(f"{v.appliance_id:13} {v.action_type:22} expected {v.expected_usd:7.2f} verified {v.verified_saving_usd:7.2f} -> {v.status}")
    for r in scores:
        typer.echo(f"score {r['action_type']:22} {r['success_score']:.2f} ({r['verified']} verified / {r['proposed']} proposed)")
