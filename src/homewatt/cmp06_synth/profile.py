"""Schedule profile YAML (TRS-06-02, TRS-06-09). One file per synthetic household."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from homewatt.schema import ApplianceType


class Window(BaseModel):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)  # half-open, local time
    weight: float = Field(gt=0, default=1.0)


class ApplianceSchedule(BaseModel):
    type: ApplianceType
    label: str
    #: event: uses placed in windows; cycling: activations chained with off gaps (compressor-style);
    #: continuous: activations chained back to back with no gap (what the dataset's fridge and
    #: laptop charger actually do: constant draw for the whole session).
    mode: Literal["event", "cycling", "continuous"] = "event"
    #: event mode: mean number of uses per day (Poisson); scaled by the weekday/weekend multipliers
    uses_per_day: float = 1.0
    windows: list[Window] = Field(default_factory=lambda: [Window(start_hour=0, end_hour=24)])
    weekday_mult: float = 1.0
    weekend_mult: float = 1.0
    #: cycling mode: off gap between activations, seconds, uniform in [min, max]
    off_gap_s: tuple[float, float] = (900.0, 2400.0)
    #: When set, an activation longer than max is replaced by a random contiguous slice of
    #: uniform length in [min, max] seconds. Needed because whole-session draws (fridge, laptop,
    #: screen) come out of CMP-00 as one 5-8 h activation.
    slice_s: tuple[float, float] | None = None
    #: optional: extra uses per day per °C above 24 °C outdoor (daily mean), e.g. for fans
    temp_sensitivity_per_c: float = 0.0

    @field_validator("windows")
    @classmethod
    def _windows_valid(cls, v: list[Window]) -> list[Window]:
        for w in v:
            if w.end_hour <= w.start_hour:
                raise ValueError(f"window end_hour must exceed start_hour: {w}")
        return v


class ThermostatParams(BaseModel):
    """TRS-06-07 defaults. Cooling only in V1; below min_outdoor_c the track is zero."""

    enabled: bool = True
    appliance_id: str = "hvac"
    label: str = "air conditioner"
    p_hvac_w: float = 3000.0
    setpoint_c: float = 24.0
    hysteresis_c: float = 0.5
    tau_h: float = 4.0  # indoor temperature first-order lag toward outdoor
    cooling_rate_c_per_h: float = 1.5  # indoor cooling while the compressor runs
    min_outdoor_c: float = 15.0
    power_factor: float = 0.90
    #: TRS-06-08 fixed harmonic profile: amps per watt of p_active for h1..h32. "default" uses a
    #: decaying odd-harmonic shape derived from p/(vrms*pf).
    harmonic_profile: list[float] | Literal["default"] = "default"
    #: CMP-19 device bounds (TRS-19-02)
    min_setpoint_c: float = 18.0
    max_setpoint_c: float = 27.0
    max_step_c: float = 2.0


class Profile(BaseModel):
    household_id: str = "hh-demo"
    local_tz: str = "America/Detroit"
    vrms_v: float = 240.0
    baseload_w: float = 60.0  # TRS-06-01 constant baseload
    noise_w: float = 3.0  # TRS-06-01 zero-mean Gaussian noise std dev
    appliances: dict[str, ApplianceSchedule]
    thermostat: ThermostatParams = Field(default_factory=ThermostatParams)

    @classmethod
    def load(cls, path: Path) -> Profile:
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def fingerprint(self) -> str:
        import hashlib

        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
