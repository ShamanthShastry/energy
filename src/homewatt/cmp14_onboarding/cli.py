from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def seed(
    profile: Path = typer.Option(Path("config/profiles/demo_household.yaml")),
    zip_code: str = typer.Option("48104", "--zip"),
    tariff_id: str = typer.Option("dte_d1_11"),
    lat: float = typer.Option(42.2808),
    lon: float = typer.Option(-83.7430),
    occupants: int = typer.Option(2),
):
    """Create the household, its appliances (with device bounds for hvac) and the simulated thermostat state."""
    from homewatt.cmp06_synth.profile import Profile
    from homewatt.spacetime import SpacetimeClient

    p = Profile.load(profile)
    c = SpacetimeClient.from_settings()
    c.call("upsert_household", p.household_id, zip_code, lat, lon, tariff_id, occupants, p.local_tz)
    n = 0
    for app_id, s in p.appliances.items():
        c.call("upsert_appliance", p.household_id, app_id, str(s.type), s.label, 0.0, 0.0, 0.0)
        n += 1
    if p.thermostat.enabled:
        tp = p.thermostat
        c.call("upsert_appliance", p.household_id, tp.appliance_id, "hvac", tp.label, tp.min_setpoint_c, tp.max_setpoint_c, tp.max_step_c)
        c.call("init_thermostat_state", p.household_id, tp.appliance_id, tp.setpoint_c, True)
        n += 1
    typer.echo(f"seeded {p.household_id}: {n} appliances")
