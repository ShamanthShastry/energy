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
make venv            # uv venv + editable install with dev extras
make module-install  # npm deps for the SpacetimeDB module
make module-build    # tsc + spacetime build
make publish         # spacetime publish to Maincloud (needs `spacetime login`)
make library         # CMP-00 (needs data/raw/nilm-dataset, see below)
make synth           # CMP-06 14-day demo timeline, fridge fault at day 12
make replay          # CMP-05 replay into SpacetimeDB
make test            # offline tests; HOMEWATT_TEST_DB=1 adds the live-store tests
```

SpacetimeDB SQL has no ORDER BY / GROUP BY; readers sort in Python. Reducer struct arguments use
snake_case field names. Timestamps are microsecond integers (`*_us`).

Dataset: `git clone --depth 1 https://github.com/fariddinar/nilm-dataset data/raw/nilm-dataset`.
Cite Dinar, Paris, Busvelle, *Sensors* 2025, 25, 4601.
