from __future__ import annotations

import typer

from homewatt.config import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def evaluate(store: bool = typer.Option(True, help="write held-out metrics to model_metric (TRS-09-05)")):
    """Score the CO baseline with and without harmonics on the 3 held-out real sessions."""
    import pandas as pd

    from homewatt.cmp00_activations.split import read_split
    from homewatt.cmp09_nilm.co import evaluate as _eval
    from homewatt.cmp09_nilm.co import summarise

    s = get_settings()
    split = read_split(s.library_dir / "split.json")
    tables = {}
    for h in (False, True):
        res, model = _eval(s.library_dir, h)
        tables[model.version] = summarise(res)
    both = pd.concat(tables, axis=1)
    typer.echo(f"held-out sessions {split['test']} (real data)\n")
    typer.echo(both.round(3).to_string())
    if store:
        from homewatt.spacetime import SpacetimeClient

        rows = []
        for version, t in tables.items():
            for app_type, r in t.iterrows():
                for metric in ("mae_w", "f1_10w", "energy_ratio"):
                    v = float(r[metric])
                    rows.append({"model_version": version, "component": "cmp09_nilm", "appliance_type": app_type, "metric": metric,
                                 "value": v if v == v else -1.0, "synthetic": False, "eval_sessions": ",".join(split["test"])})
        SpacetimeClient.from_settings().call("write_model_metrics", rows)
        typer.echo(f"\nwrote {len(rows)} metric rows")
