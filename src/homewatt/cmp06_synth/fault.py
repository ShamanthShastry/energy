"""TRS-06-05 fault script: modifies only the named appliance's track and is recorded in the
ground-truth output so CMP-12's verdict can be scored."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Fault(BaseModel):
    appliance_id: str
    start_day: int = Field(ge=0, description="0-based day index from timeline start")
    end_day: int | None = Field(default=None, description="exclusive; None = to the end")
    kind: Literal["duty_cycle", "power"]
    #: duty_cycle: on-time fraction scales by (1 + magnitude), achieved by shortening off gaps.
    #: power: watts (and current, harmonics) scale by (1 + magnitude) while on.
    magnitude: float

    @classmethod
    def load(cls, path: Path) -> Fault:
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def active_on_day(self, day: int) -> bool:
        return day >= self.start_day and (self.end_day is None or day < self.end_day)
