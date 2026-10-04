"""The SpacetimeDB module cannot run outside SpacetimeDB; these checks type-check it and assert
the TRS clauses visible in its source. Behavioural checks run against the published database
under the needs_db marker (tests/module/test_live_store.py)."""

import re
import shutil
import subprocess

import pytest

from tests.conftest import REPO

MODULE = REPO / "spacetimedb"
SCHEMA = (MODULE / "src" / "schema.ts").read_text()
INDEX = (MODULE / "src" / "index.ts").read_text()


@pytest.mark.skipif(not (MODULE / "node_modules").exists(), reason="run `make module-install` first")
def test_module_type_checks():
    npx = shutil.which("npx")
    assert npx, "node/npx not installed"
    r = subprocess.run([npx, "tsc", "--noEmit", "-p", "."], cwd=MODULE, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_trs_07_03_raw_aggregate_has_household_ts_index_and_duplicate_check():
    assert "columns: ['householdId', 'tsUs']" in SCHEMA
    assert "byHouseholdTs.filter([s.householdId, s.tsUs])" in INDEX
    assert "stat.duplicates += 1" in INDEX


def test_trs_05_05_only_ingest_batch_inserts_raw_aggregate():
    hits = re.findall(r"rawAggregate\.insert\(", INDEX)
    assert len(hits) == 1
    assert "export const ingestBatch" in INDEX


def test_trs_07_02_no_reducer_updates_or_deletes_raw_aggregate():
    assert not re.search(r"rawAggregate\.\w+\.(update|delete)\(", INDEX)
    assert not re.search(r"rawAggregate\.delete\(", INDEX)


def test_write_reducers_require_owner():
    reducers = re.findall(r"export const (\w+) = spacetimedb\.reducer\(", INDEX)
    assert set(reducers) >= {"ingestBatch", "logGap", "logCounters", "writeAppliancePower", "upsertHousehold", "upsertAppliance"}
    for name in reducers:
        body = INDEX.split(f"export const {name} = spacetimedb.reducer(")[1]
        first_brace = body.index("=> {")
        assert "requireOwner(ctx);" in body[first_brace : first_brace + 200], name


def test_trs_08_01_appliance_power_key_includes_source_and_model_version():
    assert "columns: ['householdId', 'applianceId', 'source', 'modelVersion', 'tsUs']" in SCHEMA


def test_trs_08_02_nilm_rows_require_model_version():
    assert "TRS-08-02: nilm rows require modelVersion" in INDEX


def test_trs_08_03_rollup_integrates_watts_times_dt_capped_at_gap_threshold():
    assert "const wh = (watts * dtS) / 3600.0;" in INDEX
    assert "deltaS > 0 && deltaS <= GAP_THRESHOLD_S ? deltaS : NOMINAL_PERIOD_S" in INDEX
    assert "const GAP_THRESHOLD_S = 10.0;" in INDEX


def test_trs_14_02_closed_appliance_type_list_matches_python():
    from homewatt.schema import ApplianceType

    m = re.search(r"const APPLIANCE_TYPES = new Set\(\[(.*?)\]\);", INDEX, re.S)
    names = set(re.findall(r"'(\w+)'", m.group(1)))
    assert names == {t.value for t in ApplianceType}


def test_every_trs_store_table_exists():
    for name in ("household", "appliance", "plug_binding", "raw_aggregate", "ingest_log", "appliance_power",
                 "appliance_hourly", "appliance_daily", "weather", "tariff_period", "forecast", "model_metric",
                 "alert", "action", "action_transition", "outcome_score", "thermostat_state", "actuation", "statement"):
        assert f"name: '{name}'" in SCHEMA, name


def test_raw_and_appliance_power_are_private_and_dashboard_tables_public():
    def block(name):
        i = SCHEMA.index(f"name: '{name}'")
        return SCHEMA[i : i + 200]

    assert "public: true" not in block("raw_aggregate")
    assert "public: true" not in block("appliance_power")
    for name in ("appliance_hourly", "alert", "action", "statement", "thermostat_state"):
        assert "public: true" in block(name), name
