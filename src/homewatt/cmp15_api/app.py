"""FastAPI app. Run: `homewatt api serve` (serves the built dashboard at / when present)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from homewatt.cmp15_api import data
from homewatt.config import REPO_ROOT
from homewatt.display import fahrenheit

log = logging.getLogger(__name__)
DIST = REPO_ROOT / "dashboard" / "dist"

app = FastAPI(title="HomeWatt API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

_client = None


def client():
    global _client
    if _client is None:
        from homewatt.spacetime import SpacetimeClient

        _client = SpacetimeClient.from_settings()
    return _client


def ctx() -> data.Ctx:
    from homewatt.spacetime import SpacetimeUnavailable

    try:
        return data.Ctx(client())
    except SpacetimeUnavailable as e:
        raise HTTPException(503, f"store unavailable: {e}") from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


def ok(payload) -> JSONResponse:
    return JSONResponse(data.json_safe(payload))


@app.exception_handler(Exception)
async def _unhandled(request, exc):  # noqa: ARG001
    from homewatt.spacetime import SpacetimeUnavailable

    if isinstance(exc, SpacetimeUnavailable):
        return JSONResponse({"detail": "store unavailable"}, status_code=503)
    log.exception("unhandled")
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


# ---------------------------------------------------------------- v0.12 sign-up and log-in (CMP-14)
@app.middleware("http")
async def require_login(request, call_next):
    """Every /api route except /api/auth/* needs a signed session cookie."""
    from homewatt.cmp14_onboarding.accounts import SESSION_COOKIE, read_session, session_secret

    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/auth/"):
        if read_session(request.cookies.get(SESSION_COOKIE), session_secret()) is None:
            return JSONResponse({"detail": "Log in to continue."}, status_code=401)
    return await call_next(request)


def _signed_in(payload: dict) -> JSONResponse:
    from homewatt.cmp14_onboarding.accounts import (
        SESSION_COOKIE,
        SESSION_DAYS,
        make_session,
        session_secret,
    )

    r = ok(payload)
    r.set_cookie(SESSION_COOKIE, make_session(payload["email"], session_secret()), max_age=SESSION_DAYS * 86400,
                 httponly=True, samesite="lax")
    return r


@app.post("/api/auth/signup")
def post_signup(body: dict):
    from homewatt.cmp14_onboarding.accounts import Signup, SignupError, create_account
    from homewatt.config import get_settings

    try:
        acc = create_account(client(), Signup(str(body.get("name", "")), str(body.get("email", "")), str(body.get("password", "")),
                                              str(body.get("zip", ""))), get_settings().household_id)
    except SignupError as e:
        raise HTTPException(400, str(e)) from e
    return _signed_in(acc)


@app.post("/api/auth/login")
def post_login(body: dict):
    from homewatt.cmp14_onboarding.accounts import check_login

    acc = check_login(client(), str(body.get("email", "")), str(body.get("password", "")))
    if acc is None:
        raise HTTPException(401, "Email or password is wrong.")
    return _signed_in(acc)


@app.post("/api/auth/logout")
def post_logout():
    from homewatt.cmp14_onboarding.accounts import SESSION_COOKIE

    r = ok({"ok": True})
    r.delete_cookie(SESSION_COOKIE)
    return r


@app.get("/api/auth/me")
def get_me(request: Request):
    from homewatt.cmp14_onboarding.accounts import (
        SESSION_COOKIE,
        find_account,
        read_session,
        session_secret,
    )

    email = read_session(request.cookies.get(SESSION_COOKIE), session_secret())
    acc = find_account(client(), email) if email else None
    if acc is None:
        raise HTTPException(401, "Log in to continue.")
    return ok({"email": acc["email"], "name": acc["name"]})


# ---------------------------------------------------------------- reads (TRS-15 outputs)
@app.get("/api/meta")
def get_meta():
    return ok(data.meta(ctx()))


@app.get("/api/summary")
def get_summary():
    return ok(data.summary(ctx()))


@app.get("/api/appliances")
def get_appliances():
    return ok(data.appliances(ctx()))


@app.get("/api/spikes")
def get_spikes():
    return ok(data.spikes(ctx()))


@app.get("/api/alerts")
def get_alerts():
    return ok(data.alerts(ctx()))


@app.get("/api/actions")
def get_actions():
    return ok(data.actions(ctx()))


@app.get("/api/savings")
def get_savings():
    return ok(data.savings(ctx()))


@app.get("/api/tariff")
def get_tariff():
    return ok(data.tariff(ctx()))


@app.get("/api/day/{day}")
def get_day(day: str):
    """v0.12: the appliance rundown behind one bar of the bill chart."""
    try:
        return ok(data.day_breakdown(ctx(), day))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/thermostat")
def get_thermostat():
    return ok(data.thermostat(ctx()))


# ---------------------------------------------------------------- user taps (TRS-15-06: status transitions only)
def _action_row(c: data.Ctx, action_id: str):
    df = c.client.sql(f"SELECT * FROM action WHERE action_id = '{action_id}' AND household_id = '{c.hh}'")
    if df.empty:
        raise HTTPException(404, "no such action")
    return df.iloc[0]


@app.post("/api/actions/{action_id}/dismiss")
def post_dismiss(action_id: str):
    from homewatt.cmp17_ledger.ledger import dismiss
    from homewatt.spacetime import SpacetimeError

    c = ctx()
    _action_row(c, action_id)
    try:
        dismiss(c.client, action_id)
    except SpacetimeError as e:
        raise HTTPException(409, str(e)) from e
    return ok({"ok": True})


def _actuator(c: data.Ctx):
    from homewatt.cmp19_actuator.actuator import ScheduleActuator
    from homewatt.cmp19_actuator.adapter import SimulatedThermostat

    return ScheduleActuator(c.client, c.hh, SimulatedThermostat(c.client, c.hh), c.now)


@app.post("/api/actions/{action_id}/take")
def post_take(action_id: str):
    """First tap. Thermostat actions return a preview (TRS-19-08) and change nothing; every other
    action is accepted in the ledger (advice only)."""
    from homewatt.cmp17_ledger.ledger import accept
    from homewatt.cmp19_actuator.actuator import ActuationRefused
    from homewatt.display import money, per_month
    from homewatt.spacetime import SpacetimeError

    c = ctx()
    a = _action_row(c, action_id)
    if a["status"] != "proposed":
        raise HTTPException(409, f"action is {a['status']}")
    if a["action_type"] == "hvac_setpoint_away":
        try:
            p = _actuator(c).preview(action_id)
        except ActuationRefused as e:
            raise HTTPException(409, str(e)) from e
        return ok({"kind": "thermostat", "preview": {
            "device_label": p.device_label, "current_c": p.current_c, "requested_c": p.requested_c, "applied_c": p.applied_c,
            "current_display": fahrenheit(p.current_c), "requested_display": fahrenheit(p.requested_c), "applied_display": fahrenheit(p.applied_c),
            "clamped": p.clamped, "simulated": p.simulated, "saving_month_display": money(per_month(float(a["saving_usd"]))),
        }})
    if data.take_kind(a.to_dict()) == "schedule":  # v0.11 TRS-19-10: preview the schedule, change nothing
        import pandas as pd

        from homewatt.display import hour12

        try:
            p = _actuator(c).preview_schedule(action_id)
        except ActuationRefused as e:
            raise HTTPException(409, str(e)) from e
        last_day = p.valid_until.tz_convert(c.tz) - pd.Timedelta(seconds=1)
        return ok({"kind": "schedule", "preview": {
            "device_label": p.device_label, "current_display": fahrenheit(p.current_c),
            "lines": [f"{hour12(p.pre_start)}–{hour12(p.peak_start)}: {fahrenheit(p.pre_c)} °F", f"{hour12(p.peak_start)}–{hour12(p.peak_end)}: {fahrenheit(p.peak_c)} °F"],
            "days_label": "weekdays" if p.weekdays_only else "every day", "until_label": last_day.strftime("%a %b %-d"),
            "simulated": p.simulated, "saving_month_display": money(per_month(float(a["saving_usd"]))),
        }})
    try:
        accept(c.client, action_id)
    except SpacetimeError as e:
        raise HTTPException(409, str(e)) from e
    return ok({"kind": "accepted"})


@app.post("/api/actions/{action_id}/confirm")
def post_confirm(action_id: str):
    """Second tap for a thermostat action: accept and apply (TRS-19-01..05)."""
    from homewatt.cmp19_actuator.actuator import ActuationRefused

    c = ctx()
    a = _action_row(c, action_id)
    try:
        if data.take_kind(a.to_dict()) == "schedule":  # v0.11: install the schedule (TRS-19-10..12)
            sr = _actuator(c).confirm_schedule(action_id)
            return ok({"kind": "schedule", "result": sr.result, "schedule_id": sr.schedule_id, "error": sr.error})
        r = _actuator(c).confirm(action_id)
    except ActuationRefused as e:
        raise HTTPException(409, str(e)) from e
    return ok({"kind": "thermostat", "result": r.result, "previous_c": r.previous_c, "applied_c": r.applied_c, "applied_display": fahrenheit(r.applied_c),
               "actuation_id": r.actuation_id, "error": r.error})


@app.post("/api/schedules/{schedule_id}/undo")
def post_undo_schedule(schedule_id: str):
    """v0.11 TRS-19-12: within 24 h, remove an installed schedule, logged as 'undo'."""
    from homewatt.cmp19_actuator.actuator import ActuationRefused

    c = ctx()
    try:
        r = _actuator(c).undo_schedule(schedule_id)
    except ActuationRefused as e:
        raise HTTPException(409, str(e)) from e
    return ok({"result": r.result, "schedule_id": r.schedule_id, "error": r.error})


@app.post("/api/actuations/{actuation_id}/undo")
def post_undo(actuation_id: str):
    from homewatt.cmp19_actuator.actuator import ActuationRefused

    c = ctx()
    try:
        r = _actuator(c).undo(actuation_id)
    except ActuationRefused as e:
        raise HTTPException(409, str(e)) from e
    return ok({"result": r.result, "applied_c": r.applied_c, "applied_display": fahrenheit(r.applied_c), "actuation_id": r.actuation_id, "error": r.error})


@app.post("/api/alerts/{alert_id}/ack")
def post_ack(alert_id: int):
    c = ctx()
    c.client.call("acknowledge_alert", int(alert_id))
    return ok({"ok": True})


# ---------------------------------------------------------------- dashboard (built)
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and Path(f).resolve().is_relative_to(DIST.resolve()):
            return FileResponse(f)
        # the shell must never be cached: it names the hashed bundle, so a stale copy runs old code
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-store"})
