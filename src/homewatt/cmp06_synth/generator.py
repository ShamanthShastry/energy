"""TRS-06-01 .. TRS-06-09 timeline generator.

Everything random goes through one numpy Generator seeded once (TRS-06-03); the same seed,
library fingerprint and profile fingerprint reproduce the same files byte for byte.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from homewatt.cmp00_activations.library import ActivationLibrary
from homewatt.cmp06_synth import thermostat as thermo
from homewatt.cmp06_synth.behaviour import Behaviour
from homewatt.cmp06_synth.fault import Fault
from homewatt.cmp06_synth.profile import ApplianceSchedule, Profile
from homewatt.schema import (
    IDX_H1,
    IDX_IRMS,
    IDX_P_ACTIVE,
    IDX_PF,
    IDX_VRMS,
    NUMERIC_FIELDS,
    ON_THRESHOLD_W,
    SAMPLE_PERIOD_S,
)

log = logging.getLogger(__name__)

SAMPLES_PER_DAY = int(86400 / SAMPLE_PERIOD_S)  # 43,200
SAMPLES_PER_STEP = int(thermo.STEP_S / SAMPLE_PERIOD_S)  # 30


@dataclass
class Timeline:
    aggregate: pd.DataFrame  # household_id, ts, 36 numeric fields
    truth: pd.DataFrame  # ts, <appliance_id>_w per appliance, baseload_w, fault_active, labelled
    meta: dict = field(default_factory=dict)


def _local_hour_of_sample(ts_utc: np.ndarray, tz: ZoneInfo) -> np.ndarray:
    """Local hour (float) for each sample. UTC offset evaluated per day (DST changes at 02:00
    local are rounded to the day boundary; acceptable for a schedule model)."""
    ts = pd.DatetimeIndex(ts_utc).tz_convert(tz)
    return (ts.hour + ts.minute / 60 + ts.second / 3600).to_numpy()


def _pick(acts: list[np.ndarray], sched: ApplianceSchedule, rng: np.random.Generator) -> np.ndarray:
    """Pick an activation; if the schedule slices, cut a random contiguous piece of it."""
    act = acts[rng.integers(len(acts))]
    if sched.slice_s is None:
        return act
    lo, hi = (int(x / SAMPLE_PERIOD_S) for x in sched.slice_s)
    if len(act) <= hi:
        return act
    n = int(rng.integers(lo, hi + 1))
    s0 = int(rng.integers(0, len(act) - n + 1))
    return act[s0 : s0 + n]


def _place(track: np.ndarray, start: int, act: np.ndarray) -> int:
    """Add an activation (n, 36) into track (N, 36) at sample `start`, clipped. Returns n placed."""
    n = min(len(act), len(track) - start)
    if n <= 0:
        return 0
    track[start : start + n] += act[:n]
    return n


def _event_track(
    sched: ApplianceSchedule,
    acts: list[np.ndarray],
    n: int,
    days: int,
    day_dow: np.ndarray,
    day_mean_temp: np.ndarray,
    rng: np.random.Generator,
    local_hour: np.ndarray,
    fault: Fault | None,
    appliance_id: str,
) -> tuple[np.ndarray, np.ndarray]:
    track = np.zeros((n, len(NUMERIC_FIELDS)), dtype=np.float32)
    fault_mask = np.zeros(n, dtype=bool)
    weights = np.array([w.weight for w in sched.windows])
    weights = weights / weights.sum()
    for d in range(days):
        mult = sched.weekend_mult if day_dow[d] >= 5 else sched.weekday_mult
        lam = sched.uses_per_day * mult + sched.temp_sensitivity_per_c * max(
            0.0, day_mean_temp[d] - 24.0
        )
        k = rng.poisson(lam)
        day0 = d * SAMPLES_PER_DAY
        day_hours = local_hour[day0 : day0 + SAMPLES_PER_DAY]
        for _ in range(k):
            w = sched.windows[rng.choice(len(weights), p=weights)]
            # samples of this day whose local hour falls in the window
            cand = np.flatnonzero((day_hours >= w.start_hour) & (day_hours < w.end_hour))
            if cand.size == 0:
                continue
            start = day0 + int(cand[rng.integers(cand.size)])
            act = _pick(acts, sched, rng)
            if fault is not None and fault.kind == "power" and fault.active_on_day(d):
                act = act * np.float32(1.0 + fault.magnitude)
                placed = _place(track, start, act)
                fault_mask[start : start + placed] = True
            else:
                _place(track, start, act)
    return track, fault_mask


def _cycling_track(
    sched: ApplianceSchedule,
    acts: list[np.ndarray],
    n: int,
    rng: np.random.Generator,
    fault: Fault | None,
    appliance_id: str,
) -> tuple[np.ndarray, np.ndarray]:
    track = np.zeros((n, len(NUMERIC_FIELDS)), dtype=np.float32)
    fault_mask = np.zeros(n, dtype=bool)
    continuous = sched.mode == "continuous"
    lo, hi = (0.0, 0.0) if continuous else sched.off_gap_s
    pos = 0 if continuous else int(rng.uniform(0, hi) / SAMPLE_PERIOD_S)  # random phase
    while pos < n:
        act = _pick(acts, sched, rng)
        day = pos // SAMPLES_PER_DAY
        gap_s = 0.0 if continuous else rng.uniform(lo, hi)
        scale = np.float32(1.0)
        faulty = fault is not None and fault.active_on_day(day)
        if faulty and fault.kind == "duty_cycle":
            # duty' = duty*(1+m)  =>  off' = (on+off)/(1+m) - on
            on_s = len(act) * SAMPLE_PERIOD_S
            gap_s = max(0.0, (on_s + gap_s) / (1.0 + fault.magnitude) - on_s)
        elif faulty and fault.kind == "power":
            scale = np.float32(1.0 + fault.magnitude)
        placed = _place(track, pos, act * scale if scale != 1.0 else act)
        if faulty:
            fault_mask[pos : pos + placed] = True
        pos += len(act) + int(round(gap_s / SAMPLE_PERIOD_S))
    return track, fault_mask


def generate(
    profile: Profile,
    library: ActivationLibrary,
    weather: pd.DataFrame,
    start_local: datetime,
    days: int,
    seed: int,
    fault: Fault | None = None,
    setpoint_override: np.ndarray | None = None,
    behaviours: list[Behaviour] | None = None,
) -> Timeline:
    """Build `days` days from `start_local` (naive local date-time in profile.local_tz)."""
    tz = ZoneInfo(profile.local_tz)
    rng = np.random.default_rng(seed)
    n = days * SAMPLES_PER_DAY
    start_utc = start_local.replace(tzinfo=tz).astimezone(ZoneInfo("UTC"))
    ts = pd.date_range(start_utc, periods=n, freq=f"{int(SAMPLE_PERIOD_S)}s", tz="UTC")
    local_hour = _local_hour_of_sample(ts, tz)
    day_dow = np.array([(start_local + timedelta(days=d)).weekday() for d in range(days)])

    # hourly weather -> per 60 s step (linear interpolation), then per sample for daily means
    w = weather.sort_values("ts").set_index("ts")["temp_c"]
    step_ts = pd.date_range(
        start_utc, periods=n // SAMPLES_PER_STEP, freq=f"{thermo.STEP_S}s", tz="UTC"
    )
    if w.index[0] > step_ts[0] or w.index[-1] < step_ts[-1]:
        raise ValueError(
            f"weather covers {w.index[0]}..{w.index[-1]}, timeline needs {step_ts[0]}..{step_ts[-1]}"
        )
    temp_step = np.interp(
        step_ts.as_unit("ns").asi8, w.index.as_unit("ns").asi8, w.to_numpy(dtype=np.float64)
    )
    day_mean_temp = temp_step.reshape(days, -1).mean(axis=1)

    tracks: dict[str, np.ndarray] = {}
    fault_mask = np.zeros(n, dtype=bool)
    if (
        fault is not None
        and fault.appliance_id not in profile.appliances
        and fault.appliance_id != profile.thermostat.appliance_id
    ):
        raise ValueError(f"fault names unknown appliance '{fault.appliance_id}'")

    for app_id, sched in profile.appliances.items():
        acts = library.activations(sched.type)
        if not acts:
            raise ValueError(
                f"profile appliance '{app_id}' ({sched.type}) has no activations in the library"
            )
        f = fault if (fault is not None and fault.appliance_id == app_id) else None
        if sched.mode in ("cycling", "continuous"):
            tr, fm = _cycling_track(sched, acts, n, rng, f, app_id)
        else:
            tr, fm = _event_track(
                sched, acts, n, days, day_dow, day_mean_temp, rng, local_hour, f, app_id
            )
        tracks[app_id] = tr
        fault_mask |= fm
        log.info("%s: on-time %.3f", app_id, float((tr[:, IDX_P_ACTIVE] > ON_THRESHOLD_W).mean()))

    # Demo household behaviour (§4.2): accepted suggestions, applied from their acceptance time.
    for b in behaviours or []:
        _apply_behaviour(b, tracks, fault_mask, fault, ts, tz)

    # TRS-06-07/08 synthesized hvac
    hvac_id = None
    if profile.thermostat.enabled:
        tp = profile.thermostat
        hvac_id = tp.appliance_id
        sp = None
        if setpoint_override is not None:
            sp = (
                thermo.expand_to_samples(setpoint_override, 1, len(step_ts))
                if len(setpoint_override) == len(step_ts)
                else setpoint_override
            )
        res = thermo.simulate(temp_step, tp, sp)
        p = thermo.expand_to_samples(res.p_w, SAMPLES_PER_STEP, n).astype(np.float32)
        hprof = (
            thermo.default_harmonic_profile(profile.vrms_v, tp.power_factor)
            if tp.harmonic_profile == "default"
            else np.asarray(tp.harmonic_profile, dtype=np.float64)
        )
        tr = np.zeros((n, len(NUMERIC_FIELDS)), dtype=np.float32)
        tr[:, IDX_P_ACTIVE] = p
        tr[:, IDX_IRMS] = p / (profile.vrms_v * tp.power_factor)
        tr[:, IDX_VRMS] = np.where(p > 0, profile.vrms_v, 0.0)
        tr[:, IDX_PF] = np.where(p > 0, tp.power_factor, 0.0)
        tr[:, IDX_H1 : IDX_H1 + 32] = p[:, None] * hprof[None, :].astype(np.float32)
        tracks[hvac_id] = tr
        indoor = thermo.expand_to_samples(res.indoor_c, SAMPLES_PER_STEP, n).astype(np.float32)
        log.info(
            "hvac: on-time %.3f, indoor %.1f..%.1f °C",
            float(res.on.mean()),
            res.indoor_c.min(),
            res.indoor_c.max(),
        )

    # TRS-06-01 aggregate = sum of tracks + baseload + Gaussian noise; harmonics summed per order
    agg = np.zeros((n, len(NUMERIC_FIELDS)), dtype=np.float64)
    for tr in tracks.values():
        agg += tr
    noise = rng.normal(0.0, profile.noise_w, n)
    agg[:, IDX_P_ACTIVE] += profile.baseload_w + noise
    agg[:, IDX_P_ACTIVE] = np.maximum(agg[:, IDX_P_ACTIVE], 0.0)
    agg[:, IDX_IRMS] += profile.baseload_w / profile.vrms_v
    agg[:, IDX_VRMS] = profile.vrms_v + rng.normal(0.0, 0.5, n)
    apparent = agg[:, IDX_VRMS] * agg[:, IDX_IRMS]
    agg[:, IDX_PF] = np.clip(
        np.divide(agg[:, IDX_P_ACTIVE], apparent, out=np.zeros(n), where=apparent > 0), 0.0, 1.0
    )

    aggregate = pd.DataFrame(agg.astype(np.float32), columns=list(NUMERIC_FIELDS))
    aggregate.insert(0, "ts", ts)
    aggregate.insert(0, "household_id", profile.household_id)

    truth = pd.DataFrame({"ts": ts})
    for app_id, tr in tracks.items():
        truth[f"{app_id}_w"] = tr[:, IDX_P_ACTIVE]
    truth["baseload_w"] = np.float32(profile.baseload_w)
    truth["fault_active"] = fault_mask
    if hvac_id is not None:
        truth["indoor_c"] = indoor
        truth["outdoor_c"] = thermo.expand_to_samples(temp_step, SAMPLES_PER_STEP, n).astype(
            np.float32
        )

    # TRS-06-02 overlap statistic: share of appliance-on samples where >= 2 appliances are on.
    # Always-on (continuous) appliances and the synthesized hvac are left out, or the number
    # would be trivially high and say nothing about scheduled-use overlap.
    on_counts = np.zeros(n, dtype=np.int16)
    for app_id, tr in tracks.items():
        if app_id != hvac_id and profile.appliances[app_id].mode != "continuous":
            on_counts += tr[:, IDX_P_ACTIVE] > ON_THRESHOLD_W
    any_on = on_counts >= 1
    overlap = float((on_counts[any_on] >= 2).mean()) if any_on.any() else 0.0

    meta = {
        "trs": ["TRS-06-01", "TRS-06-02", "TRS-06-03", "TRS-06-05", "TRS-06-07", "TRS-06-08"],
        "household_id": profile.household_id,
        "seed": seed,
        "days": days,
        "start_local": start_local.isoformat(),
        "local_tz": profile.local_tz,
        "n_samples": n,
        "profile_sha256": profile.fingerprint(),
        "library_sha256": library.fingerprint(),
        "library_sessions": library.sessions,
        "appliances": {
            app_id: {"type": s.type, "label": s.label, "synthetic": False}
            for app_id, s in profile.appliances.items()
        },
        "overlap_fraction": round(overlap, 4),
        "fault": fault.model_dump() if fault else None,
        "fault_samples": int(fault_mask.sum()),
        "behaviours": [b.model_dump(mode="json") for b in behaviours or []],
        "setpoint_override": None if setpoint_override is None else {
            "min_c": float(np.min(setpoint_override)), "max_c": float(np.max(setpoint_override)),
            "sha8": __import__("hashlib").sha256(np.asarray(setpoint_override, dtype=np.float64).tobytes()).hexdigest()[:8],
        },
    }
    if hvac_id is not None:
        meta["appliances"][hvac_id] = {
            "type": "hvac",
            "label": profile.thermostat.label,
            "synthetic": True,
            "thermostat": profile.thermostat.model_dump(exclude={"harmonic_profile"}),
            "note": "synthetic HVAC (TRS-06-07/08); metrics on this track are labelled synthetic (TRS-09-09)",
        }
    if overlap < 0.10:
        log.warning(
            "overlap fraction %.3f is below the TRS-06-02 floor of 0.10 for this profile", overlap
        )
    return Timeline(aggregate, truth, meta)


def write_timeline(tl: Timeline, out_dir: Path) -> dict[str, str]:
    """Write aggregate.parquet, truth.parquet, meta.json. Parquet is written without
    file-level timestamps so repeated runs are byte-identical (TRS-06-03)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import hashlib

    tl.aggregate.to_parquet(out_dir / "aggregate.parquet", index=False, compression="zstd")
    tl.truth.to_parquet(out_dir / "truth.parquet", index=False, compression="zstd")
    shas = {
        name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        for name in ("aggregate.parquet", "truth.parquet")
    }
    meta = {**tl.meta, "sha256": shas}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return shas


def _apply_behaviour(b: Behaviour, tracks: dict[str, np.ndarray], fault_mask: np.ndarray, fault: Fault | None,
                     ts: pd.DatetimeIndex, tz: ZoneInfo) -> None:
    if b.appliance_id not in tracks:
        raise ValueError(f"behaviour names unknown appliance '{b.appliance_id}'")
    tr = tracks[b.appliance_id]
    i0 = int(ts.searchsorted(pd.Timestamp(b.from_ts).tz_convert("UTC")))  # same unit as ts, whatever pandas picked
    if i0 >= len(tr):
        return
    if b.kind == "scale":
        tr[i0:] *= np.float32(b.factor)
    elif b.kind == "end_fault":
        if fault is None or fault.appliance_id != b.appliance_id or fault.kind != "power":
            return
        m = fault_mask.copy()
        m[:i0] = False
        tr[m] /= np.float32(1.0 + fault.magnitude)
        fault_mask[m] = False
    elif b.kind == "shift_peak":
        local = ts.tz_convert(tz)
        hours = local.hour.to_numpy()
        days = local.normalize()
        weekday = local.weekday.to_numpy() < 5
        offset = int((b.to_hour - b.peak_start) * 3600 / SAMPLE_PERIOD_S)
        in_peak = (hours >= b.peak_start) & (hours < b.peak_end)
        if b.weekdays_only:
            in_peak &= weekday
        in_peak[:i0] = False
        idx = np.flatnonzero(in_peak)
        idx = idx[idx + offset < len(tr)]
        moved = tr[idx].copy()
        tr[idx] = 0.0
        np.add.at(tr, idx + offset, moved)
        del days
