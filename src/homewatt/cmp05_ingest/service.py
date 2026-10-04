"""IngestionService: validate -> batch -> sink, with a bounded memory buffer when the store is
unavailable (CMP-05 error handling: buffer up to 60 s of samples, then drop oldest and count;
never block the sensor)."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

from homewatt.cmp05_ingest.batch import Batcher
from homewatt.cmp05_ingest.models import Counters, PlugSample, Sample
from homewatt.cmp05_ingest.sinks import Sink, SinkUnavailable
from homewatt.cmp05_ingest.validate import Validator
from homewatt.schema import SAMPLE_PERIOD_S

log = logging.getLogger(__name__)

BUFFER_SECONDS = 60.0


class IngestionService:
    def __init__(
        self,
        sink: Sink,
        batcher: Batcher | None = None,
        validator: Validator | None = None,
        clock: Callable[[], float] = time.monotonic,
        buffer_seconds: float = BUFFER_SECONDS,
    ):
        self.sink = sink
        self.clock = clock
        # `is not None`: Batcher defines __len__, so an empty batcher is falsy.
        self.batcher = batcher if batcher is not None else Batcher(clock=clock)
        self.counters = Counters()
        self.validator = validator if validator is not None else Validator(self.counters)
        self.validator.counters = self.counters
        # pending batches that could not be written: (enqueued_at, rows)
        self._pending: deque[tuple[float, list[Sample]]] = deque()
        self._buffer_seconds = buffer_seconds
        self._plug_batch: list[PlugSample] = []

    # ---- the single interface for replay and live (TRS-05-06)
    def submit(self, sample: Sample) -> bool:
        v = self.validator.check(sample)
        if v.gap is not None:
            self._safe(lambda: self.sink.write_gap(v.gap))
        if not v.accepted:
            return False
        full = self.batcher.add(sample)
        if full is not None:
            self._write(full)
        elif self.batcher.due():
            self._write(self.batcher.take())
        return True

    def submit_plug(self, sample: PlugSample) -> bool:
        if sample.watts < 0 or sample.ts.tzinfo is None:
            self.counters.plug_rejected += 1
            return False
        self.counters.plug_accepted += 1
        self._plug_batch.append(sample)
        if len(self._plug_batch) >= self.batcher.max_rows:
            self._flush_plug()
        return True

    def tick(self) -> None:
        """Call periodically (e.g. each second) so an age-expired batch flushes without new input."""
        if self.batcher.due():
            self._write(self.batcher.take())
        if self._pending:
            self._drain_pending()

    def flush(self) -> None:
        if len(self.batcher):
            self._write(self.batcher.take())
        self._drain_pending()
        self._flush_plug()

    def close(self) -> None:
        self.flush()
        for hh in self.validator._last_ts:
            self._safe(lambda hh=hh: self.sink.write_counters(hh, self.counters.as_dict()))
        self.sink.close()

    # ---- internals
    def _write(self, rows: list[Sample]) -> None:
        if not rows:
            return
        if self._pending:
            self._drain_pending()
        if self._pending:  # still unavailable: queue behind the others
            self._enqueue(rows)
            return
        try:
            inserted = self.sink.write_aggregate(rows)
            self.counters.insert_statements += 1
            self.counters.duplicate += len(rows) - inserted
        except SinkUnavailable as e:
            log.warning("store unavailable, buffering %d rows: %s", len(rows), e)
            self._enqueue(rows)

    def _enqueue(self, rows: list[Sample]) -> None:
        self._pending.append((self.clock(), rows))
        self._evict()

    def _evict(self) -> None:
        """Drop the oldest buffered batches once the buffer spans more than BUFFER_SECONDS of
        samples (by sample count at the nominal cadence), counting every dropped row."""
        cap = int(self._buffer_seconds / SAMPLE_PERIOD_S)
        total = sum(len(r) for _, r in self._pending)
        while self._pending and total > cap:
            _, rows = self._pending.popleft()
            total -= len(rows)
            self.counters.buffer_dropped += len(rows)

    def _drain_pending(self) -> None:
        while self._pending:
            _, rows = self._pending[0]
            try:
                inserted = self.sink.write_aggregate(rows)
            except SinkUnavailable:
                return
            self.counters.insert_statements += 1
            self.counters.duplicate += len(rows) - inserted
            self._pending.popleft()

    def _flush_plug(self) -> None:
        if self._plug_batch:
            rows, self._plug_batch = self._plug_batch, []
            self._safe(lambda: self.sink.write_plug(rows))

    def _safe(self, fn: Callable[[], object]) -> None:
        try:
            fn()
        except SinkUnavailable as e:
            log.warning("store unavailable for side write: %s", e)
