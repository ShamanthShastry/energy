"""One place that turns numbers into the strings users see. CMP-15 and the CMP-20 narrator input
both use it, so a figure on the dashboard and in a sentence is the same string (TRS-20-02)."""

from __future__ import annotations

import math
import re

DAYS_PER_MONTH = 30.4375


def money(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.2f}"


def kg(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.1f}"


def kwh(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.1f}"


def watts(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.0f}"


def pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:+.0f}%"


def plain_change(assumption_text: str) -> str:
    """An action's assumption_text as a readable line: drops the leading 'assumes', spells out
    unit symbols. Wording only; every number is kept as written (TRS-20-02)."""
    t = assumption_text.strip()
    if t.lower().startswith("assumes "):
        t = t[len("assumes "):]
    t = t.replace(" °C", " degrees").replace("°C", " degrees").replace(" °F", " degrees Fahrenheit").replace("°F", " degrees Fahrenheit")
    t = re.sub(r"(?<![\d.])1 degrees", "1 degree", t)
    return t[:1].upper() + t[1:]


def per_month(horizon_usd: float, horizon_days: float = 7.0) -> float:
    """TRS-13-04: a 7-day horizon figure as its monthly equivalent."""
    return horizon_usd * DAYS_PER_MONTH / horizon_days


def celsius(x: float | None) -> str:
    """Setpoints: one decimal only when needed (25.5, 27)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{round(float(x), 1):g}"


def hour12(h: int) -> str:
    """Local hour as people say it: 2 pm, 12 am."""
    h = int(h) % 24
    return f"{(h % 12) or 12} {'am' if h < 12 else 'pm'}"


def hour_range(a: int, b: int) -> str:
    """'1 to 3 pm', '11 am to 1 pm': a local hour span as people say it."""
    a, b = int(a) % 24, int(b) % 24
    same_half = (a < 12) == (b < 12) and b != 0
    return f"{(a % 12) or 12} to {hour12(b)}" if same_half else f"{hour12(a)} to {hour12(b)}"
