"""Behavioural checks against the published Maincloud database. Opt in with HOMEWATT_TEST_DB=1;
they need the owner token (spacetime login) and write under household 'hh-pytest'."""

import time
import uuid

import pandas as pd
import pytest

pytestmark = pytest.mark.needs_db


@pytest.fixture(scope="module")
def client():
    from homewatt.spacetime import SpacetimeClient

    return SpacetimeClient.from_settings()


@pytest.fixture
def hh():
    return f"hh-pytest-{uuid.uuid4().hex[:8]}"


def _sample(hh, ts_us):
    return {"household_id": hh, "ts_us": ts_us, "v": [100.0, 0.5, 240.0, 0.9] + [0.1] * 32}


def test_trs_07_03_duplicate_insert_is_ignored_and_counted(client, hh):
    from homewatt.spacetime import us

    t0 = us("2025-07-01T00:00:00Z")
    client.call("ingest_batch", [_sample(hh, t0), _sample(hh, t0 + 2_000_000), _sample(hh, t0)])
    st = client.sql(f"SELECT * FROM ingest_stats WHERE household_id = '{hh}'").iloc[0]
    assert int(st["accepted"]) == 2 and int(st["duplicates"]) == 1
    rows = client.sql(f"SELECT ts_us FROM raw_aggregate WHERE household_id = '{hh}'")
    assert len(rows) == 2


def test_trs_01_01_all_37_fields_land(client, hh):
    from homewatt.cmp07_raw_store.reader import SQL_COLUMN, read_window
    from homewatt.schema import NUMERIC_FIELDS
    from homewatt.spacetime import from_us, us

    t0 = us("2025-07-01T01:00:00Z")
    client.call("ingest_batch", [_sample(hh, t0)])
    df = client.sql(f"SELECT * FROM raw_aggregate WHERE household_id = '{hh}'")
    assert set(SQL_COLUMN.values()) <= set(df.columns) and "ts_us" in df.columns
    assert df.iloc[0]["h_32"] == pytest.approx(0.1)
    win = read_window(client, hh, from_us(t0), from_us(t0 + 1))
    assert list(win.columns) == ["ts", *NUMERIC_FIELDS] and len(win) == 1


def test_trs_08_03_ten_minute_gap_integrates_fifty_minutes(client, hh):
    from homewatt.spacetime import us

    base = us("2025-07-01T10:00:00Z")
    rows = [
        {"household_id": hh, "appliance_id": "kettle", "ts_us": base + i * 2_000_000, "watts": 1200.0, "on_prob": -1.0}
        for i in range(1800)
        if not (1_200_000_000 <= i * 2_000_000 < 1_800_000_000)
    ]
    client.call("write_appliance_power", rows, "plug", "", 2.0)
    h = client.sql(f"SELECT * FROM appliance_hourly WHERE household_id = '{hh}'").iloc[0]
    assert h["kwh"] == pytest.approx(1.2 * 50 / 60, rel=1e-3)
    assert h["covered_s"] == pytest.approx(3000, abs=3)


def test_trs_08_02_nilm_rows_without_model_version_are_refused(client, hh):
    from homewatt.spacetime import SpacetimeError, us

    row = {"household_id": hh, "appliance_id": "x", "ts_us": us("2025-07-01T00:00:00Z"), "watts": 1.0, "on_prob": -1.0}
    with pytest.raises(SpacetimeError, match="TRS-08-02"):
        client.call("write_appliance_power", [row], "nilm", "", 2.0)


def test_trs_08_06_new_model_version_adds_rows(client, hh):
    from homewatt.spacetime import us

    row = {"household_id": hh, "appliance_id": "x", "ts_us": us("2025-07-01T00:00:00Z"), "watts": 1.0, "on_prob": 0.5}
    client.call("write_appliance_power", [row], "nilm", "v1", 2.0)
    client.call("write_appliance_power", [row], "nilm", "v2", 2.0)
    df = client.sql(f"SELECT model_version FROM appliance_power WHERE household_id = '{hh}'")
    assert sorted(df["model_version"]) == ["v1", "v2"]


def test_trs_07_05_window_read_of_24h_is_reasonably_fast(client):
    """TRS-07-05 (v0.3): a 24 h window (43,200 rows) over the SQL endpoint in under 5 s."""
    from homewatt.cmp07_raw_store.reader import read_window
    from homewatt.spacetime import from_us

    stats = client.sql("SELECT last_ts_us FROM ingest_stats WHERE household_id = 'hh-demo'")
    if stats.empty:
        pytest.skip("no demo data replayed")
    end = from_us(int(stats.iloc[0]["last_ts_us"]))
    t = time.monotonic()
    df = read_window(client, "hh-demo", end - pd.Timedelta(hours=24), end)
    elapsed = time.monotonic() - t
    print(f"read_window 24 h: {len(df)} rows in {elapsed:.2f}s")
    assert len(df) >= 43_000
    assert elapsed < 5.0
