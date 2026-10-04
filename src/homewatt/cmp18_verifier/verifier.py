"""Weekly verification of accepted actions and per-action-type success scores.

TRS-18-01/03: verified saving = cost of the forecast that priced the action (forecast_made_at)
minus actual cost, for the action's appliance, over the 7 days after acceptance, both under the
tariff. The window is clipped to that forecast's 168 h horizon; the expected saving is the
priced saving scaled to the hours actually compared.
TRS-18-02: verified when verified saving >= 0.5 x expected saving.
TRS-18-05/07: success score per action type over the trailing 8 weeks, recomputed from the
ledger each week: (verified + 0.5 x accepted-not-yet-verified) / proposed; null below 2 proposals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from homewatt.cmp04_tariff.model import Tariff
from homewatt.cmp08_appliance_store.reader import read_hourly
from homewatt.cmp11_forecaster.pipeline import preferred_hourly
from homewatt.cmp13_simulator.costing import cost
from homewatt.cmp13_simulator.simulator import iso_week_id, previous_week_ids
from homewatt.spacetime import from_us, us

log = logging.getLogger(__name__)

VERIFY_THRESHOLD = 0.5  # TRS-18-02
VERIFY_DAYS = 7
HORIZON_H = 168
SCORE_WEEKS = 8
MIN_PROPOSALS = 2


@dataclass
class Verification:
    action_id: str
    appliance_id: str
    action_type: str
    expected_usd: float
    verified_saving_usd: float
    status: str
    window_hours: int


def verify_one(action: pd.Series, forecast: pd.DataFrame, actual_hourly: pd.Series, tariff: Tariff) -> Verification:
    accepted = from_us(int(action["status_at_us"])).floor("h")
    made = from_us(int(action["forecast_made_at_us"])).floor("h")
    start = max(accepted, made)
    end = min(accepted + pd.Timedelta(days=VERIFY_DAYS), made + pd.Timedelta(hours=HORIZON_H))
    hours = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    base = forecast.set_index("ts")["kwh_p50"].reindex(hours).fillna(0.0)
    act = actual_hourly.reindex(hours).fillna(0.0)
    saving = cost(base, tariff).usd - cost(act, tariff).usd
    expected = float(action["saving_usd"]) * len(hours) / HORIZON_H
    status = "verified" if expected > 0 and saving >= VERIFY_THRESHOLD * expected else "not_verified"
    return Verification(str(action["action_id"]), str(action["appliance_id"]), str(action["action_type"]), expected, saving, status, len(hours))


def due_actions(client, household_id: str, now: pd.Timestamp) -> pd.DataFrame:
    df = client.sql(f"SELECT * FROM action WHERE household_id = '{household_id}' AND status = 'accepted'")
    if df.empty:
        return df
    cutoff = us(now - pd.Timedelta(days=VERIFY_DAYS))
    return df[df["status_at_us"] <= cutoff].reset_index(drop=True)


def verify_due(client, household_id: str, now: pd.Timestamp, tariff: Tariff) -> list[Verification]:
    due = due_actions(client, household_id, now)
    out: list[Verification] = []
    for a in due.itertuples(index=False):
        a = pd.Series(a._asdict())
        made_us = int(a["forecast_made_at_us"])
        fc = client.sql(
            f"SELECT ts_us, kwh_p_50 FROM forecast WHERE household_id = '{household_id}' AND appliance_id = '{a['appliance_id']}' "
            f"AND made_at_us = {made_us}"
        )
        if fc.empty:
            log.warning("no forecast made_at %s for %s; cannot verify (TRS-18-03 forbids a later one)", made_us, a["action_id"])
            continue
        fc = pd.DataFrame({"ts": from_us(fc["ts_us"]), "kwh_p50": fc["kwh_p_50"].astype(float)})
        start = from_us(int(a["status_at_us"])) - pd.Timedelta(hours=1)
        hourly = preferred_hourly(read_hourly(client, household_id, start, start + pd.Timedelta(days=VERIFY_DAYS + 1), a["appliance_id"]))
        actual = hourly.set_index("bucket")["kwh"].astype(float) if len(hourly) else pd.Series(dtype=float)
        v = verify_one(a, fc, actual, tariff)
        client.call("verify_action", v.action_id, float(v.verified_saving_usd), v.status)
        log.info("%s %s: expected %.2f, verified %.2f -> %s", v.appliance_id, v.action_type, v.expected_usd, v.verified_saving_usd, v.status)
        out.append(v)
    return out


def scores(ledger: pd.DataFrame, week_id: str) -> list[dict]:
    """TRS-18-05 over the 8 weeks before week_id. ledger: action rows (any status)."""
    if ledger.empty:
        return []
    weeks = set(previous_week_ids(week_id, SCORE_WEEKS))
    win = ledger[ledger["week_id"].isin(weeks)]
    rows = []
    for at, g in win.groupby("action_type"):
        proposed = len(g)
        verified = int((g["status"] == "verified").sum())
        accepted = int((g["status"] == "accepted").sum())
        score = -1.0 if proposed < MIN_PROPOSALS else (verified + 0.5 * accepted) / proposed
        rows.append({"action_type": at, "proposed": proposed, "accepted": accepted, "verified": verified, "success_score": float(score)})
    return rows


def run_week(client, household_id: str, now: pd.Timestamp, tariff: Tariff) -> tuple[list[Verification], list[dict]]:
    """TRS-18-06: once per week (and on demand). Verify what is due, then recompute scores."""
    verified = verify_due(client, household_id, now, tariff)
    week_id = iso_week_id(now, tariff.timezone)
    ledger = client.sql(f"SELECT action_type, status, week_id FROM action WHERE household_id = '{household_id}'")
    rows = scores(ledger, week_id)
    client.call("write_outcome_scores", household_id, week_id, rows)
    return verified, rows
