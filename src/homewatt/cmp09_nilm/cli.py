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


@app.command()
def fit(
    timeline: str = typer.Option("data/synthetic/demo/timeline", help="synthetic timeline (aggregate + truth) for the hvac state"),
    learn_days: int = typer.Option(14, help="hvac state learned from the first N days; scored on the rest (time-ordered)"),
    store: bool = typer.Option(True, help="write held-out metrics to model_metric (TRS-09-05)"),
):
    """Fit the deployed splitter co-v2 (OI-13) and save it to data/models/co-v2.json."""
    import pandas as pd

    from homewatt.cmp00_activations.split import read_split
    from homewatt.cmp09_nilm.co import build_deployed, evaluate_deployed
    from homewatt.cmp09_nilm.runner import fit_provenance, model_path, save_model
    from homewatt.config import REPO_ROOT

    s = get_settings()
    tdir = REPO_ROOT / timeline
    truth = pd.read_parquet(tdir / "truth.parquet", columns=["ts", "hvac_w"])
    cut = truth["ts"].min() + pd.Timedelta(days=learn_days)
    model = build_deployed(s.library_dir, truth.loc[truth["ts"] < cut, "hvac_w"].to_numpy())
    agg = pd.read_parquet(tdir / "aggregate.parquet")
    held = agg[agg["ts"] >= cut].merge(truth[truth["ts"] >= cut], on="ts")
    res = evaluate_deployed(s.library_dir, model, held)
    table = res.groupby(["appliance", "synthetic"])[["mae_w", "f1_10w", "energy_ratio"]].mean()
    typer.echo(table.round(3).to_string())
    save_model(model, model_path(), fit_provenance(s.library_dir, f"{timeline} days 1-{learn_days}"))
    typer.echo(f"\nsaved {model_path()}")
    if store:
        from homewatt.spacetime import SpacetimeClient

        split = read_split(s.library_dir / "split.json")
        rows = []
        for (app_type, synthetic), r in table.iterrows():
            for metric in ("mae_w", "f1_10w", "energy_ratio"):
                v = float(r[metric])
                rows.append({"model_version": model.version, "component": "cmp09_nilm", "appliance_type": str(app_type), "metric": metric,
                             "value": v if v == v else -1.0, "synthetic": bool(synthetic),
                             "eval_sessions": f"synthetic days {learn_days + 1}+" if synthetic else ",".join(split["test"])})
        SpacetimeClient.from_settings().call("write_model_metrics", rows)
        typer.echo(f"wrote {len(rows)} metric rows")


@app.command()
def run(
    start: str = typer.Option(..., help="local date, inclusive, e.g. 2025-06-30"),
    end: str = typer.Option(..., help="local date, exclusive"),
    household: str = typer.Option("hh-demo"),
    tz: str = typer.Option("America/Detroit"),
):
    """Run co-v2 on stored raw data one local day at a time and write 60 s nilm rows (OI-13)."""
    import json

    import pandas as pd

    from homewatt.cmp09_nilm.runner import load_model, run_day
    from homewatt.spacetime import SpacetimeClient

    c = SpacetimeClient.from_settings()
    model = load_model()
    for day in pd.date_range(pd.Timestamp(start, tz=tz), pd.Timestamp(end, tz=tz), freq="D", inclusive="left"):
        rep = run_day(c, household, day.tz_convert("UTC"), (day + pd.Timedelta(days=1)).tz_convert("UTC"), model)
        typer.echo(json.dumps({"day": str(day.date()), **rep}))
