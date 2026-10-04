"""CMP-05 — Ingestion Service (TRS-05-01 .. TRS-05-06).

The single write path for sensor data. `IngestionService.submit()` is the one interface;
replay (CMP-06 files) and live (CMP-01 sensor) both call it (TRS-05-06, TRS-01-04).
"""
