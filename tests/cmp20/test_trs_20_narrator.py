import json

from homewatt.cmp20_narrator.backend import FakeBackend
from homewatt.cmp20_narrator.narrator import check, narrate, record_for
from tests.conftest import REPO

LABELS = {"dryer": "dryer", "wh": "water heater", "fridge": "fridge"}


def act(aid="a1", app="dryer", saving_week=9.10 * 7 / 30.4375, assumption="assumes all peak-hour use of dryer moves to 21:00 or later"):
    return {"action_id": aid, "appliance_id": app, "assumption_text": assumption, "saving_usd": saving_week, "saving_kg_co_2": 0.0}


def reply(*pairs):
    return json.dumps({"statements": [{"action_id": a, "text": t} for a, t in pairs]})


def test_trs_20_verification_9_10_appears_and_no_other_dollar_figure():
    rec = record_for(act(), LABELS, False, [])
    assert rec["saving_dollars_per_month"] == "9.10"
    good = narrate(FakeBackend([reply(("a1", "Running the dryer after 21:00 could save 9.10 dollars a month."))]), [rec], list(LABELS.values()))
    assert good[0].narrated and "9.10" in good[0].text
    bad = narrate(FakeBackend([reply(("a1", "Running the dryer later could save about 9 dollars, maybe 10."))]), [rec], list(LABELS.values()))
    assert not bad[0].narrated and "TRS-20-02" in bad[0].reason


def test_trs_20_verification_record_naming_only_dryer_mentions_no_other_appliance():
    rec = record_for(act(), LABELS, False, [])
    st = narrate(FakeBackend([reply(("a1", "Run the dryer and the water heater after 21:00 to save 9.10 dollars a month."))]), [rec], list(LABELS.values()))
    assert not st[0].narrated and "another appliance" in st[0].reason


def test_trs_20_verification_malformed_json_one_retry_then_fallback_to_assumption():
    rec = record_for(act(), LABELS, False, [])
    fb = FakeBackend(["not json", "{still not json"])
    st = narrate(fb, [rec], list(LABELS.values()))
    assert len(fb.calls) == 2 and "previous reply was rejected" in fb.calls[1]
    assert not st[0].narrated and st[0].text.startswith("All peak-hour use of dryer")


def test_trs_20_05_word_limit_and_symbols():
    rec = record_for(act(), LABELS, False, [])
    assert check(" ".join(["word"] * 31), rec, []) and "30" in check(" ".join(["word"] * 31), rec, [])
    assert "symbol" in check("Save $9.10 a month.", rec, [])
    assert check("Save 9.10 dollars a month by running the dryer after 21:00.", rec, list(LABELS.values())) is None


def test_trs_20_10_not_verified_history_cannot_be_claimed_as_saving():
    hist = [{"appliance_id": "dryer", "assumption_text": "assumes all peak-hour use of dryer moves to 21:00 or later", "status": "not_verified",
             "verified_saving_usd": 0.1}]
    rec = record_for(act(), LABELS, False, hist)
    assert "verified_saving_dollars" not in rec["history"][0]
    assert check("Last week's dryer change saved money; keep going for 9.10 dollars a month.", rec, []) is not None


def test_trs_20_03_one_statement_per_action_and_no_invented_ones():
    recs = [record_for(act("a1"), LABELS, False, []), record_for(act("a2", "wh", assumption="assumes the water heater is set to 49 °C (120 °F)"), LABELS, False, [])]
    st = narrate(FakeBackend([reply(("a1", "Run the dryer after 21:00 to save 9.10 dollars a month."), ("zzz", "Buy solar panels."))]), recs, list(LABELS.values()))
    assert [s.action_id for s in st] == ["a1", "a2"] and st[0].narrated and not st[1].narrated
    assert " degrees" in recs[1]["change"] and "°" not in recs[1]["change"]


def test_trs_20_01_narrator_imports_nothing_from_tariff_forecast_or_rollups():
    for p in (REPO / "src" / "homewatt" / "cmp20_narrator").glob("*.py"):
        t = p.read_text()
        for bad in ("cmp04_tariff", "cmp11_forecaster", "cmp08_appliance_store", "cmp13_simulator.costing"):
            assert bad not in t, (p.name, bad)


def test_trs_20_07_backend_protocol_has_one_method():
    from homewatt.cmp20_narrator.backend import NarratorBackend

    methods = [m for m in vars(NarratorBackend) if not m.startswith("_") and callable(getattr(NarratorBackend, m))]
    assert methods == ["generate"]


def test_trs_20_06_prompt_lives_in_config_and_editing_it_re_narrates(tmp_path, monkeypatch):
    from homewatt.cmp20_narrator import narrator

    assert narrator.PROMPT_PATH.name == "narrator.md" and "Saves" in narrator.system_prompt()
    rec = {"action_id": "a", "change": "x"}
    before = narrator.input_sha(rec)
    alt = tmp_path / "narrator.md"
    alt.write_text("different instructions")
    monkeypatch.setattr(narrator, "PROMPT_PATH", alt)
    assert narrator.input_sha(rec) != before
