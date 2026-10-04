"""Demo driver. It never takes an action and never touches a device (TRS-SYS-03, TRS-19-01): a
person taps Take action on the dashboard between `advance` calls. What the driver does:

  per replayed day   replay the aggregate (37 fields, 2 s) and the simulated per-appliance feed
                     through CMP-05, run the splitter on the stored aggregate (CMP-09, 60 s nilm
                     rows, OI-13), move the demo clock, run the anomaly detector (CMP-12);
  at Monday 00:00    close ended weeks (TRS-17-06), verify and score (CMP-18), write the week's
                     weather forecast (replayed past, perfect foresight), forecast (CMP-11),
                     price and propose (CMP-13), narrate (CMP-20).

Before replaying, the future part of the timeline is regenerated when the ledger or the
thermostat changed: accepted suggestions are followed by the simulated household from their
acceptance time, and applied setpoints reshape the HVAC track from the tap (TRS-19-07). Days
already replayed are never rewritten (TRS-SYS-04)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from homewatt.config import REPO_ROOT, get_settings

log = logging.getLogger(__name__)

DEMO_DIR = REPO_ROOT / "data" / "synthetic" / "demo"
STATE = DEMO_DIR / "state.json"
SIM_PERIOD_S = 60.0


@dataclass
class DemoState:
    household_id: str = "hh-demo"
    start_local: str = "2025-06-30T00:00"
    days: int = 28
    seed: int = 7
    profile: str = "config/profiles/demo_household.yaml"
    weather: str = "data/weather/ann_arbor_2025.parquet"
    fault: str = "config/faults/fridge_day12.yaml"
    tariff: str = "config/tariffs/dte_d1_11.yaml"
    replayed_until_utc: str = ""
    timeline_key: str = ""
    comply: bool = True
    history: list[str] = field(default_factory=list)

    def save(self) -> None:
        DEMO_DIR.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls) -> DemoState:
        if not STATE.exists():
            raise FileNotFoundError("no demo state; run `homewatt demo init` first")
        return cls(**json.loads(STATE.read_text()))


def _p(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _tz(state: DemoState) -> str:
    from homewatt.cmp06_synth.profile import Profile

    return Profile.load(_p(state.profile)).local_tz


# ---------------------------------------------------------------- behaviour from the ledger
def accepted_actions(client, household_id: str) -> pd.DataFrame:
    acts = client.sql(f"SELECT * FROM action WHERE household_id = '{household_id}'")
    if acts.empty:
        return acts
    acts = acts[acts["status"].isin(["accepted", "verified", "not_verified"])]
    if acts.empty:
        return acts
    tr = client.sql("SELECT action_id, to_status, at_us FROM action_transition WHERE to_status = 'accepted'")
    when = dict(zip(tr["action_id"], tr["at_us"], strict=True)) if len(tr) else {}
    acts = acts.assign(accepted_at_us=acts["action_id"].map(when)).dropna(subset=["accepted_at_us"])
    return acts.sort_values("accepted_at_us").reset_index(drop=True)


def behaviours_and_setpoints(client, state: DemoState, step_ts: pd.DatetimeIndex, base_setpoint: float):
    """(behaviours, setpoint array per 60 s step or None, key)."""
    from homewatt.cmp06_synth.behaviour import Behaviour
    from homewatt.spacetime import from_us

    hh = state.household_id
    tz = _tz(state)
    behaviours: list[Behaviour] = []
    sp = np.full(len(step_ts), base_setpoint, dtype=np.float64)
    changed_sp = False
    acts = accepted_actions(client, hh) if state.comply else pd.DataFrame()
    for a in acts.to_dict("records"):
        t0 = from_us(int(a["accepted_at_us"])).to_pydatetime()
        params = json.loads(a["params_json"])
        at = a["action_type"]
        if at == "shift_out_of_peak":
            behaviours.append(Behaviour(appliance_id=a["appliance_id"], from_ts=t0, kind="shift_peak", to_hour=int(params["to_hour"]),
                                        peak_start=15, peak_end=19, source_action_id=a["action_id"]))
        elif at in ("water_heater_setpoint", "trim_standby"):
            behaviours.append(Behaviour(appliance_id=a["appliance_id"], from_ts=t0, kind="scale", factor=float(params["factor"]),
                                        source_action_id=a["action_id"]))
        elif at == "fridge_service":
            behaviours.append(Behaviour(appliance_id=a["appliance_id"], from_ts=t0, kind="end_fault", source_action_id=a["action_id"]))
        elif at == "hvac_precool":
            # Advice-only in V1 (TRS-SYS-03 forbids scheduled device changes); the simulated household
            # follows it by hand: cooler 13:00-15:00, air conditioner resting 15:00-19:00, weekdays.
            local = step_ts.tz_convert(tz)
            wk = local.weekday < 5
            after = step_ts >= pd.Timestamp(t0)
            pre = after & wk & (local.hour >= int(params.get("peak_start", 15)) - 2) & (local.hour < int(params.get("peak_start", 15)))
            rest = after & wk & (local.hour >= int(params.get("peak_start", 15))) & (local.hour < int(params.get("peak_end", 19)))
            sp[np.asarray(pre)] -= 2.0
            sp[np.asarray(rest)] = 35.0
            changed_sp = True
        # hvac_setpoint_away is a device action: it reaches the timeline only through the actuation log
    acts_log = client.sql(f"SELECT * FROM actuation WHERE household_id = '{hh}' AND result = 'applied'")
    for r in acts_log.sort_values("ts_us").to_dict("records") if len(acts_log) else []:
        at = from_us(int(r["ts_us"]))
        sp[np.asarray(step_ts >= at)] = np.where(sp[np.asarray(step_ts >= at)] >= 35.0, 35.0, float(r["applied_c"]))
        changed_sp = True
    key_src = json.dumps({"b": [b.model_dump(mode="json") for b in behaviours], "sp": hashlib.sha256(sp.tobytes()).hexdigest() if changed_sp else ""}, sort_keys=True)
    return behaviours, (sp if changed_sp else None), hashlib.sha256(key_src.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- timeline
def timeline_dir() -> Path:
    return DEMO_DIR / "timeline"


def ensure_timeline(client, state: DemoState) -> bool:
    """Regenerate the timeline when the household's behaviour or thermostat changed. Returns True
    when it regenerated. Replayed days are unaffected because every change starts at or after now."""
    from homewatt.cmp00_activations.library import ActivationLibrary
    from homewatt.cmp06_synth import thermostat as thermo
    from homewatt.cmp06_synth.fault import Fault
    from homewatt.cmp06_synth.generator import generate, write_timeline
    from homewatt.cmp06_synth.profile import Profile

    prof = Profile.load(_p(state.profile))
    tz = prof.local_tz
    start_local = datetime.fromisoformat(state.start_local)
    start_utc = pd.Timestamp(start_local, tz=tz).tz_convert("UTC")
    step_ts = pd.date_range(start_utc, periods=state.days * 86400 // thermo.STEP_S, freq=f"{thermo.STEP_S}s", tz="UTC")
    behaviours, sp, key = behaviours_and_setpoints(client, state, step_ts, prof.thermostat.setpoint_c)
    if key == state.timeline_key and (timeline_dir() / "aggregate.parquet").exists():
        return False
    s = get_settings()
    tl = generate(prof, ActivationLibrary(s.library_dir), pd.read_parquet(_p(state.weather)), start_local, state.days,
                  state.seed, Fault.load(_p(state.fault)) if state.fault else None, sp, behaviours)
    write_timeline(tl, timeline_dir())
    state.timeline_key = key
    state.history.append(f"regenerated timeline key {key}: {len(behaviours)} behaviours, setpoint override {sp is not None}")
    state.save()
    log.info("timeline regenerated (key %s, %d behaviours)", key, len(behaviours))
    return True


# ---------------------------------------------------------------- jobs
def seed(client, state: DemoState) -> None:
    from homewatt.cmp03_weather.store import write_weather
    from homewatt.cmp04_tariff.model import load_tariff
    from homewatt.cmp06_synth.profile import Profile

    s = get_settings()
    p = Profile.load(_p(state.profile))
    client.call("upsert_household", p.household_id, "48104", 42.2808, -83.7430, "dte_d1_11", 2, p.local_tz)
    for app_id, sch in p.appliances.items():
        client.call("upsert_appliance", p.household_id, app_id, str(sch.type), sch.label, 0.0, 0.0, 0.0)
    tp = p.thermostat
    client.call("upsert_appliance", p.household_id, tp.appliance_id, "hvac", tp.label, tp.min_setpoint_c, tp.max_setpoint_c, tp.max_step_c)
    client.call("init_thermostat_state", p.household_id, tp.appliance_id, tp.setpoint_c, True)
    t = load_tariff(_p(state.tariff))
    client.call("upsert_tariff", t.period_rows(), t.tariff_id, t.valid_from.isoformat(), float(t.fixed_usd_per_month))
    wx = pd.read_parquet(_p(state.weather))
    have = client.sql(f"SELECT COUNT(*) AS n FROM weather WHERE location_id = '{s.location_id}' AND is_forecast = false")
    if int(have.iloc[0]["n"]) < len(wx):
        write_weather(client, wx, s.location_id, False, pd.Timestamp(state.start_local, tz=p.local_tz).tz_convert("UTC"))


def weekly(client, state: DemoState, now: pd.Timestamp) -> dict:
    from homewatt.cmp03_weather.store import write_weather
    from homewatt.cmp04_tariff.model import load_tariff
    from homewatt.cmp06_synth.profile import Profile
    from homewatt.cmp11_forecaster.pipeline import run as forecast_run
    from homewatt.cmp13_simulator.atl import load_atl
    from homewatt.cmp13_simulator.pipeline import run as simulate_run
    from homewatt.cmp13_simulator.simulator import iso_week_id
    from homewatt.cmp17_ledger.ledger import close_ended_weeks
    from homewatt.cmp18_verifier.verifier import run_week
    from homewatt.cmp20_narrator.narrator import default_backend
    from homewatt.cmp20_narrator.narrator import run as narrate_run

    s = get_settings()
    hh = state.household_id
    tariff = load_tariff(_p(state.tariff))
    prof = Profile.load(_p(state.profile))
    out: dict = {"now": str(now)}
    out["closed_through"] = close_ended_weeks(client, hh, now, tariff.timezone)
    verified, scores = run_week(client, hh, now, tariff)
    out["verified"] = [(v.action_type, v.status, round(v.verified_saving_usd, 2), round(v.expected_usd, 2)) for v in verified]
    out["scores"] = scores
    wx = pd.read_parquet(_p(state.weather))
    horizon = wx[(wx["ts"] >= now) & (wx["ts"] < now + pd.Timedelta(days=7))]
    write_weather(client, horizon, s.location_id, True, now)
    fr = forecast_run(client, hh, s.location_id, now, tariff.timezone)
    out["forecast"] = {f.appliance_id: f.model_version for f in fr.forecasts}
    batch, _ = simulate_run(client, hh, tariff, load_atl(), s.location_id, now, prof.thermostat)
    out["batch"] = [(r.appliance_id, r.action_type, r.status) for r in batch.itertuples()] if len(batch) else []
    statements = narrate_run(client, hh, iso_week_id(now, tariff.timezone), default_backend())
    out["narrated"] = sum(1 for x in statements if x.narrated)
    out["unnarrated"] = [(x.action_id[:8], x.reason) for x in statements if not x.narrated]
    return out


def advance(client, until_local: str) -> list[dict]:
    """Replay whole local days up to `until_local` (exclusive), running daily and weekly jobs."""
    from homewatt.clock import set_now
    from homewatt.cmp05_ingest.models import ApplianceSample
    from homewatt.cmp05_ingest.replay import iter_samples, sim_model_version, tracks_from_truth
    from homewatt.cmp05_ingest.service import IngestionService
    from homewatt.cmp05_ingest.sinks import SpacetimeSink
    from homewatt.cmp09_nilm.runner import load_model
    from homewatt.cmp09_nilm.runner import run_day as nilm_day
    from homewatt.cmp12_anomaly.detector import run_day

    state = DemoState.load()
    tz = _tz(state)
    start = pd.Timestamp(state.start_local, tz=tz)
    end_of_timeline = start + pd.Timedelta(days=state.days)
    until = min(pd.Timestamp(until_local, tz=tz), end_of_timeline)
    cur = pd.Timestamp(state.replayed_until_utc).tz_convert(tz) if state.replayed_until_utc else start
    if until <= cur:
        log.info("nothing to replay: already at %s", cur)
        return []
    ensure_timeline(client, state)
    meta = json.loads((timeline_dir() / "meta.json").read_text())
    agg = pd.read_parquet(timeline_dir() / "aggregate.parquet")
    truth = pd.read_parquet(timeline_dir() / "truth.parquet")
    mv = sim_model_version(meta)
    sink = SpacetimeSink(client)
    svc = IngestionService(sink)
    nilm = load_model()
    reports: list[dict] = []
    while cur < until:
        nxt = (cur + pd.Timedelta(days=1)).normalize()
        a, b = cur.tz_convert("UTC"), nxt.tz_convert("UTC")
        day_agg = agg[(agg["ts"] >= a) & (agg["ts"] < b)]
        for smp in iter_samples(day_agg):
            svc.submit(smp)
        svc.flush()
        day_truth = truth[(truth["ts"] >= a) & (truth["ts"] < b)]
        for r in tracks_from_truth(day_truth, state.household_id, SIM_PERIOD_S).itertuples(index=False):
            svc.submit_plug(ApplianceSample(r.household_id, r.appliance_id, r.ts.to_pydatetime(), float(r.watts), "sim", mv, SIM_PERIOD_S))
        svc.flush()
        nilm_rep = nilm_day(client, state.household_id, a, b, nilm)
        set_now(client, state.household_id, b)
        decisions = run_day(client, state.household_id, cur.date(), tz)
        rep = {"day": str(cur.date()), "samples": len(day_agg), "nilm_rows": nilm_rep["rows"],
               "anomaly": [d for d in decisions if d["decision"] != "insufficient history"]}
        state.replayed_until_utc = b.isoformat()
        state.save()
        if nxt.weekday() == 0:  # Monday 00:00 local: the week just ended
            rep["weekly"] = weekly(client, state, b)
        log.info("replayed %s: %s", cur.date(), {k: v for k, v in rep.items() if k != "samples"})
        reports.append(rep)
        cur = nxt
    svc.close()
    return reports
