import pytest

from homewatt.cmp00_activations.split import (
    EXPECTED_TEST,
    EXPECTED_TRAIN,
    TEST_SESSIONS,
    SplitExistsError,
    make_split,
    read_split,
    write_split,
)

ALL = ["05-12", "05-14", "05-15", "05-16", "05-19", "05-20", "05-22", "05-23", "05-26",
       "06-02", "06-16", "06-17", "06-18", "06-20", "06-24"]


def test_trs_00_02_split_is_twelve_three_by_session():
    s = make_split(ALL, {"05-21": "x"})
    assert len(s["train"]) == EXPECTED_TRAIN and len(s["test"]) == EXPECTED_TEST
    assert set(s["test"]) == set(TEST_SESSIONS)
    assert not set(s["train"]) & set(s["test"])
    assert "05-21" not in s["train"] + s["test"]


def test_trs_00_02_split_file_is_written_once(tmp_path):
    p = tmp_path / "split.json"
    s = make_split(ALL, {})
    write_split(p, s)
    assert read_split(p)["test"] == s["test"]
    with pytest.raises(SplitExistsError):
        write_split(p, s)


@pytest.mark.needs_library
def test_trs_00_02_committed_split_matches_rule():
    from tests.conftest import LIBRARY

    s = read_split(LIBRARY / "split.json")
    assert set(s["test"]) == set(TEST_SESSIONS)
    assert len(s["train"]) == 12 and "05-21" in s["excluded"]
