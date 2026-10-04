import json

import pytest

from tests.conftest import LIBRARY


@pytest.mark.needs_library
def test_trs_00_04_manifest_records_counts_on_time_and_flags():
    m = json.loads((LIBRARY / "manifest.json").read_text())
    pa = m["per_appliance"]
    for app in ("fridge", "hair_dryer", "iron", "lamp", "laptop", "screen", "straightener", "water_heater"):
        assert {"activations_train", "activations_test", "on_time_fraction_mean", "flag_low_activations"} <= set(pa[app])
    assert pa["lamp"]["activations_total"] == 0 and pa["lamp"]["flag_low_activations"]
    assert pa["iron"]["activations_total"] > 100
