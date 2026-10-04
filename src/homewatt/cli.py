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
from homewatt.cmp04_tariff.cli import app as cmp04_app  # noqa: E402
from homewatt.cmp05_ingest.cli import app as ingest_app  # noqa: E402
from homewatt.cmp06_synth.cli import app as cmp06_app  # noqa: E402
from homewatt.cmp09_nilm.cli import app as cmp09_app  # noqa: E402
from homewatt.cmp11_forecaster.cli import app as cmp11_app  # noqa: E402
from homewatt.cmp12_anomaly.cli import app as cmp12_app  # noqa: E402
from homewatt.cmp13_simulator.cli import app as cmp13_app  # noqa: E402
from homewatt.cmp14_onboarding.cli import app as cmp14_app  # noqa: E402
from homewatt.cmp15_api.cli import app as api_app  # noqa: E402
from homewatt.cmp17_ledger.cli import app as cmp17_app  # noqa: E402
from homewatt.cmp18_verifier.cli import app as cmp18_app  # noqa: E402
from homewatt.cmp20_narrator.cli import app as cmp20_app  # noqa: E402
from homewatt.demo.cli import app as demo_app  # noqa: E402
from homewatt.spacetime_cli import app as db_app  # noqa: E402

app.add_typer(cmp00_app, name="cmp00", help="Activation library and session split")
app.add_typer(cmp03_app, name="cmp03", help="Open-Meteo weather")
app.add_typer(cmp04_app, name="cmp04", help="Tariff table")
app.add_typer(cmp06_app, name="cmp06", help="Synthetic timeline generator")
app.add_typer(cmp11_app, name="cmp11", help="Forecaster")
app.add_typer(cmp13_app, name="cmp13", help="Counterfactual simulator")
app.add_typer(cmp14_app, name="cmp14", help="Onboarding seed")
app.add_typer(cmp17_app, name="cmp17", help="Action ledger: dismiss, week-end close, list")
app.add_typer(cmp09_app, name="cmp09", help="NILM baseline (combinatorial optimisation)")
app.add_typer(cmp12_app, name="cmp12", help="Anomaly detector")
app.add_typer(cmp18_app, name="cmp18", help="Savings verifier and scores")
app.add_typer(cmp20_app, name="cmp20", help="Narrator")
app.add_typer(api_app, name="api", help="Costing API and dashboard server")
app.add_typer(demo_app, name="demo", help="Step 9 demo driver")
app.add_typer(ingest_app, name="ingest", help="CMP-05 ingestion and replay")
app.add_typer(db_app, name="db", help="SpacetimeDB operations (publish, check, sql)")

if __name__ == "__main__":
    app()
