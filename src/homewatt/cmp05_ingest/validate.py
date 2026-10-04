"""TRS-05-01 (monotonic), TRS-05-02 (bounds, harmonics present), TRS-05-03 (gap events),
TRS-07-03 (duplicate ts counted, not errored)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from homewatt.cmp05_ingest.models import Counters, GapEvent, Sample
from homewatt.schema import (
    GAP_THRESHOLD_S,
    IDX_H1,
    IDX_H32,
    IDX_P_ACTIVE,
    IDX_VRMS,
    VRMS_MAX_V,
    VRMS_MIN_V,
)


@dataclass(frozen=True, slots=True)
class Verdict:
    accepted: bool
    reason: str | None = None
    gap: GapEvent | None = None


class Validator:
    """Per-household state: last accepted timestamp. Stateless otherwise."""

    def __init__(self, counters: Counters | None = None, gap_threshold_s: float = GAP_THRESHOLD_S):
        self.counters = counters or Counters()
        self.gap_threshold_s = gap_threshold_s
        self._last_ts: dict[str, datetime] = {}
        self._dropped_since_last: dict[str, int] = {}

    def last_ts(self, household_id: str) -> datetime | None:
        return self._last_ts.get(household_id)

    def check(self, s: Sample) -> Verdict:
        if s.ts is None or s.ts.tzinfo is None:
            return self._reject(s, "bad_timestamp")
        last = self._last_ts.get(s.household_id)
        if last is not None:
            if s.ts == last:
                return self._reject(s, "duplicate")
            if s.ts < last:
                return self._reject(s, "non_monotonic")
        v = s.values
        if v.shape != (IDX_H32 + 1,):
            return self._reject(s, "harmonic_missing")
        if np.isnan(v[IDX_H1 : IDX_H32 + 1]).any():
            return self._reject(s, "harmonic_missing")
        if not (v[IDX_P_ACTIVE] >= 0.0):  # also rejects NaN
            return self._reject(s, "negative_power")
        if not (VRMS_MIN_V <= v[IDX_VRMS] <= VRMS_MAX_V):
            return self._reject(s, "vrms_out_of_range")

        gap = None
        if last is not None and (s.ts - last).total_seconds() > self.gap_threshold_s:
            gap = GapEvent(
                s.household_id, last, s.ts, self._dropped_since_last.get(s.household_id, 0)
            )
            self.counters.gaps += 1
        self._last_ts[s.household_id] = s.ts
        self._dropped_since_last[s.household_id] = 0
        self.counters.accepted += 1
        return Verdict(True, None, gap)

    def _reject(self, s: Sample, reason: str) -> Verdict:
        self.counters.reject(reason)
        if reason not in ("duplicate", "non_monotonic"):
            self._dropped_since_last[s.household_id] = (
                self._dropped_since_last.get(s.household_id, 0) + 1
            )
        return Verdict(False, reason)
