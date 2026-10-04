"""Reads and costing for the API. One function per panel, each returning plain dicts."""

from __future__ import annotations

import json
import math
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd

from homewatt import display as d
from homewatt.cmp04_tariff.model import Tariff, load_tariff
from homewatt.cmp08_appliance_store.reader import read_hourly
from homewatt.cmp11_forecaster.pipeline import preferred_hourly, read_latest_forecast
from homewatt.cmp13_simulator.costing import cost
from homewatt.cmp13_simulator.simulator import iso_week_id
from homewatt.config import get_settings
from homewatt.spacetime import from_us, us

SPIKE_MARGIN = 0.25  # TRS-15-03: one named constant
SPIKE_BASELINE_DAYS = 14
STALE_SIM = pd.Timedelta(minutes=5)
SOURCE_LABEL = {"plug": "measured", "nilm": "estimated", "sim": "simulated feed"}
BASELOAD_LABEL = "Always on"
STATUS_LABEL = {"proposed": "Open", "accepted": "Taken, checking next week", "verified": "Saved", "not_verified": "Didn't show up"}


@lru_cache(maxsize=4)
def tariff_for(tariff_id: str) -> Tariff:
    return load_tariff(get_settings().tariff_dir / f"{tariff_id}.yaml")


class Ctx:
    """Per-request context: household, tariff, demo-aware now."""

    def __init__(self, client):
        from homewatt.clock import is_simulated, now

        s = get_settings()
        self.client = client
        self.hh = s.household_id
        h = client.sql(f"SELECT * FROM household WHERE household_id = '{self.hh}'")
        if h.empty:
            raise LookupError(f"household {self.hh} not found; seed it first")
        self.household = h.iloc[0]
        self.tariff = tariff_for(str(self.household["tariff_id"]))
        self.tz = self.tariff.timezone
        self.now = now(client, self.hh)
        self.simulated = is_simulated(client, self.hh)
        self.local_now = self.now.tz_convert(self.tz)

    def labels(self) -> dict[str, str]:
        apps = self.client.sql(f"SELECT appliance_id, label, type FROM appliance WHERE household_id = '{self.hh}'")
        out = {k: (v[:1].upper() + v[1:]) for k, v in zip(apps["appliance_id"], apps["label"], strict=True)} if len(apps) else {}
        out.setdefault("baseload", BASELOAD_LABEL)
        return out

    def types(self) -> dict[str, str]:
        apps = self.client.sql(f"SELECT appliance_id, type FROM appliance WHERE household_id = '{self.hh}'")
        return dict(zip(apps["appliance_id"], apps["type"], strict=True)) if len(apps) else {}

    def month_start(self) -> pd.Timestamp:
        return self.local_now.normalize().replace(day=1)

    def hourly_all(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Every source and model version (plug, sim, nilm side by side)."""
        return read_hourly(self.client, self.hh, start.tz_convert("UTC"), end.tz_convert("UTC"))

    def hourly(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        return preferred_hourly(self.hourly_all(start, end))


def latest_nilm(h: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """nilm rows of the deployed splitter version, else the last version present (TRS-08-06)."""
    from homewatt.cmp09_nilm.co import MODEL_VERSION_DEPLOY

    if h.empty:
        return h, ""
    n = h[h["source"] == "nilm"]
    if n.empty:
        return n, ""
    versions = set(n["model_version"])
    mv = MODEL_VERSION_DEPLOY if MODEL_VERSION_DEPLOY in versions else sorted(versions)[-1]
    return n[n["model_version"] == mv], mv


def _cost_by(h: pd.DataFrame, tariff: Tariff, by: str | None = None) -> pd.Series | float:
    if h.empty:
        return pd.Series(dtype=float) if by else 0.0
    r = tariff.rates(pd.DatetimeIndex(h["bucket"]))
    usd = h["kwh"].to_numpy(dtype=float) * r["usd_per_kwh"].to_numpy()
    if by is None:
        return float(usd.sum())
    return pd.Series(usd, index=h.index).groupby(h[by].to_numpy()).sum()


def nice_ticks(max_value: float, n: int = 3) -> list[dict]:
    """Axis ticks as display strings, computed here so the dashboard formats nothing (TRS-16-10)."""
    if not max_value or max_value <= 0:
        return []
    raw = max_value / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return [{"value": step * i, "display": f"{step * i:,.0f}" if step >= 1 else f"{step * i:,.2f}"} for i in range(1, n + 1)]


def _local_day(ts: pd.Series, tz: str) -> pd.Series:
    return pd.DatetimeIndex(ts).tz_convert(tz).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- meta
def meta(c: Ctx) -> dict:
    return {
        "household_id": c.hh,
        "now_utc": c.now.isoformat(),
        "now_label": c.local_now.strftime("%a %b %-d, %Y · %-I:%M %p"),
        "simulated_clock": c.simulated,
        "simulated_feed": True,
        "tariff_name": c.tariff.plan or c.tariff.tariff_id,
        "weather_note": "Replayed past: the weather forecast is what actually happened." if c.simulated else "",
    }


# ---------------------------------------------------------------- forecast helpers
def forecast_total(c: Ctx) -> tuple[pd.DataFrame, datetime | None]:
    fc, made = read_latest_forecast(c.client, c.hh)
    return fc, made


def _extend_hourly(series: pd.Series, until: pd.Timestamp) -> pd.Series:
    """Hours past the 168 h horizon repeat the forecast's same hour of the week."""
    if series.empty:
        return series
    idx = pd.date_range(series.index.min(), until, freq="h", inclusive="left", tz="UTC")
    out = series.reindex(idx)
    for i, ts in enumerate(idx):
        if pd.isna(out.iloc[i]):
            k = ts - pd.Timedelta(hours=168)
            while k not in series.index and k > series.index.min():
                k -= pd.Timedelta(hours=168)
            out.iloc[i] = series.get(k, 0.0)
    return out


# ---------------------------------------------------------------- panel 1: month summary
def summary(c: Ctx) -> dict:
    ms = c.month_start()
    me = (ms + pd.offsets.MonthBegin(1))
    h = c.hourly(ms, c.local_now)
    mtd = _cost_by(h, c.tariff)
    # daily actual cost
    daily_actual = {}
    if len(h):
        days = _local_day(h["bucket"], c.tz)
        daily_actual = _cost_by(h.assign(day=days.to_numpy()), c.tariff, "day").to_dict()
    # projection (TRS-15-02)
    fc, made = forecast_total(c)
    projected = None
    reason = None
    daily_fc: dict[str, tuple[float, float]] = {}
    if made is None or fc.empty:
        reason = "no_forecast"
    else:
        f = fc[fc["ts"] >= c.now]
        tot50 = f.groupby("ts")["kwh_p50"].sum()
        tot90 = f.groupby("ts")["kwh_p90"].sum()
        until = me.tz_convert("UTC")
        e50, e90 = _extend_hourly(tot50, until), _extend_hourly(tot90, until)
        if len(e50):
            c50 = cost(e50, c.tariff).usd
            c90 = cost(e90, c.tariff).usd
            projected = {"p50": mtd + c50, "p90": mtd + c90, "p50_display": d.money(mtd + c50), "p90_display": d.money(mtd + c90)}
            r50 = c.tariff.rates(e50.index)["usd_per_kwh"].to_numpy()
            dd = pd.Series(e50.to_numpy() * r50, index=e50.index).groupby(_local_day(pd.Series(e50.index), c.tz).to_numpy()).sum()
            dd90 = pd.Series(e90.to_numpy() * r50, index=e90.index).groupby(_local_day(pd.Series(e90.index), c.tz).to_numpy()).sum()
            daily_fc = {k: (float(dd[k]), float(dd90[k])) for k in dd.index}
        else:
            reason = "no_forecast"
    # vs last month, same number of elapsed days
    lm_start = ms - pd.offsets.MonthBegin(1)
    lm_h = c.hourly(lm_start, lm_start + (c.local_now - ms))
    lm = _cost_by(lm_h, c.tariff)
    vs = ((mtd / lm) - 1) * 100 if lm > 0 else None
    days = pd.date_range(ms.tz_localize(None), (me - pd.Timedelta(days=1)).tz_localize(None), freq="D").strftime("%Y-%m-%d")
    series = []
    for day in days:
        lab = pd.Timestamp(day).strftime("%a %b %-d")
        if day in daily_actual:
            v = float(daily_actual[day])
            series.append({"day": day, "label": lab, "kind": "actual", "usd": v, "p90_usd": None, "display": d.money(v), "p90_display": None})
        elif day in daily_fc:
            v, v90 = daily_fc[day]
            series.append({"day": day, "label": lab, "kind": "forecast", "usd": v, "p90_usd": v90, "display": d.money(v), "p90_display": d.money(v90)})
        else:
            series.append({"day": day, "label": lab, "kind": "none", "usd": None, "p90_usd": None, "display": None, "p90_display": None})
    ymax = max([x["p90_usd"] or x["usd"] or 0 for x in series] + [0])
    return {
        "month_label": c.local_now.strftime("%B %Y"),
        "month_to_date_usd": mtd,
        "month_to_date_display": d.money(mtd),
        "projected": projected,
        "projected_reason": reason,
        "vs_last_month_pct": vs,
        "vs_last_month_display": d.pct(vs) if vs is not None else None,
        "vs_last_month_note": None if vs is not None else f"No data for {lm_start.strftime('%B')}",
        "daily": series,
        "ticks": nice_ticks(ymax),
        "fixed_charge_note": f"Excludes the {d.money(c.tariff.fixed_usd_per_month)} dollar monthly service charge",
    }


# ---------------------------------------------------------------- panel 2: appliance breakdown
def appliances(c: Ctx) -> dict:
    ms = c.month_start()
    h_all = c.hourly_all(ms, c.local_now)
    h = preferred_hourly(h_all)
    nh, nilm_mv = latest_nilm(h_all)
    est_usd = _cost_by(nh, c.tariff, "appliance_id") if len(nh) else pd.Series(dtype=float)
    labels = c.labels()
    types = c.types()
    usd = _cost_by(h, c.tariff, "appliance_id") if len(h) else pd.Series(dtype=float)
    total = float(usd.sum()) if len(usd) else 0.0
    today = c.local_now.normalize()
    ht = h[h["bucket"] >= today.tz_convert("UTC")] if len(h) else h
    kwh_today = ht.groupby("appliance_id")["kwh"].sum() if len(ht) else pd.Series(dtype=float)
    if c.local_now == today and len(h):  # at local midnight, "today" is the day that just ended
        y = today - pd.Timedelta(days=1)
        hy = h[(h["bucket"] >= y.tz_convert("UTC")) & (h["bucket"] < today.tz_convert("UTC"))]
        kwh_today = hy.groupby("appliance_id")["kwh"].sum()
    live = c.client.sql(
        f"SELECT appliance_id, ts_us, watts, source FROM appliance_power WHERE household_id = '{c.hh}' AND ts_us >= {us(c.now - pd.Timedelta(minutes=10))} AND ts_us <= {us(c.now)}"
    )
    nilm = c.client.sql(
        "SELECT appliance_type, metric, value, eval_sessions, synthetic FROM model_metric "
        f"WHERE component = 'cmp09_nilm' AND model_version = '{nilm_mv or 'co-v1'}'"
    )
    nilm_rec = {r["appliance_type"]: r for r in nilm.to_dict("records") if r["metric"] == "mae_w"} if len(nilm) else {}
    hours = h.groupby("appliance_id")["covered_s"].sum() / 3600 if len(h) else pd.Series(dtype=float)
    kwh_m = h.groupby("appliance_id")["kwh"].sum() if len(h) else pd.Series(dtype=float)
    src_of = h.groupby("appliance_id")["source"].first().to_dict() if len(h) else {}
    mv_of = h.groupby("appliance_id")["model_version"].first().to_dict() if len(h) else {}
    items = []
    for app in sorted(set(usd.index) | set(labels) - {"baseload"} if len(usd) else labels):
        if app not in labels:
            continue
        src = src_of.get(app, "sim")
        lw = None
        stale = True
        if len(live):
            lv = live[(live["appliance_id"] == app) & (live["source"] == src)].sort_values("ts_us")
            if len(lv):
                lw = float(lv.iloc[-1]["watts"])
                stale = c.now - from_us(int(lv.iloc[-1]["ts_us"])) > STALE_SIM
        u = float(usd.get(app, 0.0))
        share = u / total * 100 if total else 0.0
        t = types.get(app)
        nilm_note = None
        has_est = nilm_mv != "" and app in est_usd.index
        eu = float(est_usd.get(app, 0.0)) if has_est else None
        if t in nilm_rec and float(hours.get(app, 0)) > 0:  # TRS-16-06: error in watts and as a share of typical draw
            rec = nilm_rec[t]
            mae = float(rec["value"])
            avg_w = float(kwh_m.get(app, 0.0)) * 1000 / float(hours[app])
            pct = mae / avg_w * 100 if avg_w > 0 else None
            where = "on synthetic days (synthetic HVAC)" if rec["synthetic"] else f"on real recordings ({rec['eval_sessions']})"
            nilm_note = (f"Splitter ({nilm_mv or 'co-v1'}) held-out error {where}: {d.watts(mae)} W"
                         + (f", about {pct:.0f}% of this appliance's average draw." if pct is not None else "."))
        elif t == "hvac":
            nilm_note = "Heating and cooling is synthetic in the practice home, so no real-data error exists for it."
        items.append({
            "appliance_id": app, "label": labels[app], "type": types.get(app, "other"),
            "usd_mtd": u, "usd_mtd_display": d.money(u), "share_pct": share, "share_display": f"{share:.0f}%",
            "kwh_today_display": d.kwh(float(kwh_today.get(app, 0.0))),
            "live_watts_display": d.watts(lw) if lw is not None else None, "stale": bool(stale),
            "source": src, "source_label": SOURCE_LABEL.get(src, src), "model_version": mv_of.get(app, ""),
            "error_detail": ("Simulated feed: these numbers come straight from the practice home, so there is no estimation error to show."
                             if src == "sim" else "Measured by a plug." if src == "plug" else "Estimated by the appliance splitter."),
            "nilm_note": nilm_note,
            "est_usd_mtd": eu, "est_usd_mtd_display": d.money(eu) if eu is not None else None,
            "est_share_pct": (eu / total * 100 if total else 0.0) if eu is not None else None,
            "est_label": f"estimated · {nilm_mv}" if has_est else None,
        })
    items.sort(key=lambda x: -x["usd_mtd"])
    return {"items": items, "total_display": d.money(total), "as_of": c.local_now.strftime("%-I:%M %p"),
            "nilm_model_version": nilm_mv or None}


# ---------------------------------------------------------------- panel 3: spikes
def spikes(c: Ctx) -> dict:
    labels = c.labels()
    base_start = c.local_now.normalize() - pd.Timedelta(days=SPIKE_BASELINE_DAYS)
    h = c.hourly(base_start, c.local_now.normalize())
    if h.empty:
        return {"days": [], "baseline_display": None, "spike": None, "margin_pct": int(SPIKE_MARGIN * 100)}
    days = _local_day(h["bucket"], c.tz).to_numpy()
    hd = h.assign(day=days)
    daily = _cost_by(hd, c.tariff, "day")
    n_days = max(1, len(daily))
    base = float(daily.mean())
    app_base = _cost_by(hd, c.tariff, "appliance_id") / n_days
    fc, made = forecast_total(c)
    out_days = []
    spike = None
    if made is not None and len(fc):
        f = fc[fc["ts"] >= c.now].copy()
        if len(f):
            f["day"] = _local_day(f["ts"], c.tz).to_numpy()
            r = c.tariff.rates(pd.DatetimeIndex(f["ts"]))["usd_per_kwh"].to_numpy()
            f["usd50"] = f["kwh_p50"].to_numpy() * r
            f["usd90"] = f["kwh_p90"].to_numpy() * r
            for day, g in f.groupby("day"):
                if g["ts"].nunique() < 20:  # partial day at the horizon end
                    continue
                p50, p90 = float(g["usd50"].sum()), float(g["usd90"].sum())
                by_app = g.groupby("appliance_id")["usd50"].sum()
                delta = (by_app - app_base.reindex(by_app.index).fillna(0.0)).sort_values(ascending=False)
                driver = labels.get(delta.index[0], delta.index[0]) if len(delta) else None
                is_spike = p50 > base * (1 + SPIKE_MARGIN)
                row = {"day": day, "label": pd.Timestamp(day).strftime("%a %b %-d"), "p50_usd": p50, "p90_usd": p90,
                       "p50_display": d.money(p50), "p90_display": d.money(p90), "spike": is_spike,
                       "delta_display": d.money(p50 - base), "driver_label": driver}
                out_days.append(row)
                if is_spike and (spike is None or p50 - base > spike["delta_usd"]):
                    spike = {**row, "delta_usd": p50 - base}
    ymax = max([x["p90_usd"] for x in out_days] + [base])
    return {"days": out_days, "baseline_usd": base, "baseline_display": d.money(base), "spike": spike,
            "margin_pct": int(SPIKE_MARGIN * 100), "ticks": nice_ticks(ymax)}


# ---------------------------------------------------------------- panel 4: health
def alerts(c: Ctx) -> dict:
    labels = c.labels()
    a = c.client.sql(f"SELECT * FROM alert WHERE household_id = '{c.hh}' AND closed_at_us = 0")
    items = []
    for r in a.sort_values("ts_us", ascending=False).to_dict("records") if len(a) else []:
        items.append({
            "alert_id": int(r["id"]), "appliance_label": labels.get(r["appliance_id"], r["appliance_id"]), "text": r["text"][0].upper() + r["text"][1:],
            "severity": r["severity"], "since_label": (from_us(int(r["ts_us"])) - pd.Timedelta(seconds=1)).tz_convert(c.tz).strftime("%a %b %-d"),
            "acknowledged": int(r["acknowledged_at_us"]) != 0,
        })
    monitored = sorted({labels[k] for k, t in c.types().items() if t == "fridge"})
    return {"items": items, "monitored": monitored}


# ---------------------------------------------------------------- actions
def _sentences(c: Ctx) -> dict[str, tuple[str, bool]]:
    st = c.client.sql(f"SELECT action_id, text, unnarrated FROM statement WHERE household_id = '{c.hh}' AND superseded_at_us = 0")
    return {r["action_id"]: (r["text"], bool(r["unnarrated"])) for r in st.to_dict("records")} if len(st) else {}


def _status_label(r: dict) -> str:
    if r["status"] == "dismissed":
        return "Not taken" if r["status_reason"] == "expired" else "Dismissed"
    return STATUS_LABEL.get(r["status"], r["status"])


def actions(c: Ctx) -> dict:
    week = iso_week_id(c.now, c.tz)
    labels = c.labels()
    acts = c.client.sql(f"SELECT * FROM action WHERE household_id = '{c.hh}' AND week_id = '{week}'")
    earlier = c.client.sql(f"SELECT COUNT(*) AS n FROM action WHERE household_id = '{c.hh}' AND week_id < '{week}'")
    first_week = int(earlier.iloc[0]["n"]) == 0
    supp = c.client.sql(f"SELECT action_type, from_week_id, until_week_id FROM action_suppression WHERE household_id = '{c.hh}'")
    suppressed = {r["action_type"] for r in supp.to_dict("records") if r["from_week_id"] <= week <= r["until_week_id"]} if len(supp) else set()
    sentences = _sentences(c)
    items = []
    for r in acts.to_dict("records") if len(acts) else []:
        month = d.per_month(float(r["saving_usd"]))
        score = float(r["success_score"])
        rank_score = float(r["saving_usd"]) * (1.0 if (first_week or score < 0) else (0.5 + score))
        text, unnarrated = sentences.get(r["action_id"], (d.plain_change(r["assumption_text"]), True))
        viable = r["status"] == "proposed" and month >= 1.0 and r["action_type"] not in suppressed
        items.append({
            "action_id": r["action_id"], "appliance_label": labels.get(r["appliance_id"], r["appliance_id"]),
            "action_type": r["action_type"], "sentence": text, "narrated": not unnarrated,
            "saving_month_display": d.money(month), "kg_month_display": d.kg(d.per_month(float(r["saving_kg_co_2"]))),
            "status": r["status"], "status_label": _status_label(r), "viable": viable,
            "take_kind": "thermostat" if r["action_type"] == "hvac_setpoint_away" else "accept",
            "_rank": rank_score,
        })
    items.sort(key=lambda x: -x["_rank"])
    for i, it in enumerate(items, 1):
        it["rank"] = i
        del it["_rank"]
    open_items = [i for i in items if i["status"] == "proposed"]
    biggest = (open_items or items or [None])[0]
    monday = pd.Timestamp.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    return {"week_id": week, "week_label": f"Week of {monday.strftime('%b %-d')}", "first_week": first_week, "items": items,
            "biggest": biggest}


# ---------------------------------------------------------------- savings tab
def savings(c: Ctx) -> dict:
    labels = c.labels()
    acts = c.client.sql(f"SELECT * FROM action WHERE household_id = '{c.hh}'")
    if acts.empty:
        return {"verified_total_display": d.money(0.0), "promised_total_display": d.money(0.0), "counts": {}, "items": []}
    week = iso_week_id(c.now, c.tz)
    past = acts[(acts["status"] != "proposed")]
    ver = past[past["status"] == "verified"]
    taken = past[past["status"].isin(["accepted", "verified", "not_verified"])]
    verified_total = float(ver["verified_saving_usd"].sum()) if len(ver) else 0.0
    promised = float(taken["saving_usd"].sum()) if len(taken) else 0.0
    sentences = _sentences(c)
    items = []
    for r in past.sort_values(["week_id", "saving_usd"], ascending=[False, False]).to_dict("records"):
        monday = pd.Timestamp.fromisocalendar(int(r["week_id"][:4]), int(r["week_id"][6:]), 1)
        outcome = _status_label(r)
        if r["status"] == "verified":
            detail = f"Saved {d.money(float(r['verified_saving_usd']))} dollars that week"
        elif r["status"] == "not_verified":
            detail = f"Expected {d.money(float(r['saving_usd']))}, measured {d.money(float(r['verified_saving_usd']))}"
        elif r["status"] == "accepted":
            detail = "Verdict after 7 days"
        else:
            detail = ""
        items.append({
            "action_id": r["action_id"], "week_label": f"Week of {monday.strftime('%b %-d')}", "this_week": r["week_id"] == week,
            "appliance_label": labels.get(r["appliance_id"], r["appliance_id"]),
            "sentence": sentences.get(r["action_id"], (d.plain_change(r["assumption_text"]), True))[0],
            "outcome": r["status"] if r["status"] != "dismissed" else ("expired" if r["status_reason"] == "expired" else "dismissed"),
            "outcome_label": outcome, "detail": detail,
        })
    counts = pd.Series([i["outcome"] for i in items]).value_counts().to_dict() if items else {}
    return {"verified_total_usd": verified_total, "verified_total_display": d.money(verified_total),
            "promised_total_display": d.money(promised), "counts": {k: int(v) for k, v in counts.items()}, "items": items}


# ---------------------------------------------------------------- tariff and thermostat
def tariff(c: Ctx) -> dict:
    t = c.tariff
    rows = [{"season": s.name, "months": f"{s.start} to {s.end}", "period": p.name.replace("_", "-"), "days": ", ".join(p.days),
             "hours": f"{p.start_hour:02d}:00–{p.end_hour:02d}:00", "cents_per_kwh": f"{p.usd_per_kwh * 100:.3f}"}
            for s in t.seasons for p in s.periods]
    return {"tariff_id": t.tariff_id, "plan": t.plan, "utility": t.utility, "valid_from": t.valid_from.isoformat(), "rows": rows,
            "fixed_display": d.money(t.fixed_usd_per_month), "carbon": f"{t.kg_co2_per_kwh} kg CO₂ per kWh ({t.carbon_source})"}


def thermostat(c: Ctx) -> dict:
    st = c.client.sql(f"SELECT * FROM thermostat_state WHERE household_id = '{c.hh}'")
    if st.empty:
        return {"present": False}
    s = st.iloc[0]
    labels = c.labels()
    acts = c.client.sql(f"SELECT * FROM actuation WHERE household_id = '{c.hh}'")
    last = None
    if len(acts):
        a = acts.sort_values("ts_us").iloc[-1]
        expires = int(a["undo_expires_at_us"])
        can_undo = a["result"] == "applied" and a["actor"] == "user" and expires > us(c.now)
        last = {"actuation_id": a["actuation_id"], "actor": a["actor"], "result": a["result"], "error": a["error"],
                "previous_c": float(a["previous_c"]), "applied_c": float(a["applied_c"]),
                "at_label": from_us(int(a["ts_us"])).tz_convert(c.tz).strftime("%a %b %-d, %-I:%M %p"),
                "can_undo": bool(can_undo),
                "undo_until_label": from_us(expires).tz_convert(c.tz).strftime("%a %-I:%M %p") if expires else None}
    return {"present": True, "label": labels.get(s["appliance_id"], s["appliance_id"]), "setpoint_c": float(s["current_setpoint_c"]),
            "mode": s["mode"], "simulated": bool(s["simulated"]), "last_change": last}


def json_safe(o):
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, list):
        return [json_safe(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, (np.floating,)):
        return json_safe(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


__all__ = ["Ctx", "meta", "summary", "appliances", "spikes", "alerts", "actions", "savings", "tariff", "thermostat", "json_safe", "json"]
