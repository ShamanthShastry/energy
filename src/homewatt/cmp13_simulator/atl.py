"""Annex A loader. The YAML is the complete action space (TRS-13-01)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from homewatt.config import REPO_ROOT

ATL_PATH = REPO_ROOT / "config" / "atl.yaml"


class Search(BaseModel):
    name: str
    min: float
    max: float
    step: float = Field(gt=0)

    def values(self) -> list[float]:
        out, v = [], self.min
        while v <= self.max + 1e-9:
            out.append(round(v, 6))
            v += self.step
        return out


class Template(BaseModel):
    action_type: str
    shape: Literal["shift", "trim", "setpoint", "maintenance"]
    applies_to: list[str]
    params: dict = Field(default_factory=dict)
    search: Search | list[Search] | None = None  # v0.11: several ranges are searched as a grid
    requires_alert: bool = False
    requires_tou: bool = False
    actuator: str | None = None
    assumption: str
    retired: bool = False

    def searches(self) -> list[Search]:
        if self.search is None:
            return []
        return self.search if isinstance(self.search, list) else [self.search]

    def candidates(self) -> list[dict]:
        """TRS-13-12: the fixed params with every combination of the searched values."""
        out = [dict(self.params)]
        for sr in self.searches():
            out = [dict(c, **{sr.name: v}) for c in out for v in sr.values()]
        return out


class ATL(BaseModel):
    version: int
    templates: list[Template]

    @property
    def active(self) -> list[Template]:
        return [t for t in self.templates if not t.retired]

    def get(self, action_type: str) -> Template:
        for t in self.templates:
            if t.action_type == action_type:
                return t
        raise KeyError(action_type)


def load_atl(path: Path | str = ATL_PATH) -> ATL:
    atl = ATL.model_validate(yaml.safe_load(Path(path).read_text()))
    names = [t.action_type for t in atl.templates]
    if len(names) != len(set(names)):
        raise ValueError("duplicate action_type in ATL")
    return atl
