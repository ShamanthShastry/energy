"""CMP-04 — Tariff and Carbon Table (TRS-04-01 .. TRS-04-05). Every dollar and CO₂ figure in the
Tracker is kWh × a row from here (TRS-SYS-01)."""

from homewatt.cmp04_tariff.model import Rate, Tariff, TariffError, load_tariff

__all__ = ["Rate", "Tariff", "TariffError", "load_tariff"]
