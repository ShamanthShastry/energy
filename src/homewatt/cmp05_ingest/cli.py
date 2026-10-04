from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def replay(
    file: Path = typer.Argument(
        ..., help="aggregate.parquet from CMP-06, or a CMP-00 session/negative parquet"
    ),
    speed: float = typer.Option(0.0, help="N× real time; 0 = as fast as possible"),
    sink: str = typer.Option("spacetime", help="spacetime | memory"),
    household_id: str | None = typer.Option(None, help="required for files without household_id"),
):
    """Replay a timeline through the CMP-05 ingestion interface (TRS-05-06)."""
    from homewatt.cmp05_ingest.replay import read_timeline, run_replay
    from homewatt.cmp05_ingest.service import IngestionService
    from homewatt.cmp05_ingest.sinks import MemorySink, SpacetimeSink

    df = read_timeline(file, household_id)
    s = MemorySink() if sink == "memory" else SpacetimeSink()
    svc = IngestionService(s)
    counters = run_replay(df, svc, speed)
    if isinstance(s, SpacetimeSink):
        # TRS-07-03: the store counts duplicates; reconcile before closing.
        for hh in sorted(s.households):
            st = s.stats(hh)
            if st:
                counters["store_accepted"] = int(st["accepted"])
                counters["store_duplicates"] = int(st["duplicates"])
    svc.close()
    typer.echo(json.dumps(counters, indent=2))
    if sink == "memory":
        typer.echo(f"memory sink holds {len(s.rows)} rows, {len(s.gaps)} gap events")


@app.command("replay-tracks")
def replay_tracks(
    truth: Path = typer.Argument(..., help="truth.parquet from CMP-06"),
    meta: Path | None = typer.Option(None, help="meta.json next to it (default)"),
    period: float = typer.Option(60.0, help="cadence of the simulated feed in seconds"),
    sink: str = typer.Option("spacetime", help="spacetime | memory"),
):
    """Feed the CMP-06 ground-truth tracks as source='sim' (simulated feed, TRS-SYS-02 v0.5)."""
    from homewatt.cmp05_ingest.replay import read_tracks, run_tracks
    from homewatt.cmp05_ingest.service import IngestionService
    from homewatt.cmp05_ingest.sinks import MemorySink, SpacetimeSink

    df, model_version = read_tracks(truth, meta or truth.with_name("meta.json"), period)
    typer.echo(f"{len(df)} rows, {df['appliance_id'].nunique()} appliances, model_version {model_version}")
    s = MemorySink() if sink == "memory" else SpacetimeSink()
    svc = IngestionService(s)
    counters = run_tracks(df, model_version, svc, period)
    svc.close()
    typer.echo(json.dumps({k: v for k, v in counters.items() if k.startswith("plug")}, indent=2))
