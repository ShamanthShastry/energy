"""Shared fixtures. Tests never touch data/raw; a tiny synthetic library is built in tmp_path
so the suite runs without the dataset. Tests marked needs_library/needs_db skip when absent."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from homewatt.schema import IDX_H1, IDX_IRMS, IDX_P_ACTIVE, IDX_PF, IDX_VRMS, NUMERIC_FIELDS

REPO = Path(__file__).resolve().parents[1]
LIBRARY = REPO / "data" / "library"


def pytest_collection_modifyitems(config, items):
    skip_lib = pytest.mark.skip(reason="data/library not built (homewatt cmp00 build)")
    skip_db = pytest.mark.skip(reason="HOMEWATT_DATABASE_URL not set / DB tests opt-in")
    for item in items:
        if "needs_library" in item.keywords and not (LIBRARY / "split.json").exists():
            item.add_marker(skip_lib)
        if "needs_db" in item.keywords and not os.environ.get("HOMEWATT_TEST_DB"):
            item.add_marker(skip_db)


def make_activation(n: int, watts: float, rng: np.random.Generator, vrms: float = 240.0) -> np.ndarray:
    """A plausible (n, 36) activation: constant draw with small noise and a harmonic vector."""
    a = np.zeros((n, len(NUMERIC_FIELDS)), dtype=np.float32)
    p = watts + rng.normal(0, 1.0, n)
    a[:, IDX_P_ACTIVE] = p
    a[:, IDX_VRMS] = vrms
    a[:, IDX_PF] = 0.95
    a[:, IDX_IRMS] = p / (vrms * 0.95)
    for k in range(32):
        a[:, IDX_H1 + k] = a[:, IDX_IRMS] / ((k + 1) ** 1.5)
    return a


def write_fake_library(root: Path, rng: np.random.Generator) -> Path:
    """Minimal CMP-00 layout: activations for a few appliance types, split.json, manifest.json."""
    (root / "activations").mkdir(parents=True)
    specs = {
        "water_heater": (60, 1500.0, 20),   # (samples per activation, watts, count)
        "hair_dryer": (90, 1000.0, 20),
        "fridge": (3000, 58.0, 4),
        "laptop": (3000, 33.0, 4),
    }
    for app, (n, w, cnt) in specs.items():
        frames = []
        for k in range(cnt):
            sess = ["s1", "s2", "s3"][k % 3]
            a = make_activation(n, w, rng)
            df = pd.DataFrame(a, columns=list(NUMERIC_FIELDS))
            df.insert(0, "t_s", np.arange(n) * 2)
            df.insert(0, "i", np.arange(n, dtype=np.int32))
            df.insert(0, "activation_id", f"{sess}:{app}:{k:04d}")
            df.insert(0, "appliance", app)
            df.insert(0, "session", sess)
            frames.append(df)
        pd.concat(frames).to_parquet(root / "activations" / f"{app}.parquet", index=False)
    (root / "split.json").write_text(json.dumps({"train": ["s1", "s2"], "test": ["s3"], "excluded": {"s9": "bad"}}))
    (root / "manifest.json").write_text(json.dumps({"per_appliance": {}}))
    return root


@pytest.fixture
def rng():
    return np.random.default_rng(0)


@pytest.fixture
def fake_library(tmp_path, rng):
    from homewatt.cmp00_activations.library import ActivationLibrary

    write_fake_library(tmp_path / "lib", rng)
    return ActivationLibrary(tmp_path / "lib")


@pytest.fixture
def hot_weather():
    """Hourly weather, 20 days from 2025-07-01 UTC, diurnal 22-34 °C."""
    ts = pd.date_range("2025-06-30T00:00Z", periods=24 * 30, freq="h")
    temp = 28 + 6 * np.sin((ts.hour - 9) / 24 * 2 * np.pi)
    return pd.DataFrame({"ts": ts, "temp_c": temp})


@pytest.fixture
def cold_weather():
    ts = pd.date_range("2025-06-30T00:00Z", periods=24 * 30, freq="h")
    return pd.DataFrame({"ts": ts, "temp_c": np.full(len(ts), 10.0)})


@pytest.fixture
def small_profile():
    from homewatt.cmp06_synth.profile import Profile

    return Profile.model_validate(
        {
            "household_id": "hh-test",
            "baseload_w": 50.0,
            "noise_w": 2.0,
            "appliances": {
                "water_heater": {"type": "water_heater", "label": "water heater", "uses_per_day": 20,
                                  "windows": [{"start_hour": 16, "end_hour": 18}]},
                "hair_dryer": {"type": "hair_dryer", "label": "hair dryer", "uses_per_day": 20,
                                "windows": [{"start_hour": 16, "end_hour": 18}]},
                "fridge": {"type": "fridge", "label": "fridge", "mode": "continuous", "slice_s": [1800, 3600]},
            },
            "thermostat": {"enabled": True, "setpoint_c": 24.0},
        }
    )
