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
    t = t.replace(" °C", " degrees Celsius").replace("°C", " degrees Celsius").replace(" °F", " degrees Fahrenheit").replace("°F", " degrees Fahrenheit")
    t = re.sub(r"(?<![\d.])1 degrees", "1 degree", t)
    return t[:1].upper() + t[1:]


def per_month(horizon_usd: float, horizon_days: float = 7.0) -> float:
    """TRS-13-04: a 7-day horizon figure as its monthly equivalent."""
    return horizon_usd * DAYS_PER_MONTH / horizon_days
