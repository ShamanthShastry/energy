"""Tariff model: seasons × day types × hour windows → $/kWh and kg CO₂/kWh.

TRS-04-01: every hour of every day type is covered exactly once per season; seasons cover the
year exactly once. Gaps and overlaps abort the load naming the hours.
TRS-04-02: a flat plan is one period over all hours (is_flat).
TRS-04-03: valid_from on every rate row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field, field_validator

DayType = Literal["weekday", "weekend", "holiday"]
DAY_TYPES: tuple[DayType, ...] = ("weekday", "weekend", "holiday")


class TariffError(ValueError):
    pass


class Period(BaseModel):
    name: str
    days: list[DayType]
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)  # half-open [start, end), local time
    usd_per_kwh: float = Field(ge=0)
    kg_co2_per_kwh: float | None = None  # overrides the tariff default (hourly feed, OI-04)

    @field_validator("end_hour")
    @classmethod
    def _order(cls, v, info):
        if "start_hour" in info.data and v <= info.data["start_hour"]:
            raise ValueError("end_hour must exceed start_hour")
        return v


class Season(BaseModel):
    name: str
    start: str  # 'MM-DD' inclusive
    end: str  # 'MM-DD' inclusive; may wrap the year end
    periods: list[Period]

    def contains(self, d: date) -> bool:
        md = d.strftime("%m-%d")
        if self.start <= self.end:
            return self.start <= md <= self.end
        return md >= self.start or md <= self.end


@dataclass(frozen=True)
class Rate:
    usd_per_kwh: float
    kg_co2_per_kwh: float
    period_name: str
    season: str


class Tariff(BaseModel):
    tariff_id: str
    utility: str = ""
    plan: str = ""
    timezone: str = "America/Detroit"
    valid_from: date
    kg_co2_per_kwh: float = Field(ge=0)
    carbon_source: str = ""
    fixed_usd_per_month: float = 0.0
    holidays: list[date] = Field(default_factory=list)
    seasons: list[Season]

    # ---- validation (TRS-04-01)
    def check_coverage(self) -> None:
        problems: list[str] = []
        for s in self.seasons:
            for day in DAY_TYPES:
                slots = np.zeros(24, dtype=int)
                for p in s.periods:
                    if day in p.days:
                        slots[p.start_hour : p.end_hour] += 1
                missing = [h for h in range(24) if slots[h] == 0]
                overlap = [h for h in range(24) if slots[h] > 1]
                if missing:
                    problems.append(f"season '{s.name}', {day}: hours {_fmt(missing)} uncovered")
                if overlap:
                    problems.append(f"season '{s.name}', {day}: hours {_fmt(overlap)} covered twice")
        # seasons cover every day of a leap year exactly once
        ref = pd.date_range("2024-01-01", "2024-12-31", freq="D")
        counts = np.array([sum(s.contains(d.date()) for s in self.seasons) for d in ref])
        if (counts == 0).any():
            problems.append(f"days not in any season: {', '.join(ref[counts == 0].strftime('%m-%d')[:5])}")
        if (counts > 1).any():
            problems.append(f"days in two seasons: {', '.join(ref[counts > 1].strftime('%m-%d')[:5])}")
        if problems:
            raise TariffError(f"tariff '{self.tariff_id}' fails coverage (TRS-04-01): " + "; ".join(problems))

    # ---- lookups
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def is_flat(self) -> bool:
        prices = {p.usd_per_kwh for s in self.seasons for p in s.periods}
        return len(prices) == 1

    def season_for(self, d: date) -> Season:
        for s in self.seasons:
            if s.contains(d):
                return s
        raise TariffError(f"no season for {d}")

    def day_type(self, d: date) -> DayType:
        if d in self.holidays:
            return "holiday"
        return "weekend" if d.weekday() >= 5 else "weekday"

    def period_for(self, local: datetime) -> tuple[Season, Period]:
        s = self.season_for(local.date())
        day = self.day_type(local.date())
        for p in s.periods:
            if day in p.days and p.start_hour <= local.hour < p.end_hour:
                return s, p
        raise TariffError(f"no period for {local}")  # unreachable after check_coverage

    def rate(self, ts: datetime | pd.Timestamp) -> Rate:
        """rate(ts) for one UTC timestamp."""
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            raise TariffError("rate() needs a tz-aware timestamp")
        local = t.tz_convert(self.tz).to_pydatetime()
        s, p = self.period_for(local)
        return Rate(p.usd_per_kwh, p.kg_co2_per_kwh if p.kg_co2_per_kwh is not None else self.kg_co2_per_kwh, p.name, s.name)

    def rates(self, ts: pd.DatetimeIndex | pd.Series) -> pd.DataFrame:
        """Vectorised rate lookup: columns usd_per_kwh, kg_co2_per_kwh, period_name, season."""
        idx = pd.DatetimeIndex(ts)
        if idx.tz is None:
            raise TariffError("rates() needs tz-aware timestamps")
        local = idx.tz_convert(self.tz)
        out = pd.DataFrame(index=range(len(idx)), columns=["usd_per_kwh", "kg_co2_per_kwh", "period_name", "season"])
        cache: dict[tuple[date, int], Rate] = {}
        rows = []
        for d, h in zip(local.date, local.hour, strict=True):
            key = (d, h)
            r = cache.get(key)
            if r is None:
                s, p = self.period_for(datetime(d.year, d.month, d.day, h))
                r = Rate(p.usd_per_kwh, p.kg_co2_per_kwh if p.kg_co2_per_kwh is not None else self.kg_co2_per_kwh, p.name, s.name)
                cache[key] = r
            rows.append((r.usd_per_kwh, r.kg_co2_per_kwh, r.period_name, r.season))
        out[:] = rows
        out["usd_per_kwh"] = out["usd_per_kwh"].astype(float)
        out["kg_co2_per_kwh"] = out["kg_co2_per_kwh"].astype(float)
        return out

    def peak_window(self, d: date) -> tuple[int, int] | None:
        """(start_hour, end_hour) of the most expensive period on local date d, or None when the
        day has a single price (flat plan, weekend, holiday)."""
        s = self.season_for(d)
        day = self.day_type(d)
        ps = [p for p in s.periods if day in p.days]
        prices = {p.usd_per_kwh for p in ps}
        if len(prices) <= 1:
            return None
        top = max(ps, key=lambda p: p.usd_per_kwh)
        return top.start_hour, top.end_hour

    def period_rows(self) -> list[dict]:
        """Flat rows for the tariff_period store table (TRS-04-04 exposure)."""
        rows = []
        for s in self.seasons:
            for p in s.periods:
                rows.append(
                    {
                        "tariff_id": self.tariff_id, "season": s.name, "season_start": s.start, "season_end": s.end,
                        "period_name": p.name, "days": ",".join(p.days), "start_hour": p.start_hour, "end_hour": p.end_hour,
                        "usd_per_kwh": p.usd_per_kwh,
                        # SDK canonical name: a digit gets its own underscore (kgCo2PerKwh -> kg_co_2_per_kwh)
                        "kg_co_2_per_kwh": p.kg_co2_per_kwh if p.kg_co2_per_kwh is not None else self.kg_co2_per_kwh,
                        "valid_from": self.valid_from.isoformat(),
                    }
                )
        return rows


def _fmt(hours: list[int]) -> str:
    return ", ".join(f"{h:02d}-{h + 1:02d}" for h in hours)


def load_tariff(path: Path | str) -> Tariff:
    """Load and validate a tariff YAML. Raises TariffError naming uncovered/overlapping hours."""
    data = yaml.safe_load(Path(path).read_text())
    t = Tariff.model_validate(data)
    t.check_coverage()
    return t


def flat_tariff(usd_per_kwh: float, kg_co2_per_kwh: float = 0.5, tariff_id: str = "flat") -> Tariff:
    """TRS-04-02: a flat-rate plan as a single period covering all hours."""
    return Tariff(
        tariff_id=tariff_id, valid_from=date(2025, 1, 1), kg_co2_per_kwh=kg_co2_per_kwh,
        seasons=[Season(name="all", start="01-01", end="12-31", periods=[
            Period(name="flat", days=list(DAY_TYPES), start_hour=0, end_hour=24, usd_per_kwh=usd_per_kwh)
        ])],
    )
