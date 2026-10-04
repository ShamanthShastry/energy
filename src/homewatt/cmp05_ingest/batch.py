"""TRS-05-04: inserts are batched, <= 500 rows or 1 s, whichever first (CMP-05 outputs table).
At the 2 s sensor cadence this yields at most one INSERT per second per household; the
2-per-second ceiling holds for any input rate up to 1,000 samples/s."""

from __future__ import annotations

import time
from collections.abc import Callable

MAX_ROWS = 500
MAX_AGE_S = 1.0


class Batcher:
    def __init__(
        self,
        max_rows: int = MAX_ROWS,
        max_age_s: float = MAX_AGE_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_rows = max_rows
        self.max_age_s = max_age_s
        self.clock = clock
        self._rows: list = []
        self._opened_at: float | None = None

    def add(self, row) -> list | None:
        """Add a row; return the batch to flush if it is now full, else None."""
        if self._opened_at is None:
            self._opened_at = self.clock()
        self._rows.append(row)
        if len(self._rows) >= self.max_rows:
            return self.take()
        return None

    def due(self) -> bool:
        return self._opened_at is not None and (self.clock() - self._opened_at) >= self.max_age_s

    def take(self) -> list:
        rows, self._rows, self._opened_at = self._rows, [], None
        return rows

    def __len__(self) -> int:
        return len(self._rows)
