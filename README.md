# Synergy

**Ease the grid. Shrink your bill.** Your family's energy hub, fed by a single sensor.

One clamp on the breaker panel sees every appliance, prices every change, and learns what works in your home, one week at a time.

Built solo at MHacks 26 by Shamanth Shastry. Devpost: https://devpost.com/software/synergy-xiumow

## Why

City grids strain when every household runs its appliances at the same, worst times. Residents can't do much about it: a bill shows one total, not which device cost what, and the only way to find out has been a sensor on every outlet.

The research field of non-intrusive load monitoring (NILM) has known for thirty years that a single whole-home electrical measurement carries enough information to tell appliances apart. Synergy takes that out of the papers and into something a household would actually open: one sensor, every appliance, and advice priced in dollars you can check a week later.

## What it does

- **Where the power goes.** A convolutional neural network splits the whole-home signal into per-appliance usage and cost, labelled as estimated, with its held-out accuracy one click away.
- **This month's bill, by day.** Month-to-date, a forecast for the rest of the month with a high-end range, and a rundown for any day you tap.
- **Looking ahead.** A LightGBM forecaster predicts each appliance's energy for the next 7 days against the weather and flags the expensive days.
- **Appliance health.** The fridge is compared to its own history; two days of drawing more than usual raises an alert.
- **Suggestions, priced.** Each week a deterministic simulator prices six kinds of habit change under the real DTE time-of-day tariff and keeps the best three. Gemini writes each one as a plain sentence.
- **Take action.** A thermostat suggestion moves the (simulated) thermostat in two taps with a 24-hour undo. Precool installs a weekday schedule on the device that expires with the week.
- **Did it really save?** A week later the verifier compares what the appliance actually cost against the forecast that priced the suggestion, shows the verified saving, and re-ranks next week's suggestions by what this household actually does.

## How it works

```
One sensor ──▶ CNN splits it ──▶ Forecasts the week, ──▶ Three suggestions, ──▶ You tap: ──▶ A week later:
(2 s readings)   by appliance      prices each change      in plain English       device + undo   savings verified
                                         ▲                                                              │
                                         └──────────────── learns what works, re-ranks next week ───────┘
```

Three rules hold the whole thing together:

1. **No model emits a dollar.** Every dollar figure anywhere is energy × that hour's rate, computed in one place (the API) from a tariff you can inspect.
2. **Gemini narrates, nothing more.** It receives structured records and returns one sentence per suggestion against a JSON schema; every number is checked verbatim against the input, and it never proposes an action.
3. **Devices change only on a tap.** With undo, within bounds, and never on the app's own clock. A schedule exists only because a tap installed it, and it ends with its week.

## Stack

| Layer | Tools |
|---|---|
| Front end | React, TypeScript, Vite. Styled after the Tesla energy app, light mode. Formats nothing: every number arrives from the API as the string you see. |
| Back end | Python 3.11, FastAPI. All pricing, all formatting, sign-in (scrypt-hashed passwords, signed session cookie), the thermostat flow, the daily CNN run. |
| NILM splitter | PyTorch seq2point CNN (`s2p-v3`): a 299-sample window × 35 inputs (power, current, power factor, 32 harmonics) through a shared 5-layer encoder with a watts head and an on/off head per appliance. Trained on the Mac GPU; inference in numpy from saved `.npz` weights. A combinatorial-optimisation baseline (`co-v2.1`) is kept for comparison. |
| Forecaster | LightGBM per appliance, time-ordered 80/20 split, deployed only when it beats seasonal-naive. |
| Store | SpacetimeDB on Maincloud, TypeScript module. Raw readings append-only; every write is a reducer; the ledger is never deleted. |
| Narrator | Gemini 2.5 Flash with a JSON response schema. Instructions in `config/narrator.md`. |
| Data | Dinar et al. NILM dataset (2 s, 37 fields incl. harmonics), Open-Meteo weather, DTE Time of Day rate card (D1.11). |

Held-out results for the CNN (sessions it never trained on, F1 at 10 W): laptop 0.99, water heater 1.00, fridge 1.00, hair dryer 1.00, iron 0.89, screen 0.54, straightener 0.45. The power-only ablation drops the laptop to 0.64: the harmonics carry the small loads.

## Layout

```
spacetimedb/            SpacetimeDB module: src/schema.ts (tables), src/index.ts (reducers)
src/homewatt/
  cmp00_activations/    activation library + session split from the dataset
  cmp03_weather/        Open-Meteo client
  cmp04_tariff/         rate card loader and rate(ts)
  cmp05_ingest/         validation, gap detection, batched writes, replay
  cmp06_synth/          seeded practice-home timelines, thermostat model, fault script
  cmp07_raw_store/      raw readings reader
  cmp08_appliance_store/ per-appliance writer and kWh rollups
  cmp09_nilm/           s2p.py (CNN), co.py (baseline), runner.py (daily 60 s rows)
  cmp11_forecaster/     LightGBM forecaster
  cmp12_anomaly/        fridge fault detector
  cmp13_simulator/      prices the six action templates (config/atl.yaml)
  cmp14_onboarding/     sign-up and sessions
  cmp15_api/            FastAPI: every dollar and every formatted number
  cmp17_ledger/         suggestion lifecycle
  cmp18_verifier/       verified savings and success scores
  cmp19_actuator/       simulated thermostat: setpoints, precool schedule, undo
  cmp20_narrator/       Gemini narrator with verbatim-number checks
  demo/                 demo driver: replay a day, run the weekly jobs
dashboard/              React app; design tokens in src/styles/tokens.css
config/                 atl.yaml, narrator.md, tariffs/, profiles/, faults/
data/models/            deployed.json names the splitter in use; co-v2.1.json, s2p-v3.npz
docs/                   TRS-HOMEWATT-001.md is the spec; devpost.md; flowchart.mmd
tests/                  one test per spec criterion: test_trs_NN_MM_<slug>
```

The spec (`TRS-HOMEWATT-001.md`) is the source of truth: every module maps to a component and every behaviour to a requirement ID. `HANDOFF.md` and `CLAUDE.md` carry the build notes.

## Quick start

```bash
uv venv --python 3.11 && uv pip install -e ".[dev,api,ml]"
cd spacetimedb && npm install && cd ..
cd dashboard && npm install && npm run build && cd ..
brew install libomp                    # LightGBM on macOS
git clone --depth 1 https://github.com/fariddinar/nilm-dataset data/raw/nilm-dataset
```

Put `GEMINI_API_KEY=...` in `.env` (gitignored). Without it the narrator shows each suggestion's plain fallback text. The SpacetimeDB module publishes with `make publish` after `spacetime login`.

## Running the demo

The demo replays a four-week July timeline of a practice home, day by day, on its own clock. It never takes an action itself: you tap on the dashboard between replays.

```bash
.venv/bin/homewatt demo reset --wipe              # empties the database; demo only
.venv/bin/homewatt demo init                      # household, tariff, weather, timeline
.venv/bin/homewatt demo advance --to 2025-07-14   # two weeks: fridge fault on Jul 12, alert Jul 13
.venv/bin/homewatt api serve                      # http://127.0.0.1:8000 → sign up, then tap
.venv/bin/homewatt demo advance --to 2025-07-21   # verifies last week's taps; Savings tab fills
```

Each replayed day: readings go through ingestion, the CNN splits them, the fault detector runs. Each Monday: close the week (untaken suggestions expire), verify and score, forecast, price and propose three suggestions, narrate.

## The splitter

```bash
.venv/bin/homewatt cmp09 s2p-train                 # train the CNN and its power-only ablation (PyTorch, ~6 min on an M-series GPU)
.venv/bin/homewatt cmp09 deploy s2p-v3 --reason "..."   # make a version the one every reader uses
.venv/bin/homewatt cmp09 run --start 2025-06-30 --end 2025-07-21   # backfill 60 s estimates
.venv/bin/homewatt cmp09 fit                       # refit the CO baseline
```

PyTorch and LightGBM each bundle an OpenMP runtime and crash a single macOS process together, so training is its own command and inference runs in numpy.

## Tests

```bash
.venv/bin/pytest -q                                   # offline suite
HOMEWATT_TEST_DB=1 .venv/bin/pytest -q tests/module   # against the live database
HOMEWATT_TEST_TORCH=1 .venv/bin/pytest -q tests/cmp09 # the PyTorch tests, on their own
.venv/bin/ruff check src tests
```

## Honest limits

- The demo's per-appliance ground truth comes from a simulated practice home, and the simulated household follows every suggestion it accepts, so verified savings in the demo are a best case.
- The weather "forecast" in the replay is what actually happened.
- The CNN is weak on short-burst appliances with few training examples (iron, straightener).
- Only the fridge is watched for faults.
- Every account opens the same demo home; the price-plan sign-up is not built yet.

## Dataset

Dinar, Paris, Busvelle, *Sensors* 2025, 25, 4601. https://github.com/fariddinar/nilm-dataset
