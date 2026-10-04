import pytest

from homewatt.cmp05_ingest.replay import read_timeline, run_replay
from homewatt.cmp05_ingest.service import IngestionService
from homewatt.cmp05_ingest.sinks import MemorySink
from tests.conftest import LIBRARY


@pytest.mark.needs_library
def test_trs_01_02_replayed_30s_gap_is_logged_as_one_gap_event():
    """TRS-01-02 / TRS-05-03 verification: insert a 30 s gap in the replay; CMP-05 logs a gap."""
    df = read_timeline(LIBRARY / "negative" / "05-16_gap30s.parquet", "hh-test")
    sink = MemorySink()
    svc = IngestionService(sink)
    c = run_replay(df, svc, speed=0)
    assert c["gaps"] == 1 and len(sink.gaps) == 1
    assert (sink.gaps[0].gap_end - sink.gaps[0].gap_start).total_seconds() >= 30


@pytest.mark.needs_library
def test_trs_07_03_replayed_duplicate_timestamp_is_counted_once():
    df = read_timeline(LIBRARY / "negative" / "05-16_dup.parquet", "hh-test")
    sink = MemorySink()
    svc = IngestionService(sink)
    c = run_replay(df, svc, speed=0)
    assert c["duplicate"] == 1
    assert len(sink.rows) == c["accepted"]


@pytest.mark.needs_library
def test_trs_01_01_replayed_session_rows_carry_all_37_fields():
    from homewatt.schema import NUMERIC_FIELDS

    df = read_timeline(LIBRARY / "sessions" / "05-16.parquet", "hh-test")
    assert list(df.columns) == ["household_id", "ts", *NUMERIC_FIELDS]
    sink = MemorySink()
    svc = IngestionService(sink)
    c = run_replay(df.head(2000), svc, speed=0)
    assert c["accepted"] + c["rejected"] == 2000
    assert all(v.shape == (36,) for v in sink.rows.values())
