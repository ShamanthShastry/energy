from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def generate(
    profile: Path = typer.Option(..., help="schedule profile YAML (TRS-06-09)"),
    weather: Path = typer.Option(..., help="hourly weather parquet from `homewatt cmp03 fetch`"),
    out: Path = typer.Option(..., help="output directory"),
    days: int = typer.Option(14),
    seed: int = typer.Option(7),
    start: str = typer.Option(
        "2025-07-01T00:00", help="local start, ISO; June-September for the DTE summer gap"
    ),
    fault: Path | None = typer.Option(None, help="fault script YAML (TRS-06-05)"),
    library: Path | None = typer.Option(None, help="data/library (default)"),
    sessions: str = typer.Option("train", help="'train' (default) or comma-separated session ids"),
):
    """Generate a seeded synthetic timeline: aggregate.parquet (37 fields), truth.parquet, meta.json."""
    from homewatt.cmp00_activations.library import ActivationLibrary
    from homewatt.cmp06_synth.fault import Fault
    from homewatt.cmp06_synth.generator import generate as _generate
    from homewatt.cmp06_synth.generator import write_timeline
    from homewatt.cmp06_synth.profile import Profile

    s = get_settings()
    lib = ActivationLibrary(
        library or s.library_dir, None if sessions == "train" else sessions.split(",")
    )
    prof = Profile.load(profile)
    wx = pd.read_parquet(weather)
    f = Fault.load(fault) if fault else None
    tl = _generate(prof, lib, wx, datetime.fromisoformat(start), days, seed, f)
    shas = write_timeline(tl, out)
    typer.echo(
        f"{tl.meta['n_samples']} samples, overlap {tl.meta['overlap_fraction']}, fault samples {tl.meta['fault_samples']}"
    )
    for k, v in shas.items():
        typer.echo(f"  {k}  sha256 {v}")
