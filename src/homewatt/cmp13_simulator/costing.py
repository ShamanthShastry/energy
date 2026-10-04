"""The one costing function (TRS-13-02, TRS-15-01): Σ kWh(ts) × rate(ts). Baseline and
counterfactual are priced by this same function; saving is their difference."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from homewatt.cmp04_tariff.model import Tariff


@dataclass(frozen=True)
class Cost:
    usd: float
    kg_co2: float
    kwh: float


def cost(kwh: pd.Series, tariff: Tariff) -> Cost:
    """kwh: Series indexed by tz-aware hourly UTC timestamps."""
    if len(kwh) == 0:
        return Cost(0.0, 0.0, 0.0)
    r = tariff.rates(kwh.index)
    k = kwh.to_numpy(dtype=float)
    return Cost(float((k * r["usd_per_kwh"].to_numpy()).sum()), float((k * r["kg_co2_per_kwh"].to_numpy()).sum()), float(k.sum()))
