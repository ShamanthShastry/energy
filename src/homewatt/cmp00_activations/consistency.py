"""TRS-00-03: a session is excluded when the sum of its appliance files differs from its
aggregate by more than 10% of the aggregate mean over the session.

The ratio is computed on the files as recorded (mean watts of each sub-meter file summed,
divided by mean watts of the aggregate file). Measured 2026-10-03: every session lands at
0.96-1.00 except 05-21 at 1.18, where six of eight sub-meters stop after ~4 minutes while the
aggregate runs for ~3 h. Per-appliance coverage is recorded alongside so that cause is visible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

CONSISTENCY_TOLERANCE = 0.10


@dataclass
class SessionConsistency:
    session: str
    aggregate_mean_w: float
    appliance_sum_mean_w: float
    ratio: float
    consistent: bool
    aggregate_rows: int
    coverage: dict[str, float] = field(default_factory=dict)  # sub-meter span / aggregate span
    reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def check_session(
    session: str,
    agg: pd.DataFrame,
    subs: dict[str, pd.DataFrame],
    tol: float = CONSISTENCY_TOLERANCE,
) -> SessionConsistency:
    agg_mean = float(agg["p_active_w"].mean())
    app_sum = float(sum(s["p_active_w"].mean() for s in subs.values()))
    ratio = app_sum / agg_mean if agg_mean > 0 else float("inf")
    consistent = abs(app_sum - agg_mean) <= tol * agg_mean
    agg_span = float(agg["t_s"].iloc[-1] - agg["t_s"].iloc[0]) or 1.0
    coverage = {
        app: round(float(min(1.0, (s["t_s"].iloc[-1] - s["t_s"].iloc[0]) / agg_span)), 3)
        for app, s in subs.items()
    }
    reason = None
    if not consistent:
        short = [a for a, c in coverage.items() if c < 0.5]
        reason = f"appliance sum / aggregate = {ratio:.2f}, outside 1±{tol:.2f}"
        if short:
            reason += f"; sub-meters covering < 50% of the session: {', '.join(short)}"
    return SessionConsistency(
        session, agg_mean, app_sum, ratio, consistent, len(agg), coverage, reason
    )
