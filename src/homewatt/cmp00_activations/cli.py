from __future__ import annotations

import json
from pathlib import Path

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def build(
    dataset: Path | None = typer.Option(None, help="path to the cloned nilm-dataset repo"),
    out: Path | None = typer.Option(None, help="library output dir (default data/library)"),
    force_split: bool = typer.Option(
        False, help="overwrite split.json (TRS-00-02 forbids re-splitting; demo reset only)"
    ),
):
    """Extract activations, write split.json once, manifest, aligned sessions, negative cases."""
    from homewatt.cmp00_activations.library import build_library

    s = get_settings()
    manifest = build_library(dataset or s.dataset_root, out or s.library_dir, force_split)
    typer.echo(
        json.dumps(
            {a: v["activations_total"] for a, v in manifest["per_appliance"].items()}, indent=2
        )
    )
    typer.echo(f"excluded: {manifest['excluded']}")


@app.command()
def summary(out: Path | None = typer.Option(None)):
    """Print per-appliance activation counts and flags from manifest.json."""
    s = get_settings()
    m = json.loads(((out or s.library_dir) / "manifest.json").read_text())
    typer.echo(f"{'appliance':14} {'train':>6} {'test':>6} {'on-frac':>8}  flag")
    for a, v in m["per_appliance"].items():
        typer.echo(
            f"{a:14} {v['activations_train']:6d} {v['activations_test']:6d} {v['on_time_fraction_mean']:8.3f}  {'LOW' if v['flag_low_activations'] else ''}"
        )
    typer.echo(f"excluded: {m['excluded']}")
