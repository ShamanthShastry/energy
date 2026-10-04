# CLAUDE.md — MHacks 26 Household Energy Tracker

Read `HANDOFF.md` first, then `TRS-HOMEWATT-001.md` in full, before writing any code.

## Who's who

- Shamanth Shastry: chief architect. Decides.
- Claude: architect under Shamanth. Builds, critiques, pushes back freely, but Shamanth's decision stands.
- When a direction from Shamanth contradicts the TRS, stop and ask before acting: name the TRS clause, give 2–3 options with a recommendation, then update the TRS (`TRS-HOMEWATT-001.md`) and the code together once he picks. Never let the code and the TRS drift apart.

## Source of truth

`TRS-HOMEWATT-001.md` (v0.2). Every module maps to a CMP-nn; every behaviour maps to a TRS-nn-mm. Reference the requirement ID in commit messages and docstrings. Bump the revision history table when the TRS changes.

## Hard rules (from the TRS, see HANDOFF.md §Settled decisions)

- No ML or LLM component emits a dollar or CO₂ figure. Costing lives only in CMP-15 (`Σ kWh × rate(ts)`).
- Devices change state only on a user tap, within bounds, with undo (TRS-SYS-03, CMP-19).
- Model evaluation splits by recording session, never by shuffled sample. Forecaster: time-ordered 80/20.
- Gemini (CMP-20) is a narrator. Structured input only; every number verbatim; never proposes actions.
- Actions come only from the ATL (`atl.yaml`, Annex A). Six templates. Adding one is a TRS change.
- Raw data is never updated or deleted. Derived tables add rows under a new `model_version`.
- Dataset session `05-21` is excluded. The train/test split file is written once and never re-split.

## Stack

Python 3.11 · TimescaleDB (PostgreSQL 16) · FastAPI · PyTorch (seq2point) + NILMTK (CO baseline) · LightGBM · Gemini API (JSON response schema) · React + TypeScript · Open-Meteo.

## Conventions

- `src/homewatt/cmpNN_<name>/` one package per component, matching the TRS numbering.
- `tests/` mirrors it; each TRS verification criterion becomes a test named `test_trs_NN_MM_<slug>`.
- Timestamps are UTC `timestamptz` in the DB; local time only in the tariff lookup and the dashboard.
- Energy in kWh, power in W, temperature in °C internally. Convert at the display layer.
- Synthetic timelines are files under `data/synthetic/`, fed through the replay path only (TRS-05-06). Never insert them directly.
- Demo timelines are dated June–September (DTE summer peak gap).

## Dataset

`https://github.com/fariddinar/nilm-dataset` — 2 s samples, 16 sessions (~99 h), 8 appliances + aggregate, 37 fields incl. harmonics h1–h32. Cite Dinar, Paris, Busvelle, Sensors 2025, 25, 4601.
