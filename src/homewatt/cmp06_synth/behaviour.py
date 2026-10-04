"""Demo household behaviour (§4.2). In the replayed demo, an accepted suggestion is followed by the
simulated household from the moment it was accepted, so the verifier (CMP-18) has a real change to
measure. Applied to the per-appliance tracks before the aggregate is summed; uses no randomness,
so regenerating with a behaviour leaves every other track and the noise byte-identical."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Behaviour(BaseModel):
    appliance_id: str
    from_ts: datetime  # UTC
    kind: Literal["scale", "shift_peak", "end_fault"]
    factor: float = 1.0  # scale
    to_hour: int = 19  # shift_peak: local hour the peak-window use moves to
    peak_start: int = 15  # shift_peak: local peak window [start, end)
    peak_end: int = 19
    weekdays_only: bool = True
    source_action_id: str = ""
