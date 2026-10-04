"""v0.11 TRS-19-10..12 and TRS-SYS-03: a tap installs a bounded, week-long precool schedule."""

import json

import numpy as np
import pandas as pd
import pytest

from homewatt.cmp06_synth.thermostat import schedule_setpoints
from homewatt.cmp19_actuator.actuator import ActuationRefused, ScheduleActuator, week_end_utc
from homewatt.cmp19_actuator.adapter import DeviceUnavailable, ThermostatState
from tests.conftest import REPO

NOW = pd.Timestamp("2025-07-21T04:00:00Z")  # Monday 00:00 Detroit
PARAMS = {"schedule": "precool", "pre_hours": 1.0, "pre_cool_c": 0.5, "peak_warm_c": 2.0, "weekdays_only": True,
          "pre_start": 14, "peak_start": 15, "peak_end": 19}


class FakeClient:
    def __init__(self, status="proposed"):
        self.calls: list[tuple] = []
        self.action = {"action_id": "a1", "appliance_id": "hvac", "status": status, "params_json": json.dumps(PARAMS), "week_id": "2025-W30"}
        self.schedules: dict[str, dict] = {}

    def call(self, reducer, *args):
        self.calls.append((reducer, *args))
        if reducer == "accept_action":
            self.action["status"] = "accepted"
        if reducer == "begin_schedule_install":
            spec = args[0]
            self.schedules[spec["schedule_id"]] = {**spec, "status": "pending", "undo_expires_at_us": int((NOW + pd.Timedelta(hours=24)).value // 1000)}
        if reducer == "begin_schedule_removal":
            self.schedules[args[0]]["status"] = "removing"
        if reducer == "fail_schedule":
            s = self.schedules[args[0]]
            s["status"] = "failed" if s["status"] == "pending" else "installed"

    def sql(self, q):
        if "FROM action " in q or "FROM action WHERE" in q:
            return pd.DataFrame([self.action])
        if "FROM appliance " in q or "FROM appliance WHERE" in q:
            return pd.DataFrame([{"min_setpoint_c": 18.0, "max_setpoint_c": 27.0, "max_step_c": 2.0, "label": "air conditioner"}])
        if "FROM household" in q:
            return pd.DataFrame([{"local_tz": "America/Detroit"}])
        if "FROM thermostat_schedule" in q:
            sid = q.split("schedule_id = '")[1].split("'")[0]
            return pd.DataFrame([self.schedules[sid]]) if sid in self.schedules else pd.DataFrame()
        raise AssertionError(q)


class FakeAdapter:
    def __init__(self, client, setpoint=26.0, fail=False):
        self.client, self.setpoint, self.fail = client, setpoint, fail
        self.commands: list[tuple[str, str]] = []

    def read_state(self, appliance_id):
        return ThermostatState(appliance_id, self.setpoint, "cool", NOW, True)

    def install_schedule(self, sid):
        assert self.client.schedules[sid]["status"] == "pending", "TRS-19-03: log row before the command"
        if self.fail:
            raise DeviceUnavailable("no answer")
        self.client.schedules[sid]["status"] = "installed"
        self.commands.append(("install", sid))

    def remove_schedule(self, sid):
        assert self.client.schedules[sid]["status"] == "removing", "TRS-19-03: removal logged first"
        self.client.schedules[sid]["status"] = "removed"
        self.commands.append(("remove", sid))


def _act(status="proposed", **kw):
    c = FakeClient(status)
    ad = FakeAdapter(c, **kw)
    return c, ad, ScheduleActuator(c, "hh", ad, NOW)


def test_trs_19_10_schedule_is_weekday_only_and_clamped_to_bounds_and_step():
    ts = pd.date_range("2025-07-25 00:00", "2025-07-26 23:00", freq="h", tz="America/Detroit")  # Fri, Sat
    sp = schedule_setpoints(ts, np.full(len(ts), 26.0), 15, 19, 2, 3.0, 2.0, 18.0, 27.0, 2.0)
    fri, sat = sp[:24], sp[24:]
    assert fri[13] == fri[14] == 24.0  # 3 °C asked, step limit 2
    assert all(fri[h] == 27.0 for h in range(15, 19))  # 28 asked, bound 27
    assert fri[12] == fri[19] == 26.0 and (sat == 26.0).all()


def test_trs_19_08_preview_states_both_setpoints_and_the_week_end_without_changing_anything():
    c, ad, act = _act()
    p = act.preview_schedule("a1")
    assert (p.current_c, p.pre_c, p.peak_c) == (26.0, 25.5, 27.0)
    assert (p.pre_start, p.peak_start, p.peak_end) == (14, 15, 19)
    assert p.valid_until == pd.Timestamp("2025-07-28 00:00", tz="America/Detroit").tz_convert("UTC")
    assert c.calls == [] and ad.commands == []


def test_trs_19_11_week_end_is_the_monday_after_the_actions_week():
    assert week_end_utc("2025-W30", "America/Detroit") == pd.Timestamp("2025-07-28T04:00:00Z")


def test_trs_19_12_confirm_accepts_logs_then_installs_with_clamped_offsets():
    c, ad, act = _act()
    r = act.confirm_schedule("a1")
    assert r.result == "installed" and ad.commands == [("install", r.schedule_id)]
    names = [x[0] for x in c.calls]
    assert names.index("accept_action") < names.index("begin_schedule_install")
    spec = c.schedules[r.schedule_id]
    assert (spec["pre_cool_c"], spec["peak_warm_c"]) == (0.5, 1.0)  # 26 + 2 clamped to 27
    assert spec["valid_until_us"] == int(pd.Timestamp("2025-07-28T04:00:00Z").value // 1000)


def test_trs_19_error_handling_failed_install_is_logged_and_action_stays_accepted():
    c, ad, act = _act(fail=True)
    r = act.confirm_schedule("a1")
    assert r.result == "failed" and c.schedules[r.schedule_id]["status"] == "failed"
    assert c.action["status"] == "accepted"


def test_trs_19_12_undo_within_24h_removes_and_is_logged_as_undo():
    c, ad, act = _act()
    sid = act.confirm_schedule("a1").schedule_id
    r = act.undo_schedule(sid)
    assert r.result == "removed" and ("begin_schedule_removal", sid, "undo") in c.calls
    late = ScheduleActuator(c, "hh", ad, NOW + pd.Timedelta(hours=25))
    c.schedules[sid]["status"] = "installed"
    with pytest.raises(ActuationRefused, match="24-hour"):
        late.undo_schedule(sid)


def test_trs_19_01_a_non_schedule_action_cannot_install_one():
    c, ad, act = _act()
    c.action["params_json"] = json.dumps({"target_setpoint_c": 27.0})
    with pytest.raises(ActuationRefused):
        act.preview_schedule("a1")


def test_trs_19_static_install_and_remove_are_called_only_inside_the_actuator():
    src = REPO / "src" / "homewatt"
    for name in ("install_schedule(", "remove_schedule("):
        callers = [p.relative_to(src).as_posix() for p in src.rglob("*.py") if f".{name}" in p.read_text()]
        assert callers == ["cmp19_actuator/actuator.py"], (name, callers)


class _ScheduleClient:
    def __init__(self, rows):
        self.rows = rows

    def sql(self, q):
        assert "FROM thermostat_schedule" in q
        return pd.DataFrame(self.rows)


def _row(**kw):
    base = {"status": "installed", "ts_us": 1, "valid_from_us": int(NOW.value // 1000),
            "valid_until_us": int(pd.Timestamp("2025-07-28T04:00:00Z").value // 1000), "removed_at_us": 0,
            "pre_start_hour": 14, "peak_start_hour": 15, "peak_end_hour": 19, "pre_cool_c": 1.0, "peak_warm_c": 1.0,
            "min_c": 18.0, "max_c": 27.0, "max_step_c": 2.0, "weekdays_only": True}
    return base | kw


def _steps(start, days):
    return pd.date_range(start, periods=days * 1440, freq="60s", tz="UTC")


def test_trs_19_07_simulated_device_runs_the_schedule_on_weekdays_and_stops_at_week_end():
    from homewatt.demo.driver import apply_schedules

    ts = _steps("2025-07-26T04:00:00Z", 3)  # Sat, Sun, Mon (next week) local
    sp, changed = apply_schedules(_ScheduleClient([_row()]), "hh", ts, np.full(len(ts), 26.0), "America/Detroit")
    assert changed and (sp == 26.0).all()  # weekend, then the schedule has ended
    ts = _steps("2025-07-21T04:00:00Z", 1)  # Monday
    sp, _ = apply_schedules(_ScheduleClient([_row()]), "hh", ts, np.full(len(ts), 26.0), "America/Detroit")
    local = ts.tz_convert("America/Detroit")
    assert set(sp[local.hour == 14]) == {25.0} and set(sp[(local.hour >= 15) & (local.hour < 19)]) == {27.0}
    assert set(sp[local.hour == 12]) == {26.0}


def test_trs_19_12_an_undone_schedule_stops_at_the_undo():
    from homewatt.demo.driver import apply_schedules

    undo = pd.Timestamp("2025-07-21T12:00:00Z")  # Monday 08:00 local, before the first precool
    rows = [_row(status="removed", removed_at_us=int(undo.value // 1000))]
    ts = _steps("2025-07-21T04:00:00Z", 1)
    sp, _ = apply_schedules(_ScheduleClient(rows), "hh", ts, np.full(len(ts), 26.0), "America/Detroit")
    assert (sp == 26.0).all()
