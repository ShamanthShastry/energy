from __future__ import annotations

import subprocess

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def check():
    """Connect with the owner token and list tables plus ingest stats."""
    from homewatt.spacetime import SpacetimeClient

    c = SpacetimeClient.from_settings()
    typer.echo(f"database: {c.database} @ {c.host}")
    typer.echo(c.sql("SELECT * FROM ingest_stats").to_string(index=False))
    typer.echo(c.sql("SELECT * FROM household").to_string(index=False))


@app.command()
def sql(query: str):
    """Run a SQL statement with the owner token (SELECT; no ORDER BY / GROUP BY in SpacetimeDB)."""
    from homewatt.spacetime import SpacetimeClient

    typer.echo(SpacetimeClient.from_settings().sql(query).to_string(index=False))


@app.command()
def publish(delete_data: bool = typer.Option(False, help="wipe the database and re-run init (demo reset only)")):
    """Build and publish spacetimedb/ to the configured database (uses the spacetime CLI login)."""
    s = get_settings()
    cmd = ["spacetime", "publish", s.spacetime_database, "--yes", "--module-path", str(s.spacetime_module_dir)]
    if delete_data:
        cmd.append("--delete-data=always")
    typer.echo(" ".join(cmd))
    raise typer.Exit(subprocess.run(cmd).returncode)
