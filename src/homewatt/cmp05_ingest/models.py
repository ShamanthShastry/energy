from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from homewatt.schema import NUMERIC_FIELDS


@dataclass(slots=True)
class Sample:
    """One 37-field aggregate sample (TRS-01-01). `values` holds the 36 numeric fields in
    NUMERIC_FIELDS order; ts is sensor-assigned UTC (TRS-01-03)."""

    household_id: str
    ts: datetime
    values: np.ndarray  # shape (36,), float32

    @classmethod
    def from_mapping(cls, household_id: str, ts: datetime, m: dict) -> Sample:
        vals = np.array([m.get(f, np.nan) for f in NUMERIC_FIELDS], dtype=np.float32)
        return cls(household_id, ts, vals)


@dataclass(slots=True)
class ApplianceSample:
    """Per-appliance sample. source='plug' (CMP-02, measured) or 'sim' (CMP-06 ground truth,
    demo only, TRS-SYS-02 v0.5). NILM rows are written by CMP-09 directly, not through here."""

    household_id: str
    appliance_id: str
    ts: datetime
    watts: float
    source: str = "plug"
    model_version: str = ""  # required for 'sim'
    period_s: float = 2.0  # the stream's sample period (TRS-08-03)


PlugSample = ApplianceSample


@dataclass(frozen=True, slots=True)
class GapEvent:
    """TRS-05-03: consecutive accepted timestamps differ by more than 10 s."""

    household_id: str
    gap_start: datetime
    gap_end: datetime
    samples_dropped: int  # samples rejected inside the gap, if any


@dataclass
class Counters:
    accepted: int = 0
    duplicate: int = 0
    non_monotonic: int = 0
    negative_power: int = 0
    vrms_out_of_range: int = 0
    harmonic_missing: int = 0
    bad_timestamp: int = 0
    buffer_dropped: int = 0
    gaps: int = 0
    plug_accepted: int = 0
    plug_rejected: int = 0
    insert_statements: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        setattr(self, reason, getattr(self, reason) + 1)
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1

    @property
    def rejected(self) -> int:
        return sum(self.rejected_by_reason.values())

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "rejected_by_reason"} | {
            "rejected": self.rejected
        }
