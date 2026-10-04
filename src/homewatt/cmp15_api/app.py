"""FastAPI app. Run: `homewatt api serve` (serves the built dashboard at / when present)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from homewatt.cmp15_api import data
from homewatt.config import REPO_ROOT

log = logging.getLogger(__name__)
DIST = REPO_ROOT / "dashboard" / "dist"

app = FastAPI(title="HomeWatt API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])

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
    from homewatt.cmp19_actuator.actuator import Actuator
    from homewatt.cmp19_actuator.adapter import SimulatedThermostat

    return Actuator(c.client, c.hh, SimulatedThermostat(c.client, c.hh), c.now)


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
            "clamped": p.clamped, "simulated": p.simulated, "saving_month_display": money(per_month(float(a["saving_usd"]))),
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
    _action_row(c, action_id)
    try:
        r = _actuator(c).confirm(action_id)
    except ActuationRefused as e:
        raise HTTPException(409, str(e)) from e
    return ok({"result": r.result, "previous_c": r.previous_c, "applied_c": r.applied_c, "actuation_id": r.actuation_id, "error": r.error})


@app.post("/api/actuations/{actuation_id}/undo")
def post_undo(actuation_id: str):
    from homewatt.cmp19_actuator.actuator import ActuationRefused

    c = ctx()
    try:
        r = _actuator(c).undo(actuation_id)
    except ActuationRefused as e:
        raise HTTPException(409, str(e)) from e
    return ok({"result": r.result, "applied_c": r.applied_c, "actuation_id": r.actuation_id, "error": r.error})


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
        return FileResponse(DIST / "index.html")
