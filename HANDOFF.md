# HANDOFF — MHacks 26 Household Energy Tracker

**Date:** 2026-10-03
**From:** Cowork planning session (Shamanth + Claude)
**To:** Claude Code build session
**Status:** TRS v0.2 complete and ready to scaffold. Nothing is built yet.

---

## Roles

- **Shamanth Shastry** is chief architect. He makes every design decision.
- **Claude** is the architect under him. Claude builds, critiques, and pushes back with full license, but Shamanth decides.
- **Standing rule:** when Shamanth gives a direction that contradicts the TRS, Claude does not silently comply or silently refuse. Claude raises it immediately as an explicit choice (in Claude Code: ask before acting, naming the TRS clause and the options), gets his decision, then updates the TRS and the code together. The TRS is the source of truth; it changes by his decision, never by drift.

## The product in one paragraph

A household head installs one whole-home electrical sensor (2 s sampling, power + current harmonics). A NILM model splits the signal into appliances. A LightGBM forecaster predicts each appliance's kWh for the next week against the weather. A deterministic simulator prices a fixed menu of behaviour changes (the ATL, Annex A) under the real DTE time-of-use tariff. Gemini turns the top 3 priced actions into spoken sentences on a Voice tab. A "take action" tap moves the (simulated) thermostat. A week later the verifier checks whether the saving appeared and scores each action type, and the next week's ranking uses that score. For MHacks the sensor is a replay of the Dinar et al. NILM dataset stitched into a multi-week synthetic timeline.

## Files in this folder

| File | What it is |
|---|---|
| `TRS-HOMEWATT-001.docx` / `.md` | The full requirements spec, v0.2. 20 components (CMP-01 to CMP-20) plus CMP-00, ~120 requirements, Annex A (ATL). **Read this first, fully.** |
| `household-energy-flowchart.png` / `.svg` | Architecture flowchart. **Out of date:** does not yet show CMP-19 (actuator), CMP-20 (narrator), the Voice tab, or the weekly feedback loop. Redraw after scaffolding. |
| `CLAUDE.md` | Project memory for Claude Code. Short version of this file plus build conventions. |
| `HANDOFF.md` | This file. |

Live TRS (editable, canonical): https://claude.ai/code/artifact/4354de7f-8f41-4b5d-92f4-7373a2ed2b40
Dataset: https://github.com/fariddinar/nilm-dataset (cite Dinar, Paris, Busvelle, *Sensors* 2025, 25, 4601)

## Settled decisions (do not relitigate without new evidence)

1. **TRS-SYS-01:** no ML or AI component ever emits a dollar or CO₂ figure. All costing is `Σ kWh × rate(ts)` in CMP-15 from the CMP-04 tariff table.
2. **TRS-SYS-03 (rewritten today):** devices change state only on an explicit user tap on a priced action, within bounds, with 24 h undo. Never on a schedule or a forecast.
3. **TRS-SYS-07:** every ML model is evaluated on a split that shares no recording session with training. Never shuffle 2 s samples. Forecaster uses a time-ordered 80/20 split.
4. **Gemini is the narrator only (CMP-20).** It receives structured action records, rewrites them as sentences, and every number in its output must appear verbatim in its input or the statement is discarded. It never proposes actions. Call it "narrator" or "Advisor" in the pitch, not "agent".
5. **Feedback loop is deterministic (option 1).** CMP-18 computes a per-household, per-action_type success score weekly; CMP-13 ranks by `saving_usd × (0.5 + score)`; Gemini only phrases. Cold start: first week ranks by saving alone, `first_week=true` passed to the narrator.
6. **The ATL (Annex A) is the complete action space.** Six templates. The simulator prices every applicable one and keeps the top 3. Adding a template = TRS revision + YAML change.
7. **HVAC is synthesized** from weather by a thermostat model in CMP-06 (3 kW compressor, 24 °C setpoint, 4 h lag, cooling only). Its NILM metrics are labelled "synthetic HVAC" everywhere.
8. **Thermostat is simulated in V1** (no Nest device available). Adapter interface `read_state / set_setpoint` with simulated and SDM implementations.
9. **Tariff is DTE Time of Day 3–7 p.m. (D1.11).** Summer peak 24.133 ¢, off-peak 18.435 ¢; non-summer peak 20.045 ¢. **Date the demo timeline June–September** or shift actions fall under the $1/month floor.
10. **Session 05-21 of the dataset is excluded** (appliance sum = 5.3× aggregate). Split: 12 sessions train, 3 test, recorded once in a file.

## Stack (from the TRS)

Python 3.11 for everything server-side. TimescaleDB on PostgreSQL 16 (hypertables `raw_aggregate`, `appliance_power`; continuous aggregates hourly/daily; plain tables for households, appliances, weather, tariff, actions, alerts, statements, actuations, outcome_scores). FastAPI for CMP-15. PyTorch seq2point for NILM (NILMTK CO as baseline). LightGBM for the forecaster. Gemini API with JSON response schema for the narrator. React + TypeScript dashboard. Open-Meteo for weather (no key). APScheduler or cron, undecided (OI-06).

## Build order (what to scaffold first)

1. Repo layout, `docker-compose` with TimescaleDB, DDL for every table in the TRS, `pyproject.toml`.
2. **CMP-00:** clone the dataset, extract activations per appliance (sub-meter > 10 W for ≥ 3 samples, 5-sample margin), write the session split file, exclude 05-21. Log activation counts.
3. **CMP-06:** synthetic timeline generator incl. the thermostat model and a fault script. Seeded, reproducible. Output = 37-field aggregate + per-appliance ground truth.
4. **CMP-05 + CMP-07 + CMP-08:** ingestion with replay at N× speed, batched COPY, gap detection. Verify integral-based hourly kWh.
5. **CMP-09:** NILMTK CO baseline first (no training), then seq2point. Report per-appliance MAE / F1 / energy ratio on the 3 held-out sessions. Harmonics ablation.
6. **CMP-04 + CMP-11 + CMP-13 + Annex A YAML:** tariff table with seasons, LightGBM vs seasonal-naive, simulator with parameter search.
7. **CMP-15 + CMP-16 + CMP-17:** API, five-panel dashboard, action ledger.
8. **CMP-12, CMP-18, CMP-19, CMP-20:** anomaly detector, weekly verifier, simulated thermostat, Gemini narrator + Voice tab.
9. Demo script: replay ≥ 3 synthetic weeks in July before judges see it, inject a fridge fault at day 12, confirm the health alert fires on day 13–14.

## Open issues carried over

| ID | Issue | Owner |
|---|---|---|
| OI-03 | Will seq2point reach useful F1 on ~75 h of training data in time? Fallback: NILMTK CO. | ML lead, first 6 h |
| OI-04 | Carbon intensity is a static regional average in V1. | Deferred |
| OI-05 | No smart plug or clamp hardware confirmed. Without a plug, CMP-02/CMP-10 are dropped and nothing on the dashboard reads "measured". | Hardware lead |
| OI-06 | One scheduler or three cron entries. | Backend lead |
| OI-07 | Single hard-coded household in V1; no multi-household auth. | Deferred |
| OI-08 | No Nest device; SDM adapter untested. | If a device turns up |
| OI-09 | Gemini API key/quota unconfirmed. Alexa not started; browser speech synthesis in V1. | Backend lead, before the event |

## Housekeeping still owed

- Redraw the flowchart with CMP-19, CMP-20, Voice tab, weekly loop.
- Re-check the DTE rate card the day the tariff YAML is loaded (a summer increase was reported after the card's Feb 2025 date).
- Get a Gemini key and test JSON-schema output on a 3-action payload.
