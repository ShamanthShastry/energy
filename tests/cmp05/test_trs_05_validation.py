from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from homewatt.cmp05_ingest.models import Sample
from homewatt.cmp05_ingest.validate import Validator
from homewatt.schema import IDX_P_ACTIVE, IDX_VRMS, NUMERIC_FIELDS

T0 = datetime(2025, 7, 1, tzinfo=UTC)


def good(ts=T0, hh="hh") -> Sample:
    v = np.zeros(len(NUMERIC_FIELDS), dtype=np.float32)
    v[IDX_P_ACTIVE] = 100.0
    v[IDX_VRMS] = 240.0
    return Sample(hh, ts, v)


def test_trs_05_01_earlier_timestamp_rejected_and_counted():
    val = Validator()
    assert val.check(good(T0)).accepted
    assert val.check(good(T0 + timedelta(seconds=2))).accepted
    v = val.check(good(T0 + timedelta(seconds=1)))
    assert not v.accepted and v.reason == "non_monotonic"
    assert val.counters.non_monotonic == 1 and val.counters.accepted == 2


def test_trs_05_01_monotonicity_is_per_household():
    val = Validator()
    assert val.check(good(T0 + timedelta(seconds=10), "a")).accepted
    assert val.check(good(T0, "b")).accepted


def test_trs_07_03_duplicate_timestamp_counted_not_errored():
    val = Validator()
    val.check(good(T0))
    v = val.check(good(T0))
    assert not v.accepted and v.reason == "duplicate" and val.counters.duplicate == 1


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("p_active_w", -1.0, "negative_power"),
        ("vrms_v", 89.9, "vrms_out_of_range"),
        ("vrms_v", 290.1, "vrms_out_of_range"),
        ("vrms_v", 0.0, "vrms_out_of_range"),
        ("h7", np.nan, "harmonic_missing"),
        ("h32", np.nan, "harmonic_missing"),
    ],
)
def test_trs_05_02_bounds_and_missing_harmonics_rejected_by_reason(field, value, reason):
    val = Validator()
    s = good()
    s.values[NUMERIC_FIELDS.index(field)] = value
    v = val.check(s)
    assert not v.accepted and v.reason == reason
    assert val.counters.rejected_by_reason == {reason: 1}


def test_trs_05_02_short_vector_is_missing_harmonics():
    val = Validator()
    s = good()
    s.values = s.values[:20]
    assert val.check(s).reason == "harmonic_missing"


def test_trs_05_03_gap_event_when_accepted_timestamps_differ_by_more_than_10s():
    val = Validator()
    val.check(good(T0))
    assert val.check(good(T0 + timedelta(seconds=10))).gap is None  # exactly 10 s: no gap
    v = val.check(good(T0 + timedelta(seconds=40.1)))
    assert v.gap is not None
    assert v.gap.gap_start == T0 + timedelta(seconds=10) and v.gap.gap_end == T0 + timedelta(seconds=40.1)
    assert val.counters.gaps == 1


def test_trs_05_03_gap_event_counts_samples_dropped_inside_it():
    val = Validator()
    val.check(good(T0))
    bad = good(T0 + timedelta(seconds=2))
    bad.values[IDX_VRMS] = 0.0
    val.check(bad)
    v = val.check(good(T0 + timedelta(seconds=30)))
    assert v.gap is not None and v.gap.samples_dropped == 1


def test_trs_01_03_naive_timestamp_rejected():
    val = Validator()
    assert val.check(good(datetime(2025, 7, 1))).reason == "bad_timestamp"
