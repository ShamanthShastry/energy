"""OI-03 seq2point: TRS-09 rules. Tests that train with PyTorch carry needs_torch and run on their
own (HOMEWATT_TEST_TORCH=1 .venv/bin/pytest tests/cmp09); the rest of the suite never imports torch."""

import numpy as np
import pytest

from homewatt.cmp09_nilm import s2p
from homewatt.schema import NUMERIC_FIELDS
from tests.conftest import REPO


def _toy(n=3000, seed=0):
    """Whole-home = a 2,000 W burst + a flat 58 W load; targets on the 'iron' and 'fridge' slots."""
    rng = np.random.default_rng(seed)
    x = np.zeros((n, len(NUMERIC_FIELDS)), np.float32)
    y = np.zeros((n, len(s2p.APPLIANCES)), np.float32)
    for start in range(200, n - 300, 700):
        y[start:start + 150, s2p.APPLIANCES.index("iron")] = 2000.0
    y[:, s2p.APPLIANCES.index("fridge")] = 58.0
    x[:, NUMERIC_FIELDS.index("p_active_w")] = y.sum(1) + rng.normal(0, 3, n)
    return s2p.Series("toy", x, y, True)


def _random_weights(n_feat: int, n_app: int, rng) -> dict[str, np.ndarray]:
    chans = [(n_feat, 32, 9), (32, 32, 7), (32, 48, 5), (48, 64, 5), (64, 64, 3)]
    w = {}
    for i, (ci, co, k) in zip((0, 2, 4, 6, 8), chans, strict=True):
        w[f"encoder.{i}.weight"] = rng.normal(0, 0.1, (co, ci, k)).astype(np.float32)
        w[f"encoder.{i}.bias"] = np.zeros(co, np.float32)
    w["encoder.11.weight"] = rng.normal(0, 0.03, (256, 64 * 19)).astype(np.float32)
    w["encoder.11.bias"] = np.zeros(256, np.float32)
    for head in ("watts", "on"):
        w[f"{head}.weight"] = rng.normal(0, 0.1, (n_app, 256)).astype(np.float32)
        w[f"{head}.bias"] = np.zeros(n_app, np.float32)
    return w


def test_trs_09_02_numpy_net_has_one_head_pair_per_appliance_and_watts_never_negative():
    net = s2p.NumpyNet(_random_weights(len(s2p.FEATS), len(s2p.APPLIANCES), np.random.default_rng(0)))
    w, p = net(np.random.default_rng(1).normal(size=(4, s2p.WINDOW, len(s2p.FEATS))).astype(np.float32))
    assert w.shape == p.shape == (4, len(s2p.APPLIANCES)) and (w >= 0).all() and ((p >= 0) & (p <= 1)).all()


def test_trs_09_window_is_299_samples_centred_with_edge_padding():
    x = np.arange(10, dtype=np.float32)[:, None]
    w = s2p._windows(x, np.array([0, 9]))
    assert w.shape == (2, s2p.WINDOW, 1) and w[0, s2p.HALF, 0] == 0 and w[1, s2p.HALF, 0] == 9 and w[0, 0, 0] == 0


def test_trs_09_01_inputs_and_power_only_ablation():
    assert s2p.FEATS[:3] == ("p_active_w", "irms_a", "power_factor") and len(s2p.FEATS) == 35
    assert s2p.FEATS_POWER == ("p_active_w",)


def test_trs_09_03_training_uses_train_sessions_and_synthetic_days_only():
    src = (REPO / "src" / "homewatt" / "cmp09_nilm" / "cli.py").read_text()
    assert 'real_sessions(s.library_dir, split["train"])' in src and 'real_sessions(s.library_dir, split["test"])' in src
    assert "synthetic_days(tdir, 0, synth_days)" in src and "synthetic_days(tdir, synth_days, 28)" in src


def test_inference_path_imports_no_torch():
    """The daily run and the API must stay torch-free (OpenMP clash with LightGBM on macOS)."""
    import ast

    tree = ast.parse((REPO / "src" / "homewatt" / "cmp09_nilm" / "s2p.py").read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("torch" in ast.dump(n) for n in top)
    runner = (REPO / "src" / "homewatt" / "cmp09_nilm" / "runner.py").read_text()
    assert "torch" not in runner


def test_deployed_pointer_selects_the_model_every_reader_uses(tmp_path, monkeypatch):
    import pandas as pd

    from homewatt.cmp09_nilm import runner
    from homewatt.cmp11_forecaster.pipeline import preferred_hourly

    monkeypatch.setattr(runner, "DEPLOYED_FILE", tmp_path / "deployed.json")
    runner.set_deployed("co-v2.1", "test")
    h = pd.DataFrame({"appliance_id": ["f", "f"], "bucket_us": [1, 1], "source": ["nilm", "nilm"],
                      "model_version": ["co-v2.1", "s2p-v1"], "kwh": [1.0, 2.0]})
    assert preferred_hourly(h)["kwh"].tolist() == [1.0]
    runner.set_deployed("s2p-v1", "test")
    assert preferred_hourly(h)["kwh"].tolist() == [2.0]


@pytest.mark.needs_torch
def test_trs_09_08_trained_net_round_trips_through_npz_and_numpy_matches_torch(tmp_path):
    pytest.importorskip("torch")
    m = s2p.train([_toy()], s2p.FEATS_POWER, "test", epochs=2, per_epoch=4096, device="cpu")
    w_t, p_t = m.predict(_toy(seed=1).x)
    m.save(tmp_path / "test", {"note": "test"})
    m2 = s2p.S2P.load(tmp_path / "test")
    assert isinstance(m2.net, s2p.NumpyNet) and m2.version == "test"
    w_n, p_n = m2.predict(_toy(seed=1).x)
    assert np.allclose(w_n, w_t, atol=0.5) and np.allclose(p_n, p_t, atol=1e-3)
