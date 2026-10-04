"""The four action shapes of TRS-13-01. Each takes an hourly kWh series (tz-aware UTC index)
and returns the counterfactual series. Energy-preserving where the TRS says so."""

from __future__ import annotations

import numpy as np
import pandas as pd

from homewatt.cmp04_tariff.model import Tariff
from homewatt.cmp06_synth import thermostat as thermo
from homewatt.cmp06_synth.profile import ThermostatParams


def _local(kwh: pd.Series, tariff: Tariff) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(kwh.index).tz_convert(tariff.tz)


def shift(kwh: pd.Series, tariff: Tariff, to_hour: int | None = None, to: str | None = None) -> pd.Series:
    """Move each local day's peak-window kWh into target hours, energy-preserving.
    to_hour: spread evenly over off-peak hours >= to_hour on the same local day (A.3: never into
    a peak period). to='pre_peak_2h': the two hours before the peak window."""
    out = kwh.astype(float).copy()
    local = _local(kwh, tariff)
    days = pd.Series(local.date, index=kwh.index)
    hours = pd.Series(local.hour, index=kwh.index)
    for d in days.unique():
        win = tariff.peak_window(d)
        if win is None:
            continue
        ps, pe = win
        mask_day = days == d
        in_peak = mask_day & (hours >= ps) & (hours < pe)
        energy = float(out[in_peak].sum())
        if energy <= 0:
            continue
        if to == "pre_peak_2h":
            target = mask_day & (hours >= ps - 2) & (hours < ps)
        else:
            assert to_hour is not None
            target = mask_day & (hours >= to_hour) & ~((hours >= ps) & (hours < pe))
        if not target.any():
            continue  # no permitted target hour on this day: leave the day unchanged
        out[in_peak] = 0.0
        out[target] += energy / int(target.sum())
    return out


def trim(kwh: pd.Series, factor: float) -> pd.Series:
    return kwh.astype(float) * float(factor)


def setpoint_factor(weather_temp_c: pd.Series, params: ThermostatParams, current_setpoint_c: float, delta_c: float) -> float:
    """TRS-06-07 thermostat model run over the horizon weather at the current setpoint and at
    current + delta: ratio of compressor on-time. Shared with CMP-19 (TRS-19-07)."""
    temp = weather_temp_c.to_numpy(dtype=float)
    if len(temp) == 0:
        return 1.0
    step = np.repeat(temp, thermo.STEPS_PER_HOUR)  # hourly -> per 60 s step
    base = thermo.simulate(step, params, current_setpoint_c, indoor0_c=float(step[0]))
    new = thermo.simulate(step, params, current_setpoint_c + delta_c, indoor0_c=float(step[0]))
    on_base = float(base.on.mean())
    if on_base <= 0:
        return 1.0
    return float(min(1.0, new.on.mean() / on_base))


def setpoint(kwh: pd.Series, factor: float) -> pd.Series:
    return kwh.astype(float) * float(factor)


def maintenance(kwh: pd.Series, factor: float) -> pd.Series:
    return kwh.astype(float) * float(factor)
