"""Store-facing CMP-13 run: gather the household context, price, rank, propose (TRS-13-08/11)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import pandas as pd

from homewatt.cmp03_weather.store import read_weather
from homewatt.cmp04_tariff.model import Tariff
from homewatt.cmp06_synth.profile import ThermostatParams
from homewatt.cmp11_forecaster.pipeline import read_latest_forecast
from homewatt.cmp13_simulator.atl import ATL
from homewatt.cmp13_simulator.simulator import (
    ApplianceInfo,
    Household,
    PricedAction,
    active_suppressions,
    iso_week_id,
    price_all,
    rank,
    suppressed_action_types,
)
from homewatt.spacetime import from_us, us

log = logging.getLogger(__name__)


def load_household(client, household_id: str, week_id: str, thermostat: ThermostatParams | None) -> Household:
    apps = client.sql(f"SELECT * FROM appliance WHERE household_id = '{household_id}'")
    infos = [ApplianceInfo(r.appliance_id, r.type, r.label) for r in apps.itertuples()]
    alerts = client.sql(f"SELECT appliance_id FROM alert WHERE household_id = '{household_id}' AND closed_at_us = 0")
    state = client.sql(f"SELECT * FROM thermostat_state WHERE household_id = '{household_id}'")
    bounds, setpoint, step = None, None, None
    if len(state):
        setpoint = float(state.iloc[0]["current_setpoint_c"])
        hv = apps[apps["type"] == "hvac"]
        if len(hv):
            bounds = (float(hv.iloc[0]["min_setpoint_c"]), float(hv.iloc[0]["max_setpoint_c"]))
            step = float(hv.iloc[0]["max_step_c"]) or None
    scores_df = client.sql(f"SELECT * FROM outcome_score WHERE household_id = '{household_id}'")
    scores: dict[str, float | None] = {}
    if len(scores_df):
        latest = scores_df.sort_values("week_id").drop_duplicates("action_type", keep="last")
        scores = {r.action_type: (None if r.success_score < 0 else float(r.success_score)) for r in latest.itertuples()}
    hist = client.sql(f"SELECT action_type, status, week_id FROM action WHERE household_id = '{household_id}'")
    first_week = hist.empty or (hist["week_id"] == week_id).all()
    dismissed: dict[str, list[str]] = {}
    for r in hist[hist["status"] == "dismissed"].itertuples():
        dismissed.setdefault(r.action_type, []).append(r.week_id)
    new = suppressed_action_types(dismissed, week_id)
    for at, (frm, until) in new.items():
        client.call("record_suppression", household_id, at, frm, until, "dismissed or not taken 3 consecutive weeks (TRS-13-10)")
    recs = client.sql(f"SELECT action_type, from_week_id, until_week_id FROM action_suppression WHERE household_id = '{household_id}'")
    records = [(r.action_type, r.from_week_id, r.until_week_id) for r in recs.itertuples()] if len(recs) else []
    suppressed = active_suppressions(records, week_id) | set(new)
    return Household(household_id, infos, week_id, first_week, scores, set(alerts["appliance_id"]) if len(alerts) else set(),
                     thermostat, setpoint, bounds, step, dismissed, suppressed)


def run(client, household_id: str, tariff: Tariff, atl: ATL, location_id: str, now: datetime,
        thermostat: ThermostatParams | None = None) -> tuple[pd.DataFrame, list[PricedAction]]:
    """Price, rank, and hand every candidate to propose_actions, which keeps the week's batch
    stable (TRS-13-08) and closes earlier weeks (TRS-17-06). Returns (this week's batch from
    the store, all priced actions)."""
    fc, made_at = read_latest_forecast(client, household_id)
    if made_at is None:
        raise RuntimeError("no forecast in the store; run `homewatt cmp11 run` first")
    week_id = iso_week_id(pd.Timestamp(now), tariff.timezone)
    hh = load_household(client, household_id, week_id, thermostat)
    wx = read_weather(client, location_id, fc["ts"].min().to_pydatetime(), fc["ts"].max().to_pydatetime() + pd.Timedelta(hours=1), is_forecast=True)
    weather = wx.set_index("ts")["temp_c"] if len(wx) else None
    all_actions = price_all(atl, hh, fc, tariff, made_at, weather)
    ordered = rank(all_actions, limit=len(all_actions)) + [a for a in all_actions if not a.surfaced]
    rows = [
        {
            "action_id": str(uuid.uuid4()), "household_id": a.household_id, "appliance_id": a.appliance_id,
            "action_type": a.action_type, "params_json": _json(a.params | {"horizon_days": a.horizon_days}),
            "baseline_usd": a.baseline.usd, "counterfactual_usd": a.counterfactual.usd, "saving_usd": a.saving_usd,
            "saving_kg_co_2": a.saving_kg_co2, "assumption_text": a.assumption_text, "forecast_made_at_us": us(a.forecast_made_at),
            "week_id": week_id, "success_score": -1.0 if a.success_score is None else float(a.success_score),
            "surfaced": bool(a.surfaced),
        }
        for a in ordered
    ]
    client.call("propose_actions", rows, household_id, week_id)
    batch = read_week(client, household_id, week_id)
    log.info("week %s batch for %s: %d actions (first_week=%s)", week_id, household_id, len(batch), hh.first_week)
    return batch, all_actions


def _json(d: dict) -> str:
    import json

    return json.dumps(d, sort_keys=True, default=float)


def read_week(client, household_id: str, week_id: str) -> pd.DataFrame:
    """Every action issued in week_id, any status, ordered by saving."""
    df = client.sql(f"SELECT * FROM action WHERE household_id = '{household_id}' AND week_id = '{week_id}'")
    if df.empty:
        return df
    return df.sort_values("saving_usd", ascending=False).reset_index(drop=True)


def read_open_actions(client, household_id: str) -> pd.DataFrame:
    df = client.sql(f"SELECT * FROM action WHERE household_id = '{household_id}' AND status = 'proposed'")
    if df.empty:
        return df
    df["forecast_made_at"] = from_us(df["forecast_made_at_us"])
    return df.sort_values("saving_usd", ascending=False).reset_index(drop=True)
