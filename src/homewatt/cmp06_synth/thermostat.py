"""TRS-06-07 thermostat model. Deterministic, vectorised at a 60 s step and repeated to 2 s.

Compressor of p_hvac_w cycles on while indoor temperature is above setpoint + hysteresis and off
below setpoint - hysteresis. Indoor temperature follows outdoor through a first-order lag
(time constant tau_h) and falls at cooling_rate_c_per_h while the compressor runs. Below
min_outdoor_c outdoor the track is zero (no heating in V1).

The setpoint may be a scalar or a per-step array, so CMP-19 can override it from an actuation
timestamp forward (TRS-19-07).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from homewatt.cmp06_synth.profile import ThermostatParams

if TYPE_CHECKING:
    import pandas as pd

STEP_S = 60
STEPS_PER_HOUR = 3600 // STEP_S


@dataclass
class ThermostatResult:
    p_w: np.ndarray  # compressor power per step (W)
    indoor_c: np.ndarray  # indoor temperature per step
    on: np.ndarray  # bool per step


def simulate(
    outdoor_c: np.ndarray,
    params: ThermostatParams,
    setpoint_c: float | np.ndarray | None = None,
    indoor0_c: float | None = None,
) -> ThermostatResult:
    """outdoor_c is per STEP_S step. Returns arrays of the same length."""
    n = len(outdoor_c)
    sp = np.broadcast_to(
        np.asarray(params.setpoint_c if setpoint_c is None else setpoint_c, dtype=np.float64), (n,)
    )
    dt_h = STEP_S / 3600.0
    alpha = dt_h / params.tau_h
    indoor = np.empty(n)
    on = np.zeros(n, dtype=bool)
    t_in = float(outdoor_c[0] if indoor0_c is None else indoor0_c)
    state = False
    for i in range(n):
        t_out = outdoor_c[i]
        if t_out < params.min_outdoor_c:
            state = False
        elif t_in > sp[i] + params.hysteresis_c:
            state = True
        elif t_in < sp[i] - params.hysteresis_c:
            state = False
        on[i] = state
        t_in += alpha * (t_out - t_in) - (params.cooling_rate_c_per_h * dt_h if state else 0.0)
        indoor[i] = t_in
    p = np.where(on, params.p_hvac_w, 0.0)
    return ThermostatResult(p, indoor, on)


def default_harmonic_profile(vrms_v: float, power_factor: float) -> np.ndarray:
    """Amps per watt for h1..h32: fundamental = 1/(vrms*pf); odd harmonics decay as 1/k^1.6;
    even harmonics near zero. A compressor's current is mostly fundamental."""
    prof = np.zeros(32)
    fund = 1.0 / (vrms_v * power_factor)
    for k in range(1, 33):
        if k % 2 == 1:
            prof[k - 1] = fund / (k**1.6)
        else:
            prof[k - 1] = fund * 0.005
    return prof


def expand_to_samples(x: np.ndarray, samples_per_step: int, n_samples: int) -> np.ndarray:
    return np.repeat(x, samples_per_step)[:n_samples]


def schedule_setpoints(
    local_ts: pd.DatetimeIndex,
    base_c: np.ndarray,
    peak_start: int,
    peak_end: int,
    pre_hours: int,
    pre_cool_c: float,
    peak_warm_c: float,
    lo_c: float,
    hi_c: float,
    max_step_c: float,
    weekdays_only: bool = True,
) -> np.ndarray:
    """TRS-19-10 (v0.11) precool schedule: on weekdays, base − pre_cool_c from peak_start − pre_hours
    to peak_start and base + peak_warm_c from peak_start to peak_end; base otherwise. Every value is
    clamped to [lo_c, hi_c] and to max_step_c from the base (TRS-19-02). One function for pricing
    (CMP-13), the device preview (CMP-19) and the simulated device (TRS-19-07)."""
    base = np.asarray(base_c, dtype=np.float64)
    sp = base.copy()
    h = np.asarray(local_ts.hour)
    day = np.asarray(local_ts.weekday < 5) if weekdays_only else np.ones(len(local_ts), dtype=bool)
    pre = day & (h >= peak_start - pre_hours) & (h < peak_start)
    peak = day & (h >= peak_start) & (h < peak_end)
    sp[pre] = base[pre] - pre_cool_c
    sp[peak] = base[peak] + peak_warm_c
    sp = np.clip(sp, lo_c, hi_c)
    return np.clip(sp, base - max_step_c, base + max_step_c)
