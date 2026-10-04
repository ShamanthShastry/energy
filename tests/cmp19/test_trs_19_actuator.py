import re

import pandas as pd
import pytest

from homewatt.cmp19_actuator.actuator import ActuationRefused, Actuator, clamp
from homewatt.cmp19_actuator.adapter import DeviceUnavailable, ThermostatState
from tests.conftest import REPO

NOW = pd.Timestamp("2025-07-14T04:00:00Z")


class FakeClient:
    """Records reducer calls in order and answers the few SELECTs the actuator makes."""

    def __init__(self, status="proposed", params='{"target_setpoint_c": 29.0}'):
        self.calls: list[tuple] = []
        self.action = {"action_id": "a1", "appliance_id": "hvac", "status": status, "params_json": params}
        self.actuations: dict[str, dict] = {}

    def call(self, reducer, *args):
        self.calls.append((reducer, *args))
        if reducer == "accept_action":
            self.action["status"] = "accepted"
        if reducer == "begin_actuation":
            aid, action_id, hh, app, prev, req, applied, actor = args
            self.actuations[aid] = {"actuation_id": aid, "action_id": action_id, "appliance_id": app, "previous_c": prev,
                                    "applied_c": applied, "result": "pending", "actor": actor,
                                    "undo_expires_at_us": int((NOW + pd.Timedelta(hours=24)).value // 1000)}
        if reducer == "fail_actuation":
            self.actuations[args[0]]["result"] = args[1]

    def sql(self, q):
        if "FROM action " in q or "FROM action WHERE" in q:
            return pd.DataFrame([self.action])
        if "FROM appliance " in q or "FROM appliance WHERE" in q:
            return pd.DataFrame([{"min_setpoint_c": 18.0, "max_setpoint_c": 27.0, "max_step_c": 2.0, "label": "air conditioner"}])
        if "FROM actuation" in q:
            aid = re.search(r"actuation_id = '([^']+)'", q).group(1)
            return pd.DataFrame([self.actuations[aid]]) if aid in self.actuations else pd.DataFrame()
        raise AssertionError(q)


class FakeAdapter:
    def __init__(self, setpoint=24.0, read_at=NOW, fail=False, client=None):
        self.setpoint, self.read_at, self.fail, self.client = setpoint, read_at, fail, client
        self.commands: list[str] = []

    def read_state(self, appliance_id):
        return ThermostatState(appliance_id, self.setpoint, "cool", self.read_at, True)

    def set_setpoint(self, actuation_id):
        assert self.client.actuations[actuation_id]["result"] == "pending", "TRS-19-03: log row must exist first"
        if self.fail:
            raise DeviceUnavailable("no answer")
        self.commands.append(actuation_id)
        self.client.actuations[actuation_id]["result"] = "applied"
        self.setpoint = self.client.actuations[actuation_id]["applied_c"]


def make(**kw):
    c = FakeClient(**{k: v for k, v in kw.items() if k in ("status", "params")})
    a = FakeAdapter(client=c, **{k: v for k, v in kw.items() if k in ("setpoint", "read_at", "fail")})
    return c, a, Actuator(c, "hh", a, NOW)


def test_trs_19_02_clamped_to_bounds_and_two_degree_step_and_shown_before_command():
    assert clamp(24.0, 29.0, 18.0, 27.0, 2.0) == 26.0
    assert clamp(26.5, 29.0, 18.0, 27.0, 2.0) == 27.0
    c, a, act = make()
    p = act.preview("a1")
    assert (p.current_c, p.requested_c, p.applied_c, p.clamped) == (24.0, 29.0, 26.0, True)
    assert a.commands == [] and not any(x[0] == "begin_actuation" for x in c.calls)  # preview changes nothing


def test_trs_19_03_log_row_before_command_and_ledger_accept():
    c, a, act = make()
    r = act.confirm("a1")
    names = [x[0] for x in c.calls]
    assert names.index("accept_action") < names.index("begin_actuation")
    assert r.result == "applied" and a.setpoint == 26.0 and len(a.commands) == 1


def test_trs_19_05_refuses_stale_state():
    c, a, act = make(read_at=NOW - pd.Timedelta(minutes=6))
    with pytest.raises(ActuationRefused, match="5 minutes"):
        act.confirm("a1")
    assert a.commands == []


def test_cmp19_error_handling_failure_is_logged_not_retried_and_action_stays_accepted():
    c, a, act = make(fail=True)
    r = act.confirm("a1")
    assert r.result == "failed" and c.action["status"] == "accepted"
    assert [x[0] for x in c.calls].count("begin_actuation") == 1
    assert any(x[0] == "fail_actuation" and x[2] == "failed" for x in c.calls)


def test_trs_19_04_undo_restores_previous_through_the_same_path_with_actor_undo():
    c, a, act = make()
    r = act.confirm("a1")
    u = act.undo(r.actuation_id)
    assert u.result == "applied" and a.setpoint == 24.0
    begins = [x for x in c.calls if x[0] == "begin_actuation"]
    assert begins[-1][-1] == "undo"


def test_trs_19_01_set_setpoint_has_exactly_one_call_site_inside_the_actuator():
    hits = []
    for p in (REPO / "src").rglob("*.py"):
        for _m in re.finditer(r"\.set_setpoint\(", p.read_text()):
            hits.append(p.relative_to(REPO).as_posix())
    assert hits == ["src/homewatt/cmp19_actuator/actuator.py"]


def test_trs_19_01_no_scheduler_model_or_driver_imports_the_actuator():
    for p in (REPO / "src").rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith("src/homewatt/cmp19_actuator/") or rel == "src/homewatt/cmp15_api/app.py":
            continue
        assert "cmp19_actuator" not in p.read_text(), rel


def test_trs_19_03_module_apply_requires_a_pending_logged_actuation():
    src = (REPO / "spacetimedb" / "src" / "index.ts").read_text()
    body = src.split("export const applySetpoint")[1].split("export const failActuation")[0]
    assert "act.result !== 'pending'" in body and "ctx.db.actuation.actuationId.find(actuationId)" in body
    assert "TRS-19-01: actuations come only from a user tap or an undo" in src
