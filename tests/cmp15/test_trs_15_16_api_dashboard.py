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
