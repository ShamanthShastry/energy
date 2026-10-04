# HomeWatt — MHacks 26 Predictive Household Energy Tracker

Spec: `TRS-HOMEWATT-001.md` (v0.2). Build notes: `HANDOFF.md`, `CLAUDE.md`.

One whole-home sensor (2 s samples, power + harmonics h1–h32) → NILM per-appliance split →
7-day kWh forecast against weather → deterministic pricing of six habit changes under the DTE
time-of-use tariff → Gemini narrates the top 3 → a tap moves the (simulated) thermostat →
a week later the verifier scores it.

## Layout

```
spacetimedb/        SpacetimeDB TypeScript module: src/schema.ts (every TRS table), src/index.ts (reducers)
spacetime.json      module path + Maincloud database name
src/homewatt/
  spacetime.py        HTTP client: call(reducer, ...) and sql(query) with the owner token
  cmp00_activations/  activation library + session split from the Dinar et al. dataset
  cmp03_weather/      Open-Meteo client (hourly archive + forecast)
  cmp05_ingest/       validation, gap detection, batched COPY, replay at N× speed
  cmp06_synth/        seeded synthetic timelines with thermostat model and fault script
  cmp07_raw_store/    raw_aggregate reader, ingest log
  cmp08_appliance_store/  appliance_power writer (dt_s), integral kWh rollup
config/profiles/    schedule profile YAML per synthetic household (TRS-06-09)
config/faults/      fault scripts for the demo story (TRS-06-05)
data/library/       CMP-00 output: activations, split.json, manifest.json (version-controlled)
data/synthetic/     CMP-06 output, replay-only (gitignored)
dashboard/          React + TypeScript (step 7); design tokens in src/styles/tokens.css
tests/              one test per TRS verification criterion: test_trs_NN_MM_<slug>
```

## Quick start

```bash
make venv            # uv venv + editable install
uv pip install -e ".[dev,api,ml]"
make module-install  # npm deps for the SpacetimeDB module
make publish         # publish the module to Maincloud (needs `spacetime login`)
make library         # CMP-00 (needs data/raw/nilm-dataset, see below)
cd dashboard && npm install && npm run build && cd ..
```

Secrets: put `GEMINI_API_KEY=...` in `.env` (gitignored). Without it the narrator falls back to
each suggestion's plain text.

## Running the demo (build-order step 9)

The demo replays a 4-week July timeline (June 30 to July 27, 2025) day by day on its own clock.
It never takes an action itself: you tap Take action on the dashboard between replays.

```bash
.venv/bin/homewatt demo reset --wipe          # empties the database; demo only
.venv/bin/homewatt demo init                  # household, tariff, weather, base timeline
.venv/bin/homewatt demo advance --to 2025-07-14   # 2 weeks: fridge fault on Jul 12, alert on Jul 13
.venv/bin/homewatt api serve                  # dashboard + API at http://127.0.0.1:8000
# tap suggestions on the Actions tab, then:
.venv/bin/homewatt demo advance --to 2025-07-21   # verifier checks last week's taps; Savings tab fills
```

Every Monday 00:00 of the replay runs the weekly jobs in order: close last week (untaken
suggestions expire), verify and score, forecast, price and propose 3 suggestions, narrate.
The simulated household follows whatever it accepted, from the moment it accepted it.

Other commands: `homewatt cmp09 evaluate` (NILM baseline on held-out sessions), `homewatt cmp17 list`
(ledger), `homewatt db sql "..."`, `homewatt demo status`.

Dashboard development: `homewatt api serve` and, in `dashboard/`, `npm run dev` (Vite on :5173
proxies `/api`).

SpacetimeDB SQL has no ORDER BY / GROUP BY; readers sort in Python. Reducer struct arguments use
snake_case field names, with a digit getting its own underscore (`kwhP50` → `kwh_p_50`).
Timestamps are microsecond integers (`*_us`).

Dataset: `git clone --depth 1 https://github.com/fariddinar/nilm-dataset data/raw/nilm-dataset`.
Cite Dinar, Paris, Busvelle, *Sensors* 2025, 25, 4601.
