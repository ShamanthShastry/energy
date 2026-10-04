"""TRS-13-08, TRS-17-02/04/06 against the published database (HOMEWATT_TEST_DB=1)."""

import uuid

import pytest

pytestmark = pytest.mark.needs_db

W1, W2 = "2030-W01", "2030-W02"


@pytest.fixture(scope="module")
def client():
    from homewatt.spacetime import SpacetimeClient

    return SpacetimeClient.from_settings()


@pytest.fixture
def hh():
    return f"hh-ledger-{uuid.uuid4().hex[:8]}"


def cand(hh, week, appliance, action_type, saving, surfaced=True):
    return {
        "action_id": str(uuid.uuid4()), "household_id": hh, "appliance_id": appliance, "action_type": action_type,
        "params_json": "{}", "baseline_usd": 10.0, "counterfactual_usd": 10.0 - saving, "saving_usd": saving,
        "saving_kg_co_2": 1.0, "assumption_text": f"{action_type} on {appliance}", "forecast_made_at_us": 0,
        "week_id": week, "success_score": -1.0, "surfaced": surfaced,
    }


def week(client, hh, w):
    df = client.sql(f"SELECT action_id, appliance_id, action_type, status, status_reason, saving_usd FROM action WHERE household_id = '{hh}' AND week_id = '{w}'")
    return {r.appliance_id: r for r in df.itertuples()}


def test_explicit_dismiss_refill_and_week_end_expiry(client, hh):
    from homewatt.cmp17_ledger.ledger import accept, dismiss, read_transitions

    rows = [cand(hh, W1, a, "x", s) for a, s in (("a", 5), ("b", 4), ("c", 3), ("d", 2), ("e", 1))]
    client.call("propose_actions", rows, hh, W1)
    w = week(client, hh, W1)
    assert set(w) == {"a", "b", "c"} and all(r.status == "proposed" for r in w.values())  # TRS-13-06

    dismiss(client, w["b"].action_id)  # explicit, TRS-16-11
    accept(client, w["a"].action_id)
    t = read_transitions(client, w["b"].action_id)
    assert list(t["to_status"]) == ["proposed", "dismissed"] and t.iloc[-1]["actor"] == "user"  # TRS-17-04

    # Re-price within the week: a stays accepted, b is not re-issued, c is re-priced, d fills b's slot.
    rows2 = [cand(hh, W1, a, "x", s) for a, s in (("b", 9), ("a", 8), ("c", 7), ("d", 6), ("e", 5))]
    client.call("propose_actions", rows2, hh, W1)
    w = week(client, hh, W1)
    assert {k: v.status for k, v in w.items()} == {"a": "accepted", "b": "dismissed", "c": "proposed", "d": "proposed"}
    assert w["c"].saving_usd == 7  # TRS-13-08 re-priced in place
    assert w["b"].status_reason == "user"

    # Week ends: everything still proposed expires; accepted is untouched (TRS-17-06).
    client.call("close_week", hh, W1)
    w = week(client, hh, W1)
    assert {k: (v.status, v.status_reason) for k, v in w.items()} == {
        "a": ("accepted", ""), "b": ("dismissed", "user"), "c": ("dismissed", "expired"), "d": ("dismissed", "expired"),
    }
    t = read_transitions(client, w["c"].action_id)
    assert t.iloc[-1]["actor"] == "week_close"


def test_new_week_closes_the_previous_one_even_without_the_weekly_job(client, hh):
    client.call("propose_actions", [cand(hh, W1, "a", "x", 5)], hh, W1)
    client.call("propose_actions", [cand(hh, W2, "a", "x", 5)], hh, W2)
    assert week(client, hh, W1)["a"].status_reason == "expired"
    assert week(client, hh, W2)["a"].status == "proposed"
    n = client.sql(f"SELECT COUNT(*) AS n FROM action WHERE household_id = '{hh}' AND status = 'proposed'").iloc[0]["n"]
    assert n == 1  # TRS-17-03


def test_below_floor_candidates_never_fill_a_slot(client, hh):
    client.call("propose_actions", [cand(hh, W1, "a", "x", 0.1, surfaced=False)], hh, W1)
    assert week(client, hh, W1) == {}


def test_only_proposed_actions_can_be_dismissed(client, hh):
    from homewatt.cmp17_ledger.ledger import dismiss
    from homewatt.spacetime import SpacetimeError

    client.call("propose_actions", [cand(hh, W1, "a", "x", 5)], hh, W1)
    aid = week(client, hh, W1)["a"].action_id
    dismiss(client, aid)
    with pytest.raises(SpacetimeError, match="only a proposed action"):
        dismiss(client, aid)
