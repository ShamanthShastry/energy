from datetime import UTC, datetime, timedelta

import numpy as np

from homewatt.cmp05_ingest.batch import Batcher
from homewatt.cmp05_ingest.models import Sample
from homewatt.cmp05_ingest.service import IngestionService
from homewatt.cmp05_ingest.sinks import MemorySink
from homewatt.schema import IDX_VRMS, NUMERIC_FIELDS

T0 = datetime(2025, 7, 1, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def sample(i: int, hh="hh") -> Sample:
    v = np.zeros(len(NUMERIC_FIELDS), dtype=np.float32)
    v[IDX_VRMS] = 240.0
    return Sample(hh, T0 + timedelta(seconds=2 * i), v)


def test_trs_05_04_batch_flushes_at_500_rows():
    clock = Clock()
    b = Batcher(clock=clock)
    for i in range(499):
        assert b.add(i) is None
    assert len(b.add(499)) == 500 and len(b) == 0


def test_trs_05_04_batch_flushes_after_one_second():
    clock = Clock()
    b = Batcher(clock=clock)
    b.add(1)
    assert not b.due()
    clock.t = 1.0
    assert b.due()


def test_trs_05_04_at_most_two_insert_statements_per_second_at_sensor_cadence():
    """Steady 2 s cadence replayed at 100x: 50 samples/s for 20 simulated seconds."""
    clock = Clock()
    sink = MemorySink()
    svc = IngestionService(sink, Batcher(clock=clock), clock=clock)
    n = 0
    for _sec in range(20):
        for _ in range(50):
            svc.submit(sample(n))
            n += 1
            clock.t += 1 / 50
        svc.tick()
    svc.flush()
    assert len(sink.rows) == n
    assert sink.statements <= 2 * 20
    assert svc.counters.insert_statements == sink.statements
