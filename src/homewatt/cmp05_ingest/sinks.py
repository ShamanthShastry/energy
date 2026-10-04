"""Where validated rows go. The SpacetimeDB sink is the ONLY place in the Python codebase that
calls the ingest_batch reducer, and ingest_batch is the only reducer that inserts into
raw_aggregate (TRS-05-05; static tests grep both)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Protocol

import numpy as np

from homewatt.cmp05_ingest.models import GapEvent, PlugSample, Sample

log = logging.getLogger(__name__)


class SinkUnavailable(RuntimeError):
    """Raised by a sink when the store cannot be reached; the service buffers (CMP-05 error handling)."""


class Sink(Protocol):
    def write_aggregate(self, rows: list[Sample]) -> int:
        """Insert rows; return the number actually inserted (duplicates ignored, TRS-07-03)."""

    def write_plug(self, rows: list[PlugSample]) -> int: ...

    def write_gap(self, gap: GapEvent) -> None: ...

    def write_counters(self, household_id: str, counters: dict) -> None: ...

    def close(self) -> None: ...


class MemorySink:
    """In-memory sink for tests and dry runs. Mimics the (household_id, ts) uniqueness of
    raw_aggregate so duplicate counting can be exercised without a database."""

    def __init__(self):
        self.rows: dict[tuple[str, datetime], np.ndarray] = {}
        self.plug_rows: list[PlugSample] = []
        self.gaps: list[GapEvent] = []
        self.counter_snapshots: list[tuple[str, dict]] = []
        self.statements = 0
        self.unavailable = False

    def write_aggregate(self, rows: list[Sample]) -> int:
        if self.unavailable:
            raise SinkUnavailable("memory sink marked unavailable")
        self.statements += 1
        inserted = 0
        for s in rows:
            key = (s.household_id, s.ts)
            if key not in self.rows:
                self.rows[key] = s.values
                inserted += 1
        return inserted

    def write_plug(self, rows: list[PlugSample]) -> int:
        self.plug_rows.extend(rows)
        return len(rows)

    def write_gap(self, gap: GapEvent) -> None:
        self.gaps.append(gap)

    def write_counters(self, household_id: str, counters: dict) -> None:
        self.counter_snapshots.append((household_id, counters))

    def close(self) -> None:
        pass


class SpacetimeSink:
    """One ingest_batch reducer call per batch (TRS-05-04). Duplicates are counted by the
    module into ingest_stats; this sink reads them back on close so the service's counters
    match the store (TRS-07-03)."""

    def __init__(self, client=None):
        from homewatt.spacetime import SpacetimeClient, us

        self._us = us
        self.client = client or SpacetimeClient.from_settings()
        self._errors = ()
        self.households: set[str] = set()

    def _wrap(self, fn):
        from homewatt.spacetime import SpacetimeUnavailable

        try:
            return fn()
        except SpacetimeUnavailable as e:
            raise SinkUnavailable(str(e)) from e

    def write_aggregate(self, rows: list[Sample]) -> int:
        payload = [
            {"household_id": s.household_id, "ts_us": self._us(s.ts), "v": [float(x) for x in s.values]}
            for s in rows
        ]
        self.households.update(s.household_id for s in rows)
        self._wrap(lambda: self.client.call("ingest_batch", payload))
        # The reducer cannot return a count; duplicates are reconciled from ingest_stats on close.
        return len(rows)

    def write_plug(self, rows: list[PlugSample]) -> int:
        from homewatt.cmp08_appliance_store.writer import AppliancePowerWriter

        return self._wrap(lambda: AppliancePowerWriter(self.client).write_plug(rows))

    def write_gap(self, gap: GapEvent) -> None:
        self._wrap(
            lambda: self.client.call(
                "log_gap", gap.household_id, self._us(gap.gap_start), self._us(gap.gap_end), int(gap.samples_dropped)
            )
        )

    def write_counters(self, household_id: str, counters: dict) -> None:
        self._wrap(lambda: self.client.call("log_counters", household_id, "rejection_summary", json.dumps(counters)))

    def stats(self, household_id: str) -> dict | None:
        df = self.client.sql(f"SELECT * FROM ingest_stats WHERE household_id = '{household_id}'")
        return df.iloc[0].to_dict() if len(df) else None

    def close(self) -> None:
        self.client.close()
