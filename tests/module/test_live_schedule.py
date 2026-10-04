"""v0.11 TRS-19-10..12 reducers against the published database (HOMEWATT_TEST_DB=1)."""

import uuid

import pandas as pd
import pytest

pytestmark = pytest.mark.needs_db


@pytest.fixture(scope="module")
def client():
    from homewatt.spacetime import SpacetimeClient

    return SpacetimeClient.from_settings()


def spec(hh, days=3.0, **kw):
    from homewatt.spacetime import us

    return {"schedule_id": str(uuid.uuid4()), "action_id": "test", "household_id": hh, "appliance_id": "hvac", "kind": "precool",
            "weekdays_only": True, "pre_start_hour": 14, "peak_start_hour": 15, "peak_end_hour": 19, "pre_cool_c": 1.0,
            "peak_warm_c": 1.0, "min_c": 18.0, "max_c": 27.0, "max_step_c": 2.0,
            "valid_until_us": us(pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=days))} | kw


def status(client, sid):
    return client.sql(f"SELECT status, removed_by FROM thermostat_schedule WHERE schedule_id = '{sid}'").iloc[0].to_dict()


def test_install_one_in_force_undo_and_bounds(client):
    from homewatt.spacetime import SpacetimeError

    hh = f"hh-sched-{uuid.uuid4().hex[:8]}"
    a = spec(hh)
    with pytest.raises(SpacetimeError):
        client.call("install_schedule", a["schedule_id"])  # TRS-19-03: no log row, no command
    client.call("begin_schedule_install", a)
    client.call("install_schedule", a["schedule_id"])
    assert status(client, a["schedule_id"])["status"] == "installed"
    with pytest.raises(SpacetimeError, match="already in force"):
        client.call("begin_schedule_install", spec(hh))  # TRS-19-11
    with pytest.raises(SpacetimeError, match="undo"):
        client.call("begin_schedule_removal", a["schedule_id"], "week_close")  # TRS-19-01: only the user removes it
    client.call("begin_schedule_removal", a["schedule_id"], "undo")
    client.call("remove_schedule", a["schedule_id"])
    assert status(client, a["schedule_id"]) == {"status": "removed", "removed_by": "undo"}
    with pytest.raises(SpacetimeError, match="at most its week"):
        client.call("begin_schedule_install", spec(hh, days=8))
    with pytest.raises(SpacetimeError, match="step limit"):
        client.call("begin_schedule_install", spec(hh, pre_cool_c=3.0))
