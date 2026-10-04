"""The only code that commands a device. Every command:
  1. reads device state; refuses if older than 5 minutes or unreachable (TRS-19-05),
  2. clamps to the household's bounds and step limit (TRS-19-02),
  3. writes the log row (begin_actuation) BEFORE the command (TRS-19-03),
  4. sends the command (adapter.set_setpoint) and records the result,
and an undo restores previous_c through the same path, logged with actor 'undo' (TRS-19-04).
v0.11: a schedule action (precool) installs a bounded, week-long schedule the same way: fresh state,
clamped values shown first, the schedule row written 'pending' before install_schedule, and undo
within 24 h removes it (TRS-19-10..12). Nothing here runs on a timer; the device ends the schedule.
Adapter errors are logged and reported, never retried automatically.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass

import pandas as pd

from homewatt.cmp19_actuator.adapter import DeviceUnavailable, ThermostatAdapter

STALE_AFTER = pd.Timedelta(minutes=5)  # TRS-19-05
UNDO_WINDOW = pd.Timedelta(hours=24)  # TRS-19-04


class ActuationRefused(RuntimeError):
    pass


@dataclass
class Preview:
    action_id: str
    appliance_id: str
    device_label: str
    current_c: float
    requested_c: float
    applied_c: float
    clamped: bool
    simulated: bool


@dataclass
class Result:
    actuation_id: str
    result: str
    previous_c: float
    applied_c: float
    error: str = ""


def clamp(current: float, requested: float, lo: float, hi: float, max_step: float) -> float:
    """TRS-19-02: within [lo, hi] and at most max_step from the current setpoint."""
    v = min(max(requested, lo), hi)
    v = min(max(v, current - max_step), current + max_step)
    return round(v, 1)


class Actuator:
    def __init__(self, client, household_id: str, adapter: ThermostatAdapter, now: pd.Timestamp):
        self.client = client
        self.household_id = household_id
        self.adapter = adapter
        self.now = now

    def _action(self, action_id: str) -> pd.Series:
        df = self.client.sql(f"SELECT * FROM action WHERE action_id = '{action_id}'")
        if df.empty:
            raise ActuationRefused(f"no action {action_id}")
        return df.iloc[0]

    def _bounds(self, appliance_id: str) -> tuple[float, float, float, str]:
        df = self.client.sql(f"SELECT * FROM appliance WHERE household_id = '{self.household_id}' AND appliance_id = '{appliance_id}'")
        if df.empty:
            raise ActuationRefused(f"no appliance {appliance_id}")
        r = df.iloc[0]
        lo, hi, step = float(r["min_setpoint_c"]), float(r["max_setpoint_c"]), float(r["max_step_c"])
        if hi <= lo:  # TRS-19-02 defaults
            lo, hi, step = 18.0, 27.0, 2.0
        return lo, hi, step or 2.0, str(r["label"])

    def _state(self, appliance_id: str):
        try:
            st = self.adapter.read_state(appliance_id)
        except DeviceUnavailable as e:
            raise ActuationRefused(f"the thermostat did not answer: {e}") from e
        if self.now - st.read_at > STALE_AFTER:
            raise ActuationRefused("the thermostat's last reading is more than 5 minutes old")
        return st

    def preview(self, action_id: str) -> Preview:
        """First tap (TRS-19-08): state the device, current and target setpoint. No state change."""
        a = self._action(action_id)
        params = json.loads(a["params_json"])
        if "target_setpoint_c" not in params:
            raise ActuationRefused("this action does not change a device")
        st = self._state(a["appliance_id"])
        lo, hi, step, label = self._bounds(a["appliance_id"])
        req = float(params["target_setpoint_c"])
        applied = clamp(st.current_setpoint_c, req, lo, hi, step)
        return Preview(action_id, str(a["appliance_id"]), label, st.current_setpoint_c, req, applied, applied != req, st.simulated)

    def _execute(self, action_id: str, appliance_id: str, previous: float, requested: float, applied: float, actor: str) -> Result:
        aid = str(uuid.uuid4())
        self.client.call("begin_actuation", aid, action_id, self.household_id, appliance_id, previous, requested, applied, actor)
        try:
            self.adapter.set_setpoint(aid)
        except DeviceUnavailable as e:
            self.client.call("fail_actuation", aid, "failed", str(e)[:300])
            return Result(aid, "failed", previous, applied, str(e))
        return Result(aid, "applied", previous, applied)

    def confirm(self, action_id: str) -> Result:
        """Second tap: accept the action (ledger) and apply the clamped setpoint (TRS-19-01).
        A failed command leaves the action accepted so the user can retry."""
        from homewatt.cmp17_ledger.ledger import accept

        a = self._action(action_id)
        if a["status"] not in ("proposed", "accepted"):
            raise ActuationRefused(f"action is {a['status']}")
        p = self.preview(action_id)
        if a["status"] == "proposed":
            accept(self.client, action_id)
        return self._execute(action_id, p.appliance_id, p.current_c, p.requested_c, p.applied_c, "user")

    def undo(self, actuation_id: str) -> Result:
        df = self.client.sql(f"SELECT * FROM actuation WHERE actuation_id = '{actuation_id}'")
        if df.empty:
            raise ActuationRefused(f"no actuation {actuation_id}")
        act = df.iloc[0]
        if act["result"] != "applied" or act["actor"] != "user":
            raise ActuationRefused("only an applied change can be undone")
        if self.now >= pd.Timestamp(int(act["undo_expires_at_us"]), unit="us", tz="UTC"):
            raise ActuationRefused("the 24-hour undo window has passed")
        st = self._state(str(act["appliance_id"]))
        prev = float(act["previous_c"])
        return self._execute(str(act["action_id"]), str(act["appliance_id"]), st.current_setpoint_c, prev, prev, "undo")


@dataclass
class SchedulePreview:
    action_id: str
    appliance_id: str
    device_label: str
    current_c: float
    pre_c: float
    peak_c: float
    pre_start: int
    peak_start: int
    peak_end: int
    weekdays_only: bool
    valid_until: pd.Timestamp  # UTC, end of the action's week (TRS-19-11)
    simulated: bool


@dataclass
class ScheduleResult:
    schedule_id: str
    result: str  # installed | failed | removed
    error: str = ""


def week_end_utc(week_id: str, tz: str) -> pd.Timestamp:
    """Monday 00:00 local after ISO week `week_id` (TRS-17-06), in UTC."""
    monday = pd.Timestamp.fromisocalendar(int(week_id[:4]), int(week_id[6:]), 1)
    return (pd.Timestamp(monday, tz=tz) + pd.Timedelta(days=7)).tz_convert("UTC")


class ScheduleActuator(Actuator):
    def _tz(self) -> str:
        df = self.client.sql(f"SELECT * FROM household WHERE household_id = '{self.household_id}'")
        if df.empty or not str(df.iloc[0]["local_tz"]):
            raise ActuationRefused(f"household {self.household_id} has no time zone")
        return str(df.iloc[0]["local_tz"])

    def preview_schedule(self, action_id: str) -> SchedulePreview:
        """First tap (TRS-19-08): both setpoints, the hours and the end date. No state change."""
        a = self._action(action_id)
        p = json.loads(a["params_json"])
        if p.get("schedule") != "precool":
            raise ActuationRefused("this action does not install a schedule")
        st = self._state(a["appliance_id"])
        lo, hi, step, label = self._bounds(a["appliance_id"])
        cur = st.current_setpoint_c
        pre = clamp(cur, cur - float(p["pre_cool_c"]), lo, hi, step)
        peak = clamp(cur, cur + float(p["peak_warm_c"]), lo, hi, step)
        return SchedulePreview(action_id, str(a["appliance_id"]), label, cur, pre, peak, int(p["pre_start"]), int(p["peak_start"]),
                               int(p["peak_end"]), bool(p.get("weekdays_only", True)), week_end_utc(str(a["week_id"]), self._tz()), st.simulated)

    def confirm_schedule(self, action_id: str) -> ScheduleResult:
        """Second tap: accept the action and install the schedule. A failed install leaves the action
        accepted so the user can retry; nothing retries on its own."""
        from homewatt.cmp17_ledger.ledger import accept
        from homewatt.spacetime import SpacetimeError, us

        a = self._action(action_id)
        if a["status"] not in ("proposed", "accepted"):
            raise ActuationRefused(f"action is {a['status']}")
        pv = self.preview_schedule(action_id)
        lo, hi, step, _ = self._bounds(pv.appliance_id)
        sid = str(uuid.uuid4())
        spec = {
            "schedule_id": sid, "action_id": action_id, "household_id": self.household_id, "appliance_id": pv.appliance_id,
            "kind": "precool", "weekdays_only": pv.weekdays_only, "pre_start_hour": pv.pre_start, "peak_start_hour": pv.peak_start,
            "peak_end_hour": pv.peak_end, "pre_cool_c": round(pv.current_c - pv.pre_c, 1), "peak_warm_c": round(pv.peak_c - pv.current_c, 1),
            "min_c": lo, "max_c": hi, "max_step_c": step, "valid_until_us": us(pv.valid_until),
        }
        if a["status"] == "proposed":
            accept(self.client, action_id)
        try:
            self.client.call("begin_schedule_install", spec)  # TRS-19-03: log before the command
        except SpacetimeError as e:
            raise ActuationRefused(str(e)) from e
        try:
            self.adapter.install_schedule(sid)
        except DeviceUnavailable as e:
            self.client.call("fail_schedule", sid, str(e)[:300])
            return ScheduleResult(sid, "failed", str(e))
        return ScheduleResult(sid, "installed")

    def undo_schedule(self, schedule_id: str) -> ScheduleResult:
        df = self.client.sql(f"SELECT * FROM thermostat_schedule WHERE schedule_id = '{schedule_id}'")
        if df.empty:
            raise ActuationRefused(f"no schedule {schedule_id}")
        s = df.iloc[0]
        if s["status"] != "installed":
            raise ActuationRefused(f"the schedule is {s['status']}")
        if self.now >= pd.Timestamp(int(s["undo_expires_at_us"]), unit="us", tz="UTC"):
            raise ActuationRefused("the 24-hour undo window has passed")
        self._state(str(s["appliance_id"]))  # TRS-19-05
        self.client.call("begin_schedule_removal", schedule_id, "undo")
        try:
            self.adapter.remove_schedule(schedule_id)
        except DeviceUnavailable as e:
            self.client.call("fail_schedule", schedule_id, str(e)[:300])
            return ScheduleResult(schedule_id, "failed", str(e))
        return ScheduleResult(schedule_id, "removed")


def as_dict(x) -> dict:
    return asdict(x)
