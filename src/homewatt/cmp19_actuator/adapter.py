"""TRS-19-06: one device interface, two implementations. Nothing else differs between them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class ThermostatState:
    appliance_id: str
    current_setpoint_c: float
    mode: str
    read_at: pd.Timestamp
    simulated: bool


class DeviceUnavailable(RuntimeError):
    pass


class ThermostatAdapter(Protocol):
    def read_state(self, appliance_id: str) -> ThermostatState: ...

    def set_setpoint(self, actuation_id: str) -> None:
        """Apply the logged, pending actuation. Raises DeviceUnavailable on failure."""


class SimulatedThermostat:
    """V1 adapter: the thermostat is a row in the store (TRS-19-09 'simulated')."""

    def __init__(self, client, household_id: str):
        self.client = client
        self.household_id = household_id

    def read_state(self, appliance_id: str) -> ThermostatState:
        from homewatt.spacetime import SpacetimeError, from_us

        try:
            self.client.call("poll_thermostat", self.household_id, appliance_id)
        except SpacetimeError as e:
            raise DeviceUnavailable(str(e)) from e
        df = self.client.sql(f"SELECT * FROM thermostat_state WHERE household_id = '{self.household_id}' AND appliance_id = '{appliance_id}'")
        if df.empty:
            raise DeviceUnavailable(f"no thermostat {appliance_id}")
        r = df.iloc[0]
        return ThermostatState(appliance_id, float(r["current_setpoint_c"]), str(r["mode"]), from_us(int(r["read_at_us"])), bool(r["simulated"]))

    def set_setpoint(self, actuation_id: str) -> None:
        from homewatt.spacetime import SpacetimeError

        try:
            self.client.call("apply_setpoint", actuation_id)
        except SpacetimeError as e:
            raise DeviceUnavailable(str(e)) from e


class SdmThermostat:
    """Production adapter for Google Nest via Smart Device Management. Not built (OI-08)."""

    def read_state(self, appliance_id: str) -> ThermostatState:
        raise NotImplementedError("SDM adapter not built in V1 (OI-08)")

    def set_setpoint(self, actuation_id: str) -> None:
        raise NotImplementedError("SDM adapter not built in V1 (OI-08)")
