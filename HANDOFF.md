# HANDOFF — MHacks 26 Household Energy Tracker (HomeWatt)

**Date:** 2026-10-04
**From:** Claude Code build session (Shamanth + Claude)
**To:** the next Claude Code session
**Status:** every build-order step is implemented and verified end to end on the live database. TRS is at **v0.10** (OI-13 built on branch `deployment`). The demo is paused at **July 21, 2025** with week 4's suggestions open. Nothing since commit `0181ef1` is committed.

Read this file, then `TRS-HOMEWATT-001.md` in full, then `CLAUDE.md`, before changing anything.

---

## Roles

- **Shamanth Shastry** is chief architect. He makes every design decision.
- **Claude** is the architect under him. Claude builds, critiques, and pushes back with full license, but Shamanth decides.
- **Standing rule:** when a direction from Shamanth contradicts the TRS, stop and ask before acting: name the clause, give 2–3 options with a recommendation, then update the TRS and the code together once he picks. The TRS changes by his decision, never by drift. Bump its revision table.
- **How he likes to work:** short, plain answers; frequent one-line progress updates; no long silent stretches. Labels in anything visual are written for a PM (component, key detail, status), not dumbed down. Only update the flowchart (`docs/flowchart.mmd`) when he asks.

## The product in one paragraph

A household installs one whole-home electrical sensor (2 s samples, power + current harmonics). An appliance splitter (NILM) would break that into appliances; for the V1 demo the per-appliance split comes straight from a practice home's ground truth, labelled "simulated feed". A LightGBM predictor forecasts each appliance's kWh for the next week against the weather. A deterministic calculator prices six kinds of habit change (Annex A) under the real DTE time-of-day tariff and keeps the best 3 each week. Gemini rewrites those 3 as plain sentences on the **Actions** tab, each with **Take action** and **Dismiss**. Taking a thermostat suggestion moves the simulated thermostat (two taps, 24 h undo). A week later the verifier checks whether the saving really appeared, shows it on the **Savings** tab, and scores each kind of suggestion so next week's ranking favours what works. The **Home** tab is look-only: this month's bill, where the power goes, pricey days ahead, appliance health, biggest saving available.

## Where things stand right now

| Thing | State |
|---|---|
| Database | SpacetimeDB on Maincloud, database `house-energy-7q7yy`, module in `spacetimedb/`, owner = Shamanth's `spacetime login` identity. Contains only data our scripts generated. |
| Demo clock | `2025-07-21 00:00` America/Detroit. Replayed June 30 → July 20 (3 weeks of a 4-week timeline). Run `homewatt demo status`. |
| What happened in the replay | Fridge fault starts Jul 12 → alert Jul 13. On Jul 14 the thermostat suggestion (24 → 26 °C) and fridge service were taken (by Claude, through the API, to test), precool was dismissed. On Jul 21 both were **verified**: thermostat measured 15.58 vs 13.45 expected, fridge 0.51 vs 0.35. Savings tab shows 16.10 dollars saved. |
| Open right now | Week of Jul 21: thermostat +1 °C (to 27, the bound), precool, water heater setpoint. Thermostat currently 26 °C. |
| Gemini | Key in `.env` (`GEMINI_API_KEY`, gitignored, mode 600). Works on `generativelanguage.googleapis.com` with the `x-goog-api-key` header and `gemini-2.5-flash`. Not Vertex. |
| Tests | 167 pass with live tests (`HOMEWATT_TEST_DB=1 .venv/bin/pytest -q`); ~156 offline. Ruff clean; dashboard and module type-check. |
| Git | Last commit `0181ef1` (Shamanth's). Everything after is uncommitted. Commit only when he asks. |

## How to run

```bash
# one-time
uv venv --python 3.11 && uv pip install -e ".[dev,api,ml]"
cd spacetimedb && npm install && cd ..
cd dashboard && npm install && npm run build && cd ..
brew install libomp            # LightGBM needs it on macOS (already installed here)

# dashboard + API (serves the built dashboard at http://127.0.0.1:8000)
.venv/bin/homewatt api serve

# continue the demo one more week (verifies week-of-Jul-21 taps, fills Savings)
.venv/bin/homewatt demo advance --to 2025-07-28

# start the demo over (wipes the whole database; demo only)
.venv/bin/homewatt demo reset --wipe && .venv/bin/homewatt demo init
.venv/bin/homewatt demo advance --to 2025-07-14
```

Each replayed day: aggregate (2 s, 37 fields) and the simulated per-appliance feed (60 s) go through ingestion, the demo clock moves, the fridge detector runs. Each Monday 00:00: close last week (untaken → expired), verify + score, write the week's weather forecast, forecast, price and propose, narrate. The driver never taps anything; a person taps between `advance` calls. Before replaying, the future part of the timeline is regenerated so the simulated household follows what it accepted, and an applied setpoint reshapes the HVAC track from the tap.

Module changes: edit `spacetimedb/src/*.ts`, then `cd spacetimedb && npx tsc --noEmit -p . && spacetime build && spacetime publish house-energy-7q7yy --yes`. Adding tables or columns (with `.default()`) is fine; removing ones that hold data is refused.

Other commands: `homewatt cmp09 evaluate` (splitter scores), `homewatt cmp17 list` (ledger), `homewatt cmp20 run` (re-narrate), `homewatt db sql "SELECT ..."`, `homewatt --help`.

## Code map

| Component | Where | Notes |
|---|---|---|
| Store (all tables, reducers) | `spacetimedb/src/schema.ts`, `index.ts` | Only `ingest_batch` inserts raw readings; every write reducer requires the owner. `sim_clock` makes ledger/alert/actuation times follow the demo clock. |
| Python ↔ store | `src/homewatt/spacetime.py` | `call(reducer, *args)`, `sql(query)`, `us()` / `from_us()` for microsecond timestamps. |
| CMP-00 activation library | `src/homewatt/cmp00_activations`, `data/library/` | `split.json` is written once: train 12, test 05-16 / 05-26 / 06-24, 05-21 excluded. |
| CMP-03 weather | `cmp03_weather` | `data/weather/ann_arbor_2025.parquet` (Jun–Sep 2025). |
| CMP-04 tariff | `cmp04_tariff`, `config/tariffs/dte_d1_11.yaml` | Coverage check names missing/overlapping hours. |
| CMP-05/07/08 ingestion, raw, appliance store | `cmp05_ingest`, `cmp07_raw_store`, `cmp08_appliance_store` | Hourly/daily rollups maintained by the `write_appliance_power` reducer. |
| CMP-06 practice home | `cmp06_synth`, `config/profiles/demo_household.yaml`, `config/faults/fridge_day12.yaml` | Seeded, byte-reproducible; `behaviour.py` = simulated household following accepted suggestions. |
| CMP-09 splitter | `cmp09_nilm/co.py`, `runner.py`, `data/models/co-v2.1.json` | Combinatorial optimisation. Deployed co-v2.1 (power only + synthetic hvac state + per-day baseload estimate) writes 60 s `nilm` rows each replayed day (TRS-09-10). `homewatt cmp09 fit` refits and stores scores; `homewatt cmp09 run --start --end` backfills. |
| CMP-11 predictor | `cmp11_forecaster` | LightGBM vs seasonal-naive, time-ordered 80/20; naive if it doesn't win or < 14 days. |
| CMP-12 fridge detector | `cmp12_anomaly` | Median/MAD z, two consecutive days, baseline skips anomalous days; fridge only in V1. |
| CMP-13 savings calculator | `cmp13_simulator`, `config/atl.yaml` | Weekly batch of 3, stable within the week; dismissed slot refilled; suppression after 3 ignored weeks. |
| CMP-14 sign-up (seed only) | `cmp14_onboarding` | No form yet; price-plan page is OI-10. |
| CMP-15 API | `cmp15_api` | All costing and all number formatting happen here (`src/homewatt/display.py`). |
| CMP-16 dashboard | `dashboard/` (Vite, React, TS) | Tokens in `dashboard/src/styles/tokens.css`; no costing or formatting in the frontend (tests enforce). |
| CMP-17 ledger | `cmp17_ledger` + reducers | Dismiss, accept, week-end expiry, all transitions logged. |
| CMP-18 verifier | `cmp18_verifier` | Uses only the forecast that priced the action. |
| CMP-19 thermostat | `cmp19_actuator` | One `set_setpoint` call site; log row before command; clamp to 18–27 °C, 2 °C per tap; refuse stale state. |
| CMP-20 narrator | `cmp20_narrator` | Gemini behind a one-method protocol; numbers checked verbatim; fallback text if a check fails, retried next run. |
| Demo driver | `src/homewatt/demo/` | `reset`, `init`, `advance`, `status`. State in `data/synthetic/demo/state.json`. |
| Tests | `tests/` mirrors components; `tests/module/test_live_*` need `HOMEWATT_TEST_DB=1`. |
| Spec and docs | `TRS-HOMEWATT-001.md`, `docs/flowchart.mmd`, `docs/design-tokens.md`, `docs/spacetimedb/*` (SDK references) |

## Settled decisions (do not relitigate without new evidence)

1. **TRS-SYS-01:** no ML or AI component emits a dollar or CO₂ figure. All costing is `Σ kWh × rate(ts)` in CMP-15.
2. **TRS-SYS-03:** devices change only on an explicit user tap on a priced action, within bounds, with 24 h undo. Never on a schedule or a forecast.
3. **TRS-SYS-07:** models are evaluated on splits that share no recording session with training. Forecaster: time-ordered 80/20.
4. **Gemini is the narrator only.** Structured input, every number verbatim, never proposes actions. Text only; no voice (v0.4).
5. **Feedback loop is deterministic.** Rank = saving × (0.5 + success score); first week ranks by saving alone.
6. **Annex A is the whole action space:** six templates in `config/atl.yaml`.
7. **HVAC is synthesized** from weather (3 kW, 24 °C, cooling only); its metrics are labelled synthetic.
8. **Thermostat is simulated in V1.** Adapter `read_state / set_setpoint`; SDM (Nest) adapter is a stub.
9. **Tariff is DTE Time of Day 3–7 p.m. (D1.11).** Demo dated June–September.
10. **Session 05-21 excluded**; split written once.
11. **Store is SpacetimeDB on Maincloud** with a TypeScript module (v0.3).
12. **Demo fridge fault is a +40% power fault** — the dataset fridge never cycles.
13. **V1 dashboard runs on the simulated feed** (source `sim`, 60 s, labelled "simulated feed"); never labelled measured (v0.5).
14. **Tabs:** Home is look-only with "Biggest saving available" as its fifth panel; Actions has Take action + Dismiss on viable rows; Savings shows verified savings and every outcome (v0.6–v0.8).
15. **Untaken suggestions expire at week end** and count toward the 3-week suppression (v0.7).

## Waiting on Shamanth (do not decide these yourself)

| ID | Question |
|---|---|
| OI-10 | Price-plan landing page at sign-up so prices are personal. He said **"not now"** on 2026-10-04 after the dashboard was running. Raise it again only when he brings it up or asks what's next. |
| OI-11 | Precool needs a daily thermostat schedule, which TRS-SYS-03 forbids. Built as advice-only. Options: keep, program the device's own schedule once on the tap, or drop the actuator field. |
| OI-12 | API takes 225–650 ms per request on Maincloud vs the 300 ms target. Options: cache reads in CMP-15, or let the dashboard subscribe to public tables. |
| OI-06 | Live scheduling (one scheduler vs cron). The demo driver runs the jobs for the replay. |

## Known limitations to state honestly in the pitch

- Verified savings in the demo measure a simulated household that always follows what it accepts.
- The weather "forecast" in the replay is what actually happened (perfect foresight).
- The splitter is weak on small loads (co-v2.1 held-out F1: laptop 0.26, screen 0.07, straightener 0.63); its baseload estimate absorbs loads that stay on all session. seq2point is not built (OI-03).
- Only the fridge is watched for faults in V1.
- Spike narration is not built (no surface for it since voice was removed).

## Gotchas that cost time

- **SpacetimeDB naming:** reducer struct args and SQL columns use snake_case, and a digit gets its own underscore: `h1`→`h_1`, `kwhP50`→`kwh_p_50`, `kgCo2PerKwh`→`kg_co_2_per_kwh`.
- **SpacetimeDB SQL** has no ORDER BY, GROUP BY, or aggregates beyond COUNT(*): sort in Python. No NaN in reducer JSON (send 0 and a flag).
- **Reducer rejections** come back as HTTP 530; the client treats 530 as an error, other 5xx as an outage.
- **`init` runs only on a database's first publish.** If the `owner` table is empty, every write fails with "only the database owner"; fix with a `--delete-data=always` publish.
- **The spacetime CLI prints the auth token inside error URLs.** Pipe publish output through `sed -E 's/token=0x[0-9a-f]+/token=REDACTED/g'`.
- **pandas 3** defaults to microsecond timestamps; `Timestamp.value` is still nanoseconds. Use `homewatt.spacetime.us()` or `DatetimeIndex.searchsorted`, never mix `.value` with `.asi8`.
- **Never write `open(p,'w').write(open(p).read()...)`** — the write truncates first (it wiped `index.ts` once). Read into a variable, then write.
- **The in-app preview launcher can't read `~/Documents`** (macOS permission). Run servers with Bash in the background and open `http://127.0.0.1:<port>` in the browser pane. For files outside the project, a launch config running `/usr/bin/python3 -I -c ...` with `os.chdir` to a /tmp path works.
- **zsh does not word-split `$var`** in `for x in $var`; use Python or arrays for loops over IDs.
- **LightGBM on macOS** needs `libomp` from Homebrew.

## Housekeeping still owed

- Re-check the DTE rate card before the event (a summer increase was reported after Feb 2025). YAML: `config/tariffs/dte_d1_11.yaml`.
- Check Gemini quota for the event (OI-09).
- `docs/HomeWatt-flowchart.pdf` came from an export Shamanth stopped; it is unverified and older than the current flowchart. Regenerate if he wants a PDF (headless Chrome printing a page that renders `docs/flowchart.mmd` with Mermaid works).
- `docs/household-energy-flowchart.*` is superseded by `docs/flowchart.mmd`.
- Commit when Shamanth asks; `.env`, `data/raw/`, `data/synthetic/`, `node_modules/`, `dashboard/dist/` are ignored.

Live TRS artifact (older copy): https://claude.ai/code/artifact/4354de7f-8f41-4b5d-92f4-7373a2ed2b40 — the repo's `TRS-HOMEWATT-001.md` is newer and canonical now.
Dataset: https://github.com/fariddinar/nilm-dataset (cite Dinar, Paris, Busvelle, *Sensors* 2025, 25, 4601).
