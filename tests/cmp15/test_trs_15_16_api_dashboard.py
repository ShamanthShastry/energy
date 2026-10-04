import re

from homewatt.cmp15_api.data import SPIKE_MARGIN, nice_ticks
from tests.conftest import REPO

DASH = REPO / "dashboard" / "src"


def test_trs_16_verification_frontend_has_no_tariff_rates():
    for p in DASH.rglob("*.ts*"):
        assert "usd_per_kwh" not in p.read_text(), p


def test_trs_16_10_frontend_does_no_currency_formatting():
    for p in DASH.rglob("*.ts*"):
        t = p.read_text()
        assert "toFixed(" not in t and "Intl.NumberFormat" not in t and "toLocaleString" not in t, p


def test_trs_15_03_spike_margin_is_one_named_constant_of_25_percent():
    assert SPIKE_MARGIN == 0.25
    src = (REPO / "src" / "homewatt" / "cmp15_api" / "data.py").read_text()
    assert len(re.findall(r"1\.25|0\.25", src)) == 1


def test_trs_16_01_main_tab_has_exactly_five_panels_in_order_and_no_action_controls():
    app = (DASH / "App.tsx").read_text()
    home = app.split("tab === 'home' ? (")[1].split(") : tab === 'actions'")[0]
    order = re.findall(r"<(MonthSummary|Breakdown|Spikes|Health|Biggest)\b", home)
    assert order == ["MonthSummary", "Breakdown", "Spikes", "Health", "Biggest"]
    biggest = (DASH / "components" / "Biggest.tsx").read_text()
    assert "Take action" not in biggest and "dismiss" not in biggest.lower() and "/api/actions" not in biggest


def test_trs_16_11_12_tabs_actions_has_take_and_dismiss_savings_exists():
    app = (DASH / "App.tsx").read_text()
    assert "label: 'Home'" in app and "label: 'Actions'" in app and "label: 'Savings'" in app
    a = (DASH / "components" / "ActionsTab.tsx").read_text()
    assert "Take action" in a and "Dismiss" in a and "i.viable ?" in a


def test_trs_16_07_simulated_feed_marker_present():
    assert "Simulated feed" in (DASH / "App.tsx").read_text()
    assert "Simulated device" in (DASH / "components" / "ActionsTab.tsx").read_text()


def test_axis_ticks_are_display_strings_from_the_api():
    t = nice_ticks(7.9)
    assert [x["display"] for x in t] == ["5", "10", "15"] or all(isinstance(x["display"], str) for x in t)


def test_trs_08_01_v0_12_estimate_leads_everywhere_but_the_fault_detector():
    import pandas as pd

    from homewatt.cmp11_forecaster.pipeline import SOURCE_PREFERENCE, preferred_hourly
    from homewatt.cmp12_anomaly import detector

    assert SOURCE_PREFERENCE == ("plug", "nilm", "sim")
    assert detector.SOURCE_PREFERENCE == ("plug", "sim", "nilm")  # co-v2.1 cannot see a fridge drawing more
    h = pd.DataFrame({"appliance_id": ["f", "f", "f"], "bucket_us": [1, 1, 1], "source": ["sim", "nilm", "nilm"],
                      "model_version": ["cmp06", "co-v2", "co-v2.1"], "kwh": [1.0, 2.0, 3.0]})
    assert preferred_hourly(h)["kwh"].tolist() == [3.0]


def test_v0_12_money_carries_its_symbol_and_the_frontend_spells_out_no_units():
    from homewatt.display import money

    assert money(4.56) == "$4.56" and money(-1.2) == "−$1.20"
    for p in (REPO / "dashboard" / "src").rglob("*.tsx"):
        assert "dollars" not in p.read_text(), p.name


def test_trs_03_03_every_temperature_is_shown_in_fahrenheit():
    from homewatt.display import fahrenheit, fahrenheit_delta, fahrenheit_text

    assert fahrenheit(26.0) == "79" and fahrenheit(27.0) == "81" and fahrenheit_delta(1.0) == "2" and fahrenheit_delta(0.5) == "1"
    assert fahrenheit_text("The thermostat is set 2 °C warmer, to 27 °C, all week.") == "The thermostat is set 4 °F warmer, to 81 °F, all week."
    assert fahrenheit_text("the water heater is turned down to 49 °C (120 °F)") == "the water heater is turned down to 120 °F"
    assert fahrenheit_text("cools 0.5 °C from 2 to 3 pm, then sits 1 °C warmer") == "cools 1 °F from 2 to 3 pm, then sits 2 °F warmer"
    for p in (REPO / "dashboard" / "src").rglob("*.tsx"):
        assert "°C" not in p.read_text(), p.name
