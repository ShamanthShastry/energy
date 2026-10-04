"""Price every applicable template, search declared parameters (TRS-13-12), apply the floor
(TRS-13-04), rank by saving × (0.5 + success_score) (TRS-13-09/13), keep 3 (TRS-13-06)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from homewatt.cmp04_tariff.model import Tariff
from homewatt.cmp06_synth.profile import ThermostatParams
from homewatt.cmp13_simulator import shapes
from homewatt.cmp13_simulator.atl import ATL, Template
from homewatt.cmp13_simulator.costing import Cost, cost

MONTHLY_FLOOR_USD = 1.0  # TRS-13-04
DAYS_PER_MONTH = 30.4375
MAX_ACTIONS = 3  # TRS-13-06
NEUTRAL_SCORE = 0.5  # TRS-13-09 null score
SUPPRESS_AFTER_DISMISSALS = 3  # TRS-13-10
SUPPRESS_WEEKS = 4


@dataclass(frozen=True)
class ApplianceInfo:
    appliance_id: str
    type: str
    label: str


@dataclass
class Household:
    household_id: str
    appliances: list[ApplianceInfo]
    week_id: str
    first_week: bool = True  # TRS-13-13 cold start
    success_scores: dict[str, float | None] = field(default_factory=dict)  # by action_type
    open_alert_appliances: set[str] = field(default_factory=set)
    thermostat: ThermostatParams | None = None
    current_setpoint_c: float | None = None
    device_bounds: tuple[float, float] | None = None  # (min_setpoint_c, max_setpoint_c)
    max_step_c: float | None = None  # TRS-19-02 step limit, also a CMP-14 device bound (Annex A.3)
    dismissed_weeks: dict[str, list[str]] = field(default_factory=dict)  # action_type -> week_ids
    suppressed: set[str] = field(default_factory=set)  # action_types currently suppressed


@dataclass
class PricedAction:
    household_id: str
    appliance_id: str
    action_type: str
    params: dict
    baseline: Cost
    counterfactual: Cost
    saving_usd: float  # over the forecast horizon (7 days)
    saving_kg_co2: float
    assumption_text: str
    forecast_made_at: datetime
    horizon_days: float
    surfaced: bool
    not_surfaced_reason: str | None
    success_score: float | None
    rank_score: float
    actuator: str | None

    @property
    def saving_usd_month(self) -> float:
        return self.saving_usd * DAYS_PER_MONTH / self.horizon_days


def _horizon_days(index: pd.DatetimeIndex) -> float:
    return max(1.0, len(index) / 24.0)


def _price(template: Template, app: ApplianceInfo, kwh: pd.Series, tariff: Tariff, hh: Household,
           weather: pd.Series | None, params: dict) -> tuple[pd.Series, dict] | None:
    """Return (counterfactual series, params used) or None when not evaluable."""
    p = dict(params)
    if template.shape == "shift":
        if p.get("to") == "pre_peak_2h":
            win = next((w for w in (tariff.peak_window(d) for d in pd.DatetimeIndex(kwh.index).tz_convert(tariff.tz).date) if w), None)
            if win is None:
                return None
            p["peak_start"], p["peak_end"] = win
            return shapes.shift(kwh, tariff, to="pre_peak_2h"), p
        return shapes.shift(kwh, tariff, to_hour=int(p["to_hour"])), p
    if template.shape == "trim":
        return shapes.trim(kwh, p["factor"]), p
    if template.shape == "maintenance":
        return shapes.maintenance(kwh, p["factor"]), p
    if template.shape == "setpoint":
        if hh.thermostat is None or hh.current_setpoint_c is None or weather is None:
            return None
        delta = float(p["delta_c"]) * float(p.get("sign", 1))
        target = hh.current_setpoint_c + delta
        if hh.device_bounds is not None and not (hh.device_bounds[0] <= target <= hh.device_bounds[1]):
            return None  # A.3: a delta that leaves the bounds is not evaluated
        if hh.max_step_c is not None and abs(delta) > hh.max_step_c + 1e-9:
            return None  # A.3: nor one the device cannot apply in a single action (TRS-19-02)
        factor = shapes.setpoint_factor(weather, hh.thermostat, hh.current_setpoint_c, delta)
        p["setpoint_factor"] = round(factor, 4)
        p["target_setpoint_c"] = target
        return shapes.setpoint(kwh, factor), p
    raise ValueError(template.shape)


def price_all(atl: ATL, hh: Household, forecast: pd.DataFrame, tariff: Tariff, made_at: datetime,
              weather: pd.Series | None = None) -> list[PricedAction]:
    """forecast: columns appliance_id, ts (UTC hourly), kwh_p50. weather: temp_c indexed by the
    same hourly ts (forecast values, for the setpoint shape). Returns every computed action,
    surfaced or not, unranked."""
    out: list[PricedAction] = []
    by_app = {a: g.set_index("ts")["kwh_p50"].sort_index() for a, g in forecast.groupby("appliance_id")}
    for template in atl.active:
        if template.action_type in hh.suppressed:
            continue
        for app in hh.appliances:
            if app.type not in template.applies_to or app.appliance_id not in by_app:
                continue
            if template.requires_alert and app.appliance_id not in hh.open_alert_appliances:
                continue
            kwh = by_app[app.appliance_id]
            base = cost(kwh, tariff)
            horizon = _horizon_days(kwh.index)
            if template.requires_tou and tariff.is_flat:
                # TRS-13-05 / TRS-04-02: computed with zero saving, never surfaced
                out.append(PricedAction(hh.household_id, app.appliance_id, template.action_type, dict(template.params),
                                        base, base, 0.0, 0.0, _assume(template, app, template.params), made_at, horizon,
                                        False, "flat_tariff", None, 0.0, template.actuator))
                continue
            candidates = [dict(template.params)]
            if template.search is not None:
                candidates = [dict(template.params, **{template.search.name: v}) for v in template.search.values()]
            best: tuple[float, pd.Series, dict] | None = None
            for cand in candidates:
                res = _price(template, app, kwh, tariff, hh, weather, cand)
                if res is None:
                    continue
                cf_series, used = res
                cf = cost(cf_series, tariff)
                saving = base.usd - cf.usd
                if best is None or saving > best[0] + 1e-12:
                    best = (saving, cf_series, used)
            if best is None:
                continue
            saving, cf_series, used = best
            cf = cost(cf_series, tariff)
            score = hh.success_scores.get(template.action_type)
            monthly = saving * DAYS_PER_MONTH / horizon
            surfaced = monthly >= MONTHLY_FLOOR_USD
            reason = None if surfaced else ("flat_tariff" if tariff.is_flat and template.shape == "shift" else "below_floor")
            rank = saving if (hh.first_week or score is None) else saving * (NEUTRAL_SCORE + score)
            if template.search is not None:
                used[template.search.name] = used[template.search.name]
            out.append(PricedAction(hh.household_id, app.appliance_id, template.action_type, used, base, cf,
                                    round(saving, 6), _nz(round(base.kg_co2 - cf.kg_co2, 6)), _assume(template, app, used),
                                    made_at, horizon, surfaced, reason, score, rank, template.actuator))
    return out


def rank(actions: list[PricedAction], limit: int = MAX_ACTIONS) -> list[PricedAction]:
    """TRS-13-06/09: surfaced actions ordered by rank score, at most `limit`."""
    live = [a for a in actions if a.surfaced]
    live.sort(key=lambda a: (-a.rank_score, -a.saving_usd, a.appliance_id, a.action_type))
    return live[:limit]


def _assume(template: Template, app: ApplianceInfo, params: dict) -> str:
    fmt = {"appliance": app.label, **{k: (int(v) if isinstance(v, float) and float(v).is_integer() else v) for k, v in params.items()}}
    try:
        return template.assumption.format(**fmt)
    except KeyError:
        return template.assumption


# ---- TRS-13-10 suppression helpers
def iso_week_id(ts: datetime, tz: str | None = None) -> str:
    """ISO week of ts. With tz, the week is taken in household local time (weeks start Monday
    00:00 local), which is when TRS-17-06 closes them."""
    t = pd.Timestamp(ts)
    if tz is not None and t.tzinfo is not None:
        t = t.tz_convert(tz)
    y, w, _ = t.isocalendar()
    return f"{y}-W{int(w):02d}"


def previous_week_ids(week_id: str, n: int) -> list[str]:
    y, w = week_id.split("-W")
    monday = pd.Timestamp.fromisocalendar(int(y), int(w), 1)
    return [iso_week_id(monday - pd.Timedelta(weeks=k)) for k in range(1, n + 1)]


def active_suppressions(records: list[tuple[str, str, str]], week_id: str) -> set[str]:
    """TRS-13-10: action_types whose recorded suppression (action_type, from_week, until_week)
    covers week_id. Read from the store so a suppression lasts its full 4 weeks."""
    return {at for at, frm, until in records if frm <= week_id <= until}


def suppressed_action_types(dismissed_weeks: dict[str, list[str]], week_id: str) -> dict[str, tuple[str, str]]:
    """New suppressions: action_type -> (from_week, until_week) for types dismissed (by the user
    or by week-end expiry, TRS-17-06) in each of the 3 weeks before week_id."""
    out = {}
    prev = previous_week_ids(week_id, SUPPRESS_AFTER_DISMISSALS)
    for at, weeks in dismissed_weeks.items():
        if all(p in set(weeks) for p in prev):
            y, w = week_id.split("-W")
            until = iso_week_id(pd.Timestamp.fromisocalendar(int(y), int(w), 1) + pd.Timedelta(weeks=SUPPRESS_WEEKS - 1))
            out[at] = (week_id, until)
    return out


def is_finite(x: float) -> bool:
    return math.isfinite(x)


def _nz(x: float) -> float:
    """A shift under a static carbon intensity saves exactly zero CO₂; keep it 0.0, not -0.0."""
    return 0.0 if abs(x) < 1e-9 else x
