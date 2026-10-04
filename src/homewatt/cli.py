"""`homewatt` command line. Sub-apps per component."""

from __future__ import annotations

import logging

import typer

app = typer.Typer(no_args_is_help=True, help="HomeWatt (TRS-HOMEWATT-001)")


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


from homewatt.cmp00_activations.cli import app as cmp00_app  # noqa: E402
from homewatt.cmp03_weather.cli import app as cmp03_app  # noqa: E402
from homewatt.cmp05_ingest.cli import app as ingest_app  # noqa: E402
from homewatt.cmp06_synth.cli import app as cmp06_app  # noqa: E402
from homewatt.spacetime_cli import app as db_app  # noqa: E402

app.add_typer(cmp00_app, name="cmp00", help="Activation library and session split")
app.add_typer(cmp03_app, name="cmp03", help="Open-Meteo weather")
app.add_typer(cmp06_app, name="cmp06", help="Synthetic timeline generator")
app.add_typer(ingest_app, name="ingest", help="CMP-05 ingestion and replay")
app.add_typer(db_app, name="db", help="SpacetimeDB operations (publish, check, sql)")

if __name__ == "__main__":
    app()
