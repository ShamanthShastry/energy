import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from homewatt.cmp05_ingest.batch import Batcher
from homewatt.cmp05_ingest.models import ApplianceSample, PlugSample, Sample
from homewatt.cmp05_ingest.service import IngestionService
from homewatt.cmp05_ingest.sinks import MemorySink
from homewatt.schema import IDX_VRMS, NUMERIC_FIELDS
from tests.conftest import REPO

T0 = datetime(2025, 7, 1, tzinfo=UTC)


def sample(i: int, hh="hh") -> Sample:
    v = np.zeros(len(NUMERIC_FIELDS), dtype=np.float32)
    v[IDX_VRMS] = 240.0
    return Sample(hh, T0 + timedelta(seconds=2 * i), v)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_trs_07_03_duplicate_rows_at_sink_are_ignored_and_counted():
    sink = MemorySink()
    svc = IngestionService(sink, Batcher(max_rows=10))
    rows = [sample(i) for i in range(10)]
    # Two services (two sensors restarting) feed the same rows into one store.
    for s in rows:
        svc.submit(s)
    svc2 = IngestionService(sink, Batcher(max_rows=10))
    for s in rows:
        svc2.submit(s)
    assert len(sink.rows) == 10
    assert svc2.counters.duplicate == 10


def test_cmp05_buffers_up_to_60s_when_store_unavailable_then_drops_oldest_and_counts():
    clock = Clock()
    sink = MemorySink()
    sink.unavailable = True
    svc = IngestionService(sink, Batcher(max_rows=10, clock=clock), clock=clock)
    for i in range(50):  # 50 samples = 100 s of sensor time, buffer holds 30
        svc.submit(sample(i))
    assert len(sink.rows) == 0
    assert svc.counters.buffer_dropped == 20
    sink.unavailable = False
    svc.flush()
    assert len(sink.rows) == 30
    assert sorted(ts for _, ts in sink.rows)[0] == T0 + timedelta(seconds=40)


def test_trs_05_06_replay_and_live_share_one_submit_interface():
    """Static check: nothing in the ingestion package branches on the input's origin."""
    src = Path(REPO / "src" / "homewatt" / "cmp05_ingest")
    text = "\n".join(p.read_text() for p in src.glob("*.py"))
    assert "is_replay" not in text and "is_live" not in text
    assert "def submit(self, sample: Sample)" in text


def test_trs_05_05_exactly_one_call_site_for_the_ingest_reducer():
    """Python side of TRS-05-05: only the CMP-05 sink calls ingest_batch; the module side is
    checked in tests/module."""
    src = Path(REPO / "src")
    hits = []
    for p in src.rglob("*.py"):
        for m in re.finditer(r"call\(\s*\"ingest_batch\"", p.read_text()):
            hits.append((p.relative_to(REPO).as_posix(), m.start()))
    assert len(hits) == 1, hits
    assert hits[0][0] == "src/homewatt/cmp05_ingest/sinks.py"


def test_trs_07_02_no_python_code_writes_raw_aggregate_by_sql():
    src = Path(REPO / "src")
    for p in src.rglob("*.py"):
        t = p.read_text()
        assert not re.search(r"(UPDATE|DELETE FROM|INSERT INTO)\s+raw_aggregate", t, re.I), p


def test_cmp02_plug_rows_go_to_appliance_power_with_source_plug():
    sink = MemorySink()
    svc = IngestionService(sink)
    assert svc.submit_plug(PlugSample("hh", "kettle", T0, 1800.0))
    assert not svc.submit_plug(PlugSample("hh", "kettle", T0, -1.0))
    svc.flush()
    assert len(sink.plug_rows) == 1 and svc.counters.plug_rejected == 1


def test_trs_sys_02_sim_rows_need_a_model_version_and_keep_their_source():
    sink = MemorySink()
    svc = IngestionService(sink)
    assert not svc.submit_plug(ApplianceSample("hh", "fridge", T0, 58.0, "sim", "", 60.0))
    assert svc.submit_plug(ApplianceSample("hh", "fridge", T0, 58.0, "sim", "cmp06-seed7", 60.0))
    assert not svc.submit_plug(ApplianceSample("hh", "fridge", T0, 58.0, "measured", "x", 60.0))
    svc.flush()
    assert [r.source for r in sink.plug_rows] == ["sim"]


def test_trs_sys_02_tracks_are_never_relabelled_as_plug():
    src = Path(REPO / "src" / "homewatt" / "cmp05_ingest" / "replay.py").read_text()
    assert '"sim", model_version, period_s' in src
    assert '"plug"' not in src.split("def read_tracks")[1]
