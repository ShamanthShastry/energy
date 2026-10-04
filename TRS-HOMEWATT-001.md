# Software Tool Requirements Specification (TRS)

## Predictive Household Energy Tracker

Oct 3, 2026 · @Shamanth

| Field | Value |
| --- | --- |
| Document ID | TRS-HOMEWATT-001 |
| Version | 0.12 — DRAFT |
| Status | For review. Not baselined. |
| Author | Shamanth Shastry |
| Classification | Internal — MHacks 26 team |
| Supersedes | — |
| Related artifacts | Household Energy Product Flow (architecture flowchart, claude.ai artifact); household-energy-flowchart.svg; Dinar et al. NILM dataset (github.com/fariddinar/nilm-dataset) |

## 1. Scope

### 1.1 Purpose

This document specifies the functional requirements, interfaces, and verification criteria for each component of the Predictive Household Energy Tracker ("the Tracker").

The Tracker ingests a whole-home electrical signal, disaggregates it into per-appliance consumption using a non-intrusive load monitoring (NILM) model, forecasts per-appliance energy and cost against weather and tariff data, detects appliance behaviour anomalies, simulates the dollar and carbon effect of concrete habit changes, and presents the result to the head of a household on a dashboard they can open at any time.

### 1.2 In scope

Specification of all 20 components (CMP-01 … CMP-20) corresponding to every data source, process step, model, data store, and user-facing surface in the architecture flowchart, plus the evaluation prerequisite CMP-00.

### 1.3 Out of scope

- Autonomous control. The Tracker changes a device only when the user taps an action (TRS-SYS-03). Automation and any change without a tap are out of scope; a device schedule exists only when a tap installs one, bounded and ending with its week (v0.11).
- The internal design of wrapped third-party components (SpacetimeDB, Open-Meteo, LightGBM, PyTorch). This document specifies their interfaces and expected behaviour.
- Utility-side data-sharing integrations (Green Button Connect, UtilityAPI). Named as the production ingestion path; not built in V1.
- Billing accuracy. Dollar figures are estimates derived from a user-entered tariff, not a reproduction of the utility's invoice.

### 1.4 Intended readership

The MHacks 26 build team, hackathon judges reviewing technical depth, and anyone extending the Tracker after the event.

## 2. Definitions and abbreviations

| Term | Definition |
| --- | --- |
| NILM | Non-Intrusive Load Monitoring. Estimating per-appliance consumption from a single whole-home measurement, without a sensor on each appliance. |
| Aggregate signal | The whole-home electrical measurement: active power plus the current harmonics, sampled every 2 s. The only mandatory input to the NILM model. |
| Activation | One contiguous on→off run of a single appliance in a sub-metered trace. The unit from which synthetic timelines are stitched. |
| Harmonics (h1–h32) | Current harmonic magnitudes from the fundamental to the 32nd order. Distinguish appliances with similar wattage but different electronics. |
| Disaggregation | The NILM model's output: an estimated watts value per appliance per timestep. |
| Baseload | Consumption not attributed to any tracked appliance. Always present as a residual. |
| Tariff | The utility's price schedule mapping each hour to a $/kWh rate. Peak hours carry the higher rate. |
| Spike | A forecast period in which projected cost exceeds the household's trailing baseline by more than the spike margin. |
| Counterfactual | A simulated timeline in which one appliance's schedule or duty is changed, used to price an action. |
| Action | A single concrete habit change with a dollar and kg CO₂ value, e.g. "run the dryer after 7 pm". |
| Duty cycle | Fraction of time an appliance is on within a window. The primary anomaly feature for cycling loads such as a fridge. |
| Carbon intensity | kg CO₂ per kWh of grid electricity for a given hour and region. |
| Replay | Feeding a recorded or synthetic timeline into ingestion at a controlled rate so the system behaves as if live. The V1 demo input. |
| Rollup table | A SpacetimeDB table (appliance\_hourly, appliance\_daily) maintained incrementally by the write reducer. |
| Household head | The single authenticated user of a household's dashboard. |

## 3. Conventions

### 3.1 Requirement identifiers

TRS-\<component number>-\<sequence>, e.g. TRS-09-03 is the third requirement of CMP-09. System-level requirements are TRS-SYS-nn.

### 3.2 Modal verbs

| Verb | Meaning |
| --- | --- |
| shall | Mandatory. Verification is required. |
| should | Recommended. Deviation requires rationale. |
| may | Permitted. No verification obligation. |

### 3.3 Component classification

Every component carries exactly one classification. The central design invariant is that no advice reaches the user without a dollar or CO₂ value computed by a DET component from a tariff the user can inspect (TRS-SYS-01).

| Class | Meaning |
| --- | --- |
| SRC | Data source. Produces raw input; holds no Tracker logic. |
| DET | Deterministic. Fixed logic. Same input yields the same output, always. No model inference. |
| ML | Learned model. Produces estimates with a stated error; never produces a dollar figure on its own. |
| AI | Uses a language model. May rephrase; may never originate a number, an action, or a device command. |
| STORE | Data store. |
| UI | User-facing surface. |
| EXT | External or wrapped third-party service. |

### 3.4 Scope tags

| Tag | Meaning |
| --- | --- |
| \[V1\] | In scope for the 36-hour MHacks build. |
| \[DEMO\] | Simulated or replayed at the demo; a real integration is specified but not built. |
| \[DEF\] | Deferred. Specified here for completeness; not implemented in V1. |

## 4. System-level requirements

**TRS-SYS-01** — Every dollar or CO₂ figure shown to the user shall be computed by a DET-classified component from a tariff and carbon-intensity table the user can inspect. No ML-classified component shall emit a currency or carbon value.

> Rationale: the model's job is to estimate watts. The moment a learned model also prices those watts, a wrong estimate and a wrong price become indistinguishable, and the user cannot audit either.

**TRS-SYS-02** — Every per-appliance value shown to the user shall be labelled as measured (from a plug), estimated (from NILM), or simulated feed (from a CMP-06 ground-truth track, demo only, source='sim'), and every estimate or simulated value shall carry the model version that produced it. A simulated value shall never be labelled measured.

**TRS-SYS-03** — The Tracker shall change the state of a device only in direct response to a user tap on a priced action (CMP-13), within bounds configured at onboarding, and with a visible undo. A tap may install a schedule on the device itself, only for an Annex A template that declares one; the schedule is bounded in its values (TRS-19-02) and its duration (it ends with the action's week, TRS-19-11), and is shown and undoable like any other change. The Tracker itself shall never change a device state on its own clock, on a forecast, or without a tap.

> Changed in v0.11 (decision of S. Shastry, 2026-10-04): a tap may install a bounded, week-long schedule on the device, so precool can be carried out (OI-11). The device runs the schedule; no Tracker component sends a command on a timer.

**TRS-SYS-04** — Raw aggregate samples shall be retained unmodified. Rollups and disaggregations are derived views and shall be reproducible from the raw store and a model version.

**TRS-SYS-05** — Every action proposed to the user shall carry its own expected saving, the assumption it rests on, and a status tracked to disposition (accepted, dismissed, verified).

**TRS-SYS-06** — The Tracker shall be implemented in Python 3.11 or later for all ingestion, modelling, and API components, with SpacetimeDB (Maincloud, TypeScript module) as the only data store. Tables and write logic live in the module (`spacetimedb/`); Python components call reducers and read over the SQL endpoint with the owner identity; the dashboard subscribes to public tables. The dashboard and the module are TypeScript.

> Changed in v0.3 (decision of S. Shastry, 2026-10-03): TimescaleDB replaced by SpacetimeDB. Hypertables, continuous aggregates, compression, and SQL roles have no equivalent; the clauses below that referenced them are restated in SpacetimeDB terms.

**TRS-SYS-07** — Every ML model shall be evaluated on a held-out split that shares no recording session with its training data, and its held-out error shall be shown wherever its output is shown (TRS-16-06).

> Note: a NILM model evaluated on a random split of 2-second samples will report near-perfect accuracy, because adjacent samples are nearly identical. That number is meaningless. Split by session.

### 4.1 System context

The Tracker sits between one whole-home sensor (or its replay) and one household head. Weather and tariff data enter from the side. Nothing leaves the Tracker except the dashboard and its alerts.

### 4.2 Demo fidelity

V1 is a hackathon build. The following are simulated at the demo and labelled as such on the dashboard (TRS-16-07):

| Piece | Demo | Production path |
| --- | --- | --- |
| Whole-home sensor | Replay of the Dinar et al. dataset, stitched into a multi-week timeline (CMP-06) | Clamp-on mains monitor (ESP32 + ATM90E36A) |
| Smart plug | One live energy-monitoring plug | Same, used in a calibration week then removed |
| Weather | Real: Open-Meteo archive for the household ZIP. In the replayed demo the 7-day "forecast" is the archive value for those hours flagged is\_forecast=true, i.e. perfect foresight, stated as such on the dashboard marker | Open-Meteo 7-day forecast |
| Tariff | Real: typed in from the utility's rate sheet | Per-utility lookup |
| Demo clock and household | The replay runs on the timeline's own clock (sim\_clock table); ledger, alert and actuation times follow it. The simulated household follows every suggestion it accepted, from the moment it accepted it, and an applied setpoint or an installed schedule reshapes the HVAC track from the tap (TRS-19-07). Verified savings in the demo therefore measure a household that always complies, and are labelled as replayed | Real households, real compliance |
| HVAC | Synthesized from weather by a thermostat model (TRS-06-07); NILM hvac head trained on synthetic data only. Dryer, oven, and EV remain absent | Real clamp data, hvac head retrained on it; UK-DALE signatures for dryer and oven |
| Per-appliance split | The CMP-06 ground-truth tracks are fed through CMP-05 as source='sim' at 60 s means, labelled "simulated feed" (v0.5). The deployed NILM baseline (CMP-09, co-v2.1) writes its own 'nilm' rows alongside at 60 s means, shown with its error (v0.10). A household without a simulated feed runs on those rows (TRS-08-01) Since v0.12 every per-appliance figure, forecast, priced action and verification leads with the 'nilm' rows; the simulated feed is shown only as a comparison when a row is opened, and remains the input of the fault detector (TRS-08-01) | NILM only (CMP-09) |

## 5. Component specifications

### CMP-01 — Whole-Home Sensor \[V1 / DEMO\]

| Field | Value |
| --- | --- |
| Class | SRC |
| Flowchart element | "Whole-home sensor" |
| Implementing tool | V1: replay of CMP-06 output. Production: ESP32 + ATM90E36A metering IC on the mains feed |
| Owner | Hardware lead |

**Purpose.** Produces the aggregate signal that every downstream estimate rests on. It is the only mandatory per-household input.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Mains current and voltage | Clamp CT on the main feed (production) or CMP-06 replay (V1) | Analogue (production); sample stream (V1) |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Aggregate sample | CMP-05 | {household\_id, ts, p\_active\_w, irms\_a, vrms\_v, power\_factor, h1…h32} at 2 s cadence |

**Requirements**

- TRS-01-01 — The sensor shall emit active power, RMS current, RMS voltage, power factor, and current harmonics h1–h32 for every sample.
- TRS-01-02 — Samples shall be emitted at a nominal 2 s period. Gaps longer than 10 s shall be detectable by CMP-05 from the timestamp alone.
- TRS-01-03 — Every sample shall carry a household\_id and a UTC timestamp assigned at the sensor, not at ingestion.
- TRS-01-04 — The V1 replay shall be byte-identical in schema to the production stream, so that no downstream component can tell them apart.

> Rationale: the demo must exercise the real ingestion path. A demo that loads a CSV straight into the models proves nothing about the pipeline.

**Error handling.** A sample with a missing or non-monotonic timestamp is dropped by CMP-05 and counted; it is never back-filled.

**Verification criteria**

- Replay one dataset session; confirm every row lands in CMP-07 with all 37 fields populated.
- Insert a 30 s gap in the replay; confirm CMP-05 logs a gap event.

**Dependencies.** CMP-06 (V1), CMP-05.

**Open issues.** OI-01 (big-load coverage), OI-05 (hardware availability).

---

### CMP-02 — Smart Plug \[V1\]

| Field | Value |
| --- | --- |
| Class | SRC |
| Flowchart element | "Smart plug, optional" |
| Implementing tool | Shelly Plug (local HTTP API) or TP-Link Kasa KP115 via python-kasa |
| Owner | Hardware lead |

**Purpose.** Provides exact per-appliance watts for the appliance it is attached to. Two roles: a live, measured appliance on the dashboard, and ground-truth labels for fine-tuning NILM to this household (CMP-10).

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Plug power reading | Plug's local API, polled | {watts, ts} |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Measured appliance sample | CMP-05 | {household\_id, appliance\_id, ts, watts, source='plug'} |

**Requirements**

- TRS-02-01 — The plug shall be polled at a period no longer than the aggregate sample period (2 s), so that plug and aggregate samples can be aligned by timestamp without interpolation.
- TRS-02-02 — Each plug shall be bound to exactly one appliance\_id at onboarding (CMP-14). An unbound plug's samples shall be stored but not displayed.
- TRS-02-03 — Plug samples shall be stored with source='plug' and shall take precedence over NILM estimates for the same appliance\_id and timestamp on every dashboard surface (TRS-SYS-02).
- TRS-02-04 — Loss of contact with a plug for more than 60 s shall mark that appliance's live tile as stale; it shall not fall back silently to the NILM estimate.

**Error handling.** Unreachable plug: log, mark stale, keep polling with backoff. Never raise to the user more than once per outage.

**Verification criteria**

- Bind a plug to a kettle; switch the kettle on; confirm the dashboard tile updates within 5 s and shows "measured".
- Unplug the plug; confirm the tile shows stale within 60 s and the NILM estimate is not substituted.

**Dependencies.** CMP-05, CMP-14.

---

### CMP-03 — Weather Service \[V1\]

| Field | Value |
| --- | --- |
| Class | EXT |
| Flowchart element | "Open-Meteo" |
| Implementing tool | Open-Meteo historical and forecast APIs (no key required) |
| Owner | Backend lead |

**Purpose.** Supplies the exogenous driver of heating and cooling load for the forecaster (CMP-11), both historically for training and forward for prediction.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Household location | CMP-14 onboarding | ZIP code, resolved to lat/lon once |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Hourly weather | CMP-08 | {location\_id, ts, temp\_c, humidity\_pct, cloud\_cover\_pct, is\_forecast} |

**Requirements**

- TRS-03-01 — The service shall backfill hourly historical weather for the full span of stored aggregate data, and shall fetch a 7-day hourly forecast at least every 6 hours.
- TRS-03-02 — Forecast rows shall be flagged is\_forecast=true and shall be overwritten by observed values when those become available. Both versions shall remain queryable (TRS-SYS-04).
- TRS-03-03 — Temperature shall be stored in °C. Any display conversion to °F is the dashboard's responsibility.
- TRS-03-04 — A failed fetch shall leave the previous forecast in place and mark its age; the forecaster shall refuse to run on a forecast older than 24 h.

**Error handling.** HTTP failure: retry with exponential backoff, max 3; then log and leave stale.

**Verification criteria**

- Fetch for Ann Arbor; confirm 168 forecast rows land with is\_forecast=true.
- Advance the clock 2 h; refetch; confirm the first two rows are replaced by observed values and the forecast versions remain in history.

**Dependencies.** CMP-08, CMP-14.

---

### CMP-04 — Tariff and Carbon Table \[V1\]

| Field | Value |
| --- | --- |
| Class | STORE |
| Flowchart element | "Tariff table" |
| Implementing tool | SpacetimeDB table `tariff_period`, seeded from a YAML file by a reducer |
| Owner | Backend lead |

**Purpose.** The authoritative mapping from (hour, weekday) to $/kWh and kg CO₂/kWh. Every dollar and carbon figure in the Tracker is a product of a kWh value and a row from this table (TRS-SYS-01).

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Rate schedule | Hand-entered from the utility's residential rate sheet | YAML: list of {name, days, start\_hour, end\_hour, usd\_per\_kwh} |
| Carbon intensity | Static regional average (V1) or Electricity Maps / WattTime hourly feed (DEF) | {region, ts?, kg\_co2\_per\_kwh} |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Rate lookup | CMP-11, CMP-13, CMP-15 | rate(ts) → {usd\_per\_kwh, kg\_co2\_per\_kwh, period\_name} |

**Schema**

| Field | Type | Purpose |
| --- | --- | --- |
| tariff\_id | text | Utility and plan name |
| period\_name | text | e.g. peak, off\_peak |
| days | enum set | weekday, weekend, holiday |
| start\_hour, end\_hour | int | Local time, half-open interval |
| usd\_per\_kwh | numeric | Energy charge |
| kg\_co2\_per\_kwh | numeric | Carbon intensity |
| valid\_from | date | Rate effective date |

**Reference tariff (V1 demo).** DTE Electric Time of Day 3 p.m.–7 p.m., rate D1.11, per the [DTE residential rate card](https://www.dteenergy.com/content/dam/dteenergy/deg/website/residential/Service-Request/pricing/residential-pricing-options/ResidentialElectricRateCard.pdf) effective 2025-02-06. All-in energy price = capacity + non-capacity + 9.726 ¢/kWh distribution. Re-check the card when loading the YAML; a summer increase was reported after this card's date.

| Period | Days | Hours (local) | Summer Jun–Sep, ¢/kWh | Non-summer Oct–May, ¢/kWh |
| --- | --- | --- | --- | --- |
| peak | Mon–Fri | 15:00–19:00 | 24.133 | 20.045 |
| off\_peak | All days | All other hours; weekends and holidays all day | 18.435 | 18.435 |

Service charge $8.50/month, excluded per TRS-04-05. The summer peak/off-peak gap (5.7 ¢/kWh) is what every shift action is priced against; the non-summer gap is 1.6 ¢/kWh, so shift actions will mostly fall under the $1/month floor (TRS-13-04) outside summer. Demo timelines should therefore be dated June–September.

**Requirements**

- TRS-04-01 — The table shall cover every hour of every day type with exactly one period, and shall support a season field (date ranges) so that summer and non-summer prices coexist. Gaps and overlaps within a season shall be rejected at load.
- TRS-04-02 — A flat-rate plan shall be represented as a single period covering all hours. The simulator (CMP-13) shall then report zero saving for time-shift actions rather than omitting them silently.
- TRS-04-03 — Every rate row shall carry valid\_from so that historical cost can be computed under the rate in force at the time.
- TRS-04-04 — The dashboard shall expose the active tariff to the user on request, so that every dollar figure can be traced to a rate they can see.
- TRS-04-05 — Fixed monthly charges may be stored but shall be excluded from all per-appliance and per-action figures.

**Error handling.** A YAML file that fails the coverage check in TRS-04-01 shall abort startup with the uncovered or overlapping hours named.

**Verification criteria**

- Load a two-period time-of-use plan; confirm rate(17:00 Tuesday) returns peak and rate(21:00 Tuesday) returns off\_peak.
- Load a plan with hours 19–20 missing; confirm load fails naming those hours.

**Dependencies.** None.

**Open issues.** OI-02 (does the team's utility plan have a peak window at all).

### CMP-05 — Ingestion Service \[V1\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | "Ingestion service: validate, timestamp, batch insert" |
| Implementing tool | Python 3.11; batches sent as one `ingest_batch` reducer call over the SpacetimeDB HTTP API |
| Owner | Backend lead |

**Purpose.** The single write path for sensor data. Validates every sample, detects gaps, and inserts in batches so that the store never sees a row-at-a-time load.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Aggregate sample | CMP-01 | 37-field sample record |
| Measured appliance sample | CMP-02 | {household\_id, appliance\_id, ts, watts, source} |
| Simulated appliance track \[DEMO\] | CMP-06 ground truth, 60 s means | {household\_id, appliance\_id, ts, watts, source='sim', model\_version} |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Validated aggregate rows | CMP-07 | One `ingest_batch` call per batch, ≤ 500 rows or 1 s, whichever first |
| Validated plug and sim rows | CMP-08 appliance\_power | Batched `write_appliance_power` calls, source='plug' or 'sim' |
| Gap event | CMP-07 ingest\_log | {household\_id, gap\_start, gap\_end, samples\_dropped} |

**Requirements**

- TRS-05-01 — The service shall reject any sample whose timestamp is earlier than the last accepted timestamp for that household, and shall count the rejection.
- TRS-05-02 — The service shall reject any sample with p\_active\_w < 0, vrms\_v outside 90–290 V, or any harmonic field missing, and shall count each rejection by reason.
- TRS-05-03 — The service shall emit a gap event whenever consecutive accepted timestamps differ by more than 10 s.
- TRS-05-04 — Inserts shall be batched. The service shall not issue more than 2 `ingest_batch` reducer calls per second per household under steady load.
- TRS-05-05 — The service shall be the only component that calls `ingest_batch`, and `ingest_batch` shall be the only reducer that inserts into raw\_aggregate. Write reducers accept only the database owner identity; the dashboard holds no owner token and reads public tables only.
- TRS-05-06 — The service shall accept replay input (CMP-06) and live input (CMP-01) through the same interface with no code path that distinguishes them (TRS-01-04).

**Error handling.** Database unavailable: buffer in memory up to 60 s of samples, then drop oldest and count. Never block the sensor.

**Verification criteria**

- Replay a session at 10× speed; confirm row count in raw\_aggregate equals accepted samples and the rejection counters equal the known bad rows.
- Static check: exactly one `rawAggregate.insert` in the module and exactly one `call("ingest_batch")` in Python.

**Dependencies.** CMP-07, CMP-08.

---

### CMP-06 — Synthetic Timeline Generator \[V1 / DEMO\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | Not on the flowchart. Feeds CMP-01 in V1. |
| Implementing tool | Python, NumPy, pandas |
| Owner | ML lead |

**Purpose.** Builds long, labelled, realistic whole-home timelines from short real recordings, so that the Tracker has weeks of data to forecast on and the NILM model has unlimited labelled training data. Also the demo's story engine: it can inject a scheduled fault.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Activation library | CMP-00 (extracted from the Dinar et al. dataset) | Per appliance: list of activations, each a 2 s series of all 37 fields |
| Schedule profile | YAML per synthetic household | Per appliance: daily use count, preferred hours, weekday/weekend weights |
| Hourly weather | CMP-03 | Drives the usage probability of temperature-sensitive loads |
| Fault script (optional) | Demo operator | {appliance\_id, start\_day, kind, magnitude}, kind ∈ {power, duty\_cycle}; the demo uses fridge power +40% from day 12 (the dataset fridge draws a constant ~58 W and never cycles, so a duty-cycle fault cannot be built from real activations) |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Aggregate timeline | CMP-01 replay | Same 37-field schema as a live sample |
| Ground-truth tracks | CMP-00 eval store | Per appliance watts per timestep, aligned to the aggregate |

**Requirements**

- TRS-06-01 — The aggregate shall be the sum of the per-appliance tracks plus a constant baseload plus zero-mean Gaussian noise. Harmonic fields shall be summed per order.
- TRS-06-02 — Activations shall be placed by sampling the schedule profile; overlapping activations shall be permitted and shall occur in at least 10% of appliance-on time.

> Rationale: non-overlapping synthetic data trains a model that cannot handle overlap, which is the whole difficulty of NILM.

- TRS-06-03 — The generator shall be seeded; the same seed, library, and profile shall reproduce the same timeline byte for byte.
- TRS-06-04 — The generator shall exclude any dataset session flagged inconsistent in CMP-00 (TRS-00-03).
- TRS-06-05 — A fault script shall modify only the named appliance's track and shall be recorded in the ground-truth output so the anomaly detector's verdict can be scored.
- TRS-06-06 — Generated timelines shall be stored as files, never written to CMP-07 directly. CMP-01 replay is the only route in (TRS-05-06).

* TRS-06-07 — The generator shall synthesize an hvac track from weather, since the dataset has no HVAC. The track shall be a thermostat model: a compressor of P\_hvac watts (default 3,000 W) cycles on while indoor temperature is above setpoint + 0.5 °C and off below setpoint − 0.5 °C, with indoor temperature following outdoor temp\_c through a first-order lag (default time constant 4 h) and a cooling rate while on (default 1.5 °C/h). Setpoint defaults to 24 °C and is overridable by CMP-19 (TRS-19-07). Below 15 °C outdoor the track is zero (no heating modelled in V1).
* TRS-06-08 — The synthesized hvac track shall carry a fixed harmonic profile (a single stored vector for h1–h32, scaled with p\_active) rather than measured harmonics, and the ground-truth file shall mark the track synthetic=true so that every metric computed on it is labelled accordingly (TRS-09-09).
* TRS-06-09 — The thermostat model's parameters shall live in the schedule profile YAML, so that a demo household can be made HVAC-heavy or HVAC-light without a code change.

**Error handling.** A profile referencing an appliance with no activations in the library shall fail generation, naming the appliance.

**Verification criteria**

- Generate 14 days from seed 7 twice; confirm identical SHA-256.
- Confirm sum of tracks + baseload equals aggregate within noise variance at every timestep.
- Inject a fridge fault at day 12; confirm the ground-truth file marks it.

**Dependencies.** CMP-00, CMP-03.

**Open issues.** OI-01.

---

### CMP-07 — Raw Aggregate Store \[V1\]

| Field | Value |
| --- | --- |
| Class | STORE |
| Flowchart element | "raw\_aggregate store" |
| Implementing tool | SpacetimeDB private table `raw_aggregate` with a btree index on (household\_id, ts\_us) |
| Owner | Backend lead |

**Purpose.** The immutable record of what the sensor saw. Every disaggregation and rollup is derived from it and can be regenerated from it (TRS-SYS-04).

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Validated aggregate rows | CMP-05 | Batched insert |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Window read | CMP-09 | SELECT over (household\_id, ts range), ordered by ts |
| Ingest log read | CMP-16 | Gap and rejection events |

**Schema**

| Field | Type | Purpose |
| --- | --- | --- |
| household\_id | text | Index key |
| ts\_us | i64 | Sensor-assigned, microseconds since the epoch, UTC |
| p\_active\_w | real | Active power |
| irms\_a, vrms\_v, power\_factor | real | Electrical context |
| h1 … h32 | real | Current harmonics |
| ingested\_at | timestamp | Server time (reducer timestamp), for lag monitoring |

**Requirements**

- TRS-07-01 — The table shall carry a btree index on (household\_id, ts\_us) so that window reads are index range scans.
- TRS-07-02 — Rows shall never be updated or deleted by any Tracker component; no reducer other than `ingest_batch` touches the table and `ingest_batch` only inserts. Retention, if any, is an operator action outside the module.
- TRS-07-03 — (household\_id, ts\_us) shall be unique. A duplicate insert shall be ignored, not errored, and counted in `ingest_stats` by the reducer; CMP-05 reconciles its counters from that table.
- TRS-07-04 — Retired in v0.3 (no compression in SpacetimeDB). Storage budget: the Maincloud free tier allows about 1 GB of table storage; a 14-day 2 s timeline is roughly 0.15 GB.
- TRS-07-05 — A window read of 24 h for one household (43,200 rows) over the SQL endpoint shall return in under 5 s from the demo network; the measured figure is recorded by the live test.

**Error handling.** Disk-full is an operator alert, not a Tracker code path.

**Verification criteria**

- Insert a duplicate (household\_id, ts\_us); confirm one row and a counted duplicate in `ingest_stats`.
- Time a 24 h window read; record the figure.

**Dependencies.** CMP-05.

---

### CMP-08 — Appliance Power Store and Rollups \[V1\]

| Field | Value |
| --- | --- |
| Class | STORE |
| Flowchart element | "appliance\_power + hourly rollups" |
| Implementing tool | SpacetimeDB private table `appliance_power` plus `appliance_hourly` and `appliance_daily` rollup tables maintained incrementally by the `write_appliance_power` reducer; public tables for weather, households, appliances, actions |
| Owner | Backend lead |

**Purpose.** Holds per-appliance power, whether measured (plug) or estimated (NILM), and the rollups every dashboard panel and model reads. Also holds the relational tables: households, appliances, weather, actions, alerts.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| NILM estimate | CMP-09 | {household\_id, appliance\_id, ts, watts, source='nilm', model\_version} |
| Plug measurement | CMP-05 | {household\_id, appliance\_id, ts, watts, source='plug'} |
| Weather rows | CMP-03 | Hourly |
| Action and alert records | CMP-13, CMP-12, CMP-17 | See CMP-17 schema |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Hourly kWh per appliance | CMP-11, CMP-12, CMP-13, CMP-15 | Rollup table appliance\_hourly |
| Daily kWh per appliance | CMP-15 | Rollup table appliance\_daily |
| Appliance window | CMP-12 | Raw 2 s rows for duty-cycle analysis |

**Schema (appliance\_power)**

| Field | Type | Purpose |
| --- | --- | --- |
| household\_id | text | Partition key |
| appliance\_id | text | FK to appliances |
| ts\_us | i64 | Aligned to the aggregate sample, microseconds UTC |
| watts | f32 | Estimated or measured |
| source | text | plug, nilm, sim (demo ground truth, v0.5) |
| model\_version | text | Required when source='nilm'; empty for plug |
| dt\_s | f32 | Interval the sample covers, assigned by the reducer (TRS-08-03) |

**Requirements**

- TRS-08-01 — (household\_id, appliance\_id, ts\_us, source, model\_version) shall be unique. Plug, sim, and NILM rows may coexist for the same appliance and timestamp; readers shall prefer plug, then sim, then nilm (TRS-02-03), and may show a nilm estimate next to a sim value with its error. Since v0.12 readers prefer plug, then nilm (the deployed model version), then sim, so the demo behaves as a deployed home would; the one exception is CMP-12, which reads sim before nilm because the deployed CO model reports fixed on-levels and cannot see an appliance drawing more than usual (decision of S. Shastry, 2026-10-04).
- TRS-08-02 — Every NILM row shall carry a non-empty model\_version (TRS-SYS-02). An insert without one shall be rejected by the reducer.
- TRS-08-03 — The hourly rollup shall compute kWh as the time-weighted integral of watts, not the mean of samples, so that gaps do not inflate energy. Realised as Σ watts × dt\_s where dt\_s is the interval since the previous row of the same key when that is at most five sample periods of the stream (10 s for the 2 s sensor, 300 s for the 60 s simulated feed), else one sample period; a gap therefore contributes no energy. The writer declares the stream's sample period on each call.
- TRS-08-04 — Rollups shall be maintained in the same transaction as the appliance\_power insert, so they are never stale.
- TRS-08-05 — A residual appliance\_id='baseload' shall be written for every timestep as aggregate minus the sum of all other appliances, floored at zero.
- TRS-08-06 — Re-running NILM with a new model\_version shall add rows, never replace them. The dashboard reads the latest model\_version per household (TRS-SYS-04).

**Error handling.** A NILM row whose timestamp has no matching raw\_aggregate row is rejected and counted; it indicates a model reading data outside the store. Since v0.10 NILM rows are 60 s means (TRS-09-10), so the match is to a minute with raw\_aggregate samples; it holds by construction because CMP-09 reads only from CMP-07, and the reducer does not re-check it.

**Verification criteria**

- Insert a 10-minute gap in raw data; confirm hourly kWh for that hour equals the integral over 50 minutes, not 60.
- Write NILM rows under model\_version v1 then v2; confirm both persist and the API returns v2.
- Attempt insert with source='nilm' and null model\_version; confirm rejection.

**Dependencies.** CMP-05, CMP-07, CMP-09.

### CMP-09 — NILM Disaggregation Model \[V1 — baseline if time remains after CMP-15..20; else DEF\]

| Field | Value |
| --- | --- |
| Class | ML |
| Flowchart element | "NILM model: aggregate + harmonics → per-appliance watts" |
| Implementing tool | PyTorch seq2point CNN; NILMTK combinatorial-optimisation baseline for comparison |
| Owner | ML lead |

**Purpose.** Turns the one signal the household has into the per-appliance signal the product needs. The production path for the per-appliance split. In the V1 demo the dashboard runs on the simulated feed (§4.2, TRS-SYS-02); the combinatorial-optimisation baseline is added alongside it if time remains, and the pitch presents NILM as the production path with whatever held-out error the baseline achieved.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Aggregate window | CMP-07 | Sliding window of W samples (W = 299 at 2 s ≈ 10 min) × features \[p\_active\_w, irms\_a, power\_factor, h1…h32\] |
| Model weights | CMP-10 (fine-tuned) or the global checkpoint | File, versioned |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Per-appliance estimate | CMP-08 | For the window's centre sample: {appliance\_id, watts, on\_prob, model\_version} per tracked appliance |

**Requirements**

- TRS-09-01 — The model shall consume active power and harmonics h1–h32; a variant trained on active power alone shall be kept as an ablation so the harmonics' contribution can be stated. V1 result (CO baseline, held-out sessions 05-16, 05-26, 06-24, 2026-10-04): harmonics cut fridge MAE from 3.0 W to 1.0 W and hair dryer from 2.1 W to 1.7 W, but raised iron, screen, and water heater error under the simple per-feature scaling used; net, harmonics do not help the CO baseline as built.
- TRS-09-02 — The model shall emit one output head per tracked appliance: a regression head (watts, ≥ 0) and a classification head (on\_prob ∈ \[0,1\]).
- TRS-09-03 — Training and test data shall be split by recording session. No session shall contribute samples to both sets (TRS-SYS-07).
- TRS-09-04 — The model shall be evaluated on at least one real held-out session, never only on synthetic timelines. Reported metrics shall be from the real session.

> Rationale: synthetic data is built from the same activation library the model trains on. A score on it measures memorisation.

- TRS-09-05 — Per-appliance held-out metrics shall be recorded with the model version: MAE in watts, F1 of on/off at a 10 W threshold, and the mean of estimated kWh divided by true kWh over the session.
- TRS-09-06 — The model shall emit no dollar, carbon, or recommendation output (TRS-SYS-01).
- TRS-09-07 — Inference over a 24 h window for one household shall complete in under 60 s on CPU, so that a nightly re-run is feasible without a GPU.
- TRS-09-08 — Every output row shall carry model\_version. A fine-tuned model shall carry the global version plus the household\_id suffix.

* TRS-09-09 — The hvac output head shall be trained on the synthesized track only (TRS-06-07). Its metrics shall be reported separately from the real-session metrics of TRS-09-05 and labelled "synthetic HVAC" wherever shown, including the dashboard details view (TRS-16-06). The pitch shall not claim real-data accuracy for HVAC.

* TRS-09-10 — The deployed model's output shall be stored as 60 s means per appliance, plus the baseload residual of TRS-08-05, with source='nilm', its model\_version, and a declared period of 60 s (TRS-08-03). The model shall read only the household's stored aggregate (CMP-07) and shall run on each replayed or live day. Deployed V1 model co-v2.1: the CO baseline on active power only (harmonics do not help it, TRS-09-01), plus an hvac state learned from the synthesized track only (TRS-09-09), plus a per-day baseload estimate (the 1st percentile of active power minus the always-on appliances, the fridge only, floored at zero), saved once to `data/models/co-v2.1.json`. Held-out real-session F1 at 10 W (MAE): fridge 0.94 (7 W), hair dryer 1.00 (2 W), iron 0.95 (3 W), water heater 0.67 (1 W), straightener 0.63 (5 W), laptop 0.26 (29 W), screen 0.07 (8 W); hvac 1.00 on synthetic days only. The laptop and screen fall against co-v1 because the 8 h dataset sessions keep them on throughout, so the baseload estimate absorbs them; on the 24 h demo days the estimate is within 6–14 W of the true 60 W except on the fridge-fault days (v0.10).

**Error handling.** A window containing a gap event (CMP-05) shall produce no output for the gapped span; it shall not interpolate across it. At 60 s means, any minute touched by a gap of more than 10 s produces no row.

**Verification criteria**

- Train on 12 sessions, test on 3; confirm all three metrics in TRS-09-05 are logged per appliance.
- Confirm the harmonics ablation is logged and the difference is reported.
- Replay a session with an injected 30 s gap; confirm no appliance rows exist for that span.
- Static check: the model module imports nothing from the tariff module.

**Dependencies.** CMP-00, CMP-07, CMP-08, CMP-10.

**Open issues.** OI-01, OI-03.

---

### CMP-10 — Household Fine-Tuning \[DEF\]

| Field | Value |
| --- | --- |
| Class | ML |
| Flowchart element | "Fine-tune NILM for this home" |
| Implementing tool | PyTorch, same architecture as CMP-09 |
| Owner | ML lead |

**Purpose.** Adapts the global NILM model to one household's actual appliances using the smart plug (CMP-02) as a label source during a calibration period. The production story: plug in for a week, then remove.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Global checkpoint | CMP-09 | Weights file |
| Labelled windows | CMP-07 aggregate aligned with CMP-08 plug rows | Windows where a plug row exists for the centre sample |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Household checkpoint | CMP-09 | Weights file, model\_version = global + '-' + household\_id |

**Requirements**

- TRS-10-01 — Fine-tuning shall update only the output heads of the plugged appliance; the shared encoder shall be frozen.
- TRS-10-02 — Fine-tuning shall require at least 20 activations of the plugged appliance before it runs; below that it shall log and skip.
- TRS-10-03 — The fine-tuned model shall be evaluated on the last 20% of plug-labelled windows (by time) and shall replace the global model for that household only if MAE improves. Otherwise the global model stays and the attempt is logged.
- TRS-10-04 — The global checkpoint shall never be modified by fine-tuning.

**Error handling.** Fewer than 20 activations: skip. Metric regression: keep global, log.

**Verification criteria**

- Supply 10 activations; confirm skip. Supply 25; confirm a household checkpoint is written and its MAE is compared to global.

**Dependencies.** CMP-02, CMP-07, CMP-08, CMP-09.

---

### CMP-11 — Advisor: Forecaster \[V1\]

| Field | Value |
| --- | --- |
| Class | ML |
| Flowchart element | "Forecaster: appliance kWh + weather → 7-day $" |
| Implementing tool | LightGBM per appliance (baseline, V1); LSTM comparison \[DEF\] |
| Owner | ML lead |

**Purpose.** The Advisor is one module with two sub-components: this forecaster and the counterfactual simulator (CMP-13), followed by the narrator (CMP-20). From the outside it takes history plus weather and returns next week's bill, the ranked changes, and the sentences that describe them. Inside, the forecaster predicts each appliance's hourly kWh for the next 7 days from its own history and the weather forecast. The spike alert and the projected bill are derived from it.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Appliance hourly history | CMP-08 appliance\_hourly | ≥ 14 days, per appliance |
| Weather history and forecast | CMP-08 weather | Hourly, 14 days back, 7 days forward |
| Calendar features | Derived | hour, weekday, is\_weekend |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Appliance kWh forecast | CMP-08 forecasts, CMP-13, CMP-15 | {household\_id, appliance\_id, ts, kwh\_p50, kwh\_p90, model\_version, made\_at} for 168 hours |

**Requirements**

- TRS-11-01 — The forecaster shall predict kWh only. Conversion to dollars is performed by CMP-15 using CMP-04 (TRS-SYS-01).
- TRS-11-02 — Features shall include lagged kWh (1 h, 24 h, 168 h), temp\_c, hour, weekday. Weather shall be the forecast value for future hours, never the observed value.
- TRS-11-03 — The model shall emit a p50 and a p90 so the dashboard can show a range (TRS-16-05). V1: p90 = p50 + the 90th percentile of the residuals on the held-out 20% (per appliance), never below p50.
- TRS-11-04 — Evaluation shall use a time-ordered split: train on the first 80% of the timeline, test on the last 20%. Random shuffling is prohibited (TRS-SYS-07).
- TRS-11-05 — Per-appliance MAE (kWh/h) on the test split shall be stored with the model version and shall be beaten by the chosen model against a seasonal-naive baseline (same hour, previous week). A model that does not beat the baseline shall not be deployed.
- TRS-11-06 — The forecaster shall refresh whenever CMP-03 delivers a new forecast and at least every 6 hours.
- TRS-11-07 — Each forecast row shall carry made\_at; superseded forecasts shall be retained (TRS-SYS-04).

**Error handling.** Fewer than 14 days of history: emit the seasonal-naive forecast, flagged model\_version='naive'.

**Verification criteria**

- Train on a 28-day synthetic timeline; confirm MAE on the last 20% is logged and beats seasonal-naive.
- Confirm no feature column contains observed weather for timestamps after made\_at.

**Dependencies.** CMP-03, CMP-04, CMP-08.

---

### CMP-12 — Appliance Anomaly Detector \[V1\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | "Anomaly detector: duty cycle vs. own baseline" |
| Implementing tool | Python, pandas; robust z-score on rolling statistics |
| Owner | ML lead |

**Purpose.** Flags an appliance whose behaviour has drifted from its own history, which usually means a maintenance problem (fridge seal, clogged filter) rather than a habit. The feature existing products rarely offer.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Appliance 2 s rows | CMP-08 appliance\_power | Last 24 h for the appliance |
| Appliance baseline | CMP-08 appliance\_daily, prior 14 days | Per-day duty cycle, cycles/day, mean on-watts |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Health alert | CMP-08 alerts, CMP-16 | {household\_id, appliance\_id, ts, feature, today\_value, baseline\_median, baseline\_mad, z, severity} |

**Requirements**

- TRS-12-01 — The detector shall be deterministic: median and MAD over the baseline window, z = (today − median) / (1.4826 · MAD). No learned model. The baseline window is the latest 14 earlier days that were not themselves scored anomalous (|z| > 3 on duty\_cycle or mean\_on\_watts); without that skip a fault lasting a week becomes the new median and the alert closes while the fault persists (v0.9).
- TRS-12-02 — Features shall be duty\_cycle, cycles\_per\_day, and mean\_on\_watts, computed per appliance per day. The appliance type selects the features (TRS-14-02): V1 monitors the fridge only. Event loads (hair dryer, iron) have no stable daily baseline and HVAC follows the weather, so they carry no anomaly features in V1 (v0.9).
- TRS-12-03 — An alert shall be raised when |z| > 3 for duty\_cycle or mean\_on\_watts on two consecutive days. A single-day excursion shall not alert.

> Rationale: one hot day lengthens fridge cycles legitimately. Two days in a row with the baseline already weather-mixed is a change in the appliance.

- TRS-12-04 — The detector shall run only on appliances with at least 10 baseline days. Below that it shall record "insufficient history".
- TRS-12-05 — Alert text shall state the feature and the magnitude in plain terms ("fridge is drawing 38% more than its usual") and shall not name a cause. Suggested causes, if shown, are a static lookup by appliance type in CMP-16.
- TRS-12-06 — An alert shall carry severity: watch (3 < |z| ≤ 5) or act (|z| > 5).

**Error handling.** MAD = 0 (constant baseline): use 0.01 × median as the scale and log the substitution.

**Verification criteria**

- Replay a CMP-06 timeline with a fridge fault at day 12 (+40% mean\_on\_watts); confirm an alert on day 13 or 14 and none before day 12.
- Replay with no fault; confirm zero alerts over 14 days.

**Dependencies.** CMP-06 (for test), CMP-08.

---

### CMP-13 — Advisor: Counterfactual Simulator \[V1\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | "Counterfactual simulator: shift or trim load → $ and CO₂ saved" |
| Implementing tool | Python, pandas |
| Owner | Backend lead |

**Purpose.** Second sub-component of the Advisor (see CMP-11). Prices a concrete change. Takes the forecast, applies one transformation to one appliance, re-costs both timelines under the tariff, and reports the difference. The source of every action the user sees. Requirement IDs TRS-13-nn are retained for stability.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Appliance kWh forecast | CMP-11 | 168 h, per appliance |
| Rate lookup | CMP-04 | rate(ts) |
| Action template library | Static YAML | Annex A: templates with action\_type, shape, applies\_to, params, optional search range |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Priced action | CMP-17 | {household\_id, appliance\_id, action\_type, params, baseline\_usd, counterfactual\_usd, saving\_usd, saving\_kg\_co2, assumption\_text, forecast\_made\_at} |

**Requirements**

- TRS-13-01 — The simulator shall evaluate only the templates in the Action Template Library (ATL, Annex A). Action shapes in V1 shall be: shift (move an appliance's forecast kWh out of a set of hours into the cheapest permitted hours, energy-preserving), trim (scale an appliance's kWh by a factor), setpoint (change a thermostat setpoint, or install a weekday setpoint schedule (v0.11); kWh effect from the thermostat model of TRS-06-07), and maintenance (scale kWh by a factor, enabled only while a CMP-12 alert is open).
- TRS-13-02 — Baseline cost and counterfactual cost shall be computed by the same function over the same tariff; saving shall be their difference, never an independently estimated number.
- TRS-13-03 — Every priced action shall carry assumption\_text stating what was changed in one sentence ("assumes all dryer use between 3–7 pm moves to 7–9 pm").
- TRS-13-04 — Actions whose saving\_usd is below $1/month shall be computed but not surfaced. saving\_usd is the saving over the forecast horizon (7 days); the floor is applied to its monthly equivalent, saving\_usd × 30.4375 / 7, and the dashboard shows that same monthly equivalent (TRS-16-08).
- TRS-13-05 — Under a flat tariff, shift actions shall report saving\_usd = 0 and shall not be surfaced; trim and setpoint actions remain (TRS-04-02).
- TRS-13-06 — The simulator shall emit at most 3 actions per household per refresh, ranked by saving\_usd.
- TRS-13-07 — The simulator shall contain no learned component (TRS-SYS-01).

* TRS-13-08 — Actions shall be issued as one batch per week\_id. Within a week the batch may be re-priced on each forecast refresh but shall not change its action set unless an action is dismissed. A dismissed action is not re-issued in the same week; its slot is filled by the next-ranked surfaced action at the next refresh.
* TRS-13-09 — Ranking shall be by saving\_usd × (0.5 + success\_score) using CMP-18's score for the household and action\_type; a null score shall rank as 0.5 (neutral).
* TRS-13-10 — An action\_type dismissed in 3 consecutive weeks for a household shall be suppressed for the following 4 weeks, and the suppression recorded with its reason. A dismissal by the user and an expiry at week end (TRS-17-06) both count. The suppression is read back from its record each week so it lasts the full 4 weeks.
* TRS-13-11 — Each issued action shall carry week\_id and shall record the success\_score used at ranking time, so the ranking can be audited later.

- TRS-13-12 — Where a template declares a search range for one or more parameters (Annex A, `search`), the simulator shall evaluate every combination of the values in the ranges at the declared steps and keep the combination with the greatest saving\_usd. The chosen values shall be recorded in params. Several ranges added in v0.11 (precool adapts its length and depth to each week).
- TRS-13-13 — Cold start: in a household's first week, or for any action\_type with a null success score, ranking shall be by saving\_usd alone, and the narrator input shall carry first\_week=true so the Actions tab can say the Tracker is still learning what works for this household.

**Error handling.** A template referencing an appliance the household lacks is skipped silently.

**Verification criteria**

- Two-period tariff, dryer forecast concentrated at 17:00; confirm a shift-to-21:00 action with saving equal to kWh × (peak − off-peak) rate.
- Flat tariff; confirm the same action prices at $0 and is not surfaced.
- Confirm baseline\_usd equals the CMP-15 projected cost for the same appliance and horizon.

**Dependencies.** CMP-04, CMP-11, CMP-17.

### CMP-14 — Onboarding and Household Profile \[V1\]

| Field | Value |
| --- | --- |
| Class | UI / STORE |
| Flowchart element | "Onboarding: home profile, ZIP, utility tariff" |
| Implementing tool | Dashboard form; households and appliances tables in CMP-08 |
| Owner | Frontend lead |

**Purpose.** Captures the few facts the Tracker cannot sense: where the home is, which tariff applies, which appliances exist, and which plug is on which appliance.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Profile form | Household head | {zip, tariff\_id, appliances: \[{appliance\_id, type, label}\], plug\_bindings: \[{plug\_id, appliance\_id}\], occupants} |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Household record | CMP-08 households, appliances | Rows |
| Location | CMP-03 | lat/lon from ZIP |
| Tariff selection | CMP-04 | tariff\_id |

**Requirements**

- TRS-14-01 — Onboarding shall complete in one screen. Since v0.12 it is a sign-up asking name, email, password (at least 8 characters) and a 5-digit ZIP, or a log-in, and leads straight to the main tab. Passwords are stored only as salted scrypt hashes in a private table; a session is a signed cookie, and every API route except sign-up and log-in requires one. Every account opens the one demo household until OI-07 and OI-10 are settled; the tariff is not asked yet. Appliances may be added later.
- TRS-14-02 — Each appliance shall carry a type from a closed list (fridge, water\_heater, hair\_dryer, iron, laptop, screen, lamp, straightener, hvac, dryer, oven, ev, other). The type selects the NILM output head, the anomaly features, and the action templates.
- TRS-14-03 — A plug may be bound to at most one appliance; rebinding shall end the previous binding with a timestamp, not overwrite it.
- TRS-14-04 — The profile shall be editable at any time; edits shall be versioned.

**Error handling.** Unknown ZIP: reject with a message; do not default to a location.

**Verification criteria**

- Submit ZIP + tariff only; confirm the household exists and CMP-03 begins backfill.
- Rebind a plug; confirm two binding rows, the first closed.

**Dependencies.** CMP-03, CMP-04, CMP-08.

---

### CMP-15 — Query and Costing API \[V1\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | Not drawn; sits between the stores and the dashboard |
| Implementing tool | FastAPI, Python 3.11 |
| Owner | Backend lead |

**Purpose.** The only thing the dashboard talks to. Reads rollups and forecasts, multiplies kWh by the tariff, and returns the numbers every panel shows. Centralising costing here is how TRS-SYS-01 is enforced.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Dashboard requests | CMP-16 | HTTP, authenticated per household |
| Rollups, forecasts, alerts, actions | CMP-08 | SQL |
| Rate lookup | CMP-04 | rate(ts) |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| /summary | CMP-16 | {month\_to\_date\_usd, projected\_month\_usd, projected\_p90\_usd, vs\_last\_month\_pct} |
| /appliances | CMP-16 | Per appliance: {kwh\_today, usd\_month\_to\_date, share\_pct, source, model\_version, live\_watts, stale} |
| /spikes | CMP-16 | Forecast days where projected\_usd > baseline × (1 + margin): {day, delta\_usd, driver\_appliance} |
| /alerts | CMP-16 | CMP-12 alerts, open |
| /actions | CMP-16 | CMP-13 actions, open, ranked |
| /tariff | CMP-16 | The active rate table (TRS-04-04) |

**Requirements**

- TRS-15-01 — Every dollar figure shall be computed in this component as Σ kWh(ts) × rate(ts).usd\_per\_kwh over the relevant rows. No dollar figure shall be stored precomputed except in CMP-17 action records, which carry their forecast\_made\_at.
- TRS-15-02 — The projected month shall be month-to-date actual plus the CMP-11 p50 forecast for the remaining hours; projected\_p90 uses the p90.
- TRS-15-03 — A spike shall be reported when a forecast day's cost exceeds the trailing 14-day mean daily cost by more than 25%. The margin shall be a single named constant.
- TRS-15-04 — Every per-appliance response shall include source and model\_version (TRS-SYS-02).
- TRS-15-05 — Every endpoint shall respond in under 300 ms for a household with 30 days of data on demo hardware. Measured 2026-10-04 with the store on Maincloud: 225–650 ms per endpoint, dominated by SQL round trips; not met (OI-12).
- TRS-15-06 — The API shall read CMP-07 and CMP-08 over the SQL endpoint and shall call only the action and alert status-transition reducers; it shall never call `ingest_batch` or `write_appliance_power`.

**Error handling.** Missing forecast: /summary returns projected = null with reason='no\_forecast'; the dashboard shows month-to-date only.

**Verification criteria**

- Seed 30 days; confirm /summary month\_to\_date\_usd equals a hand computation over the hourly rollup and the tariff.
- Change the tariff; confirm every dollar figure changes and no stored value had to be rewritten.
- Time each endpoint; confirm < 300 ms.

**Dependencies.** CMP-04, CMP-08, CMP-11, CMP-12, CMP-13, CMP-17.

---

### CMP-16 — Household Dashboard \[V1\]

| Field | Value |
| --- | --- |
| Class | UI |
| Flowchart element | "What the user sees" (five panels) |
| Implementing tool | React + TypeScript, charts via a lightweight SVG library |
| Owner | Frontend lead |

**Purpose.** The product. The main tab is a dashboard of past and current state: what the home is spending, what is driving it, what is about to happen, what is wrong, and the single change with the biggest impact. The Actions tab is where the household acts.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| All panel data | CMP-15 | JSON |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Action disposition | CMP-17 via CMP-15 | {action\_id, status} |
| Alert acknowledgement | CMP-08 alerts via CMP-15 | {alert\_id, acknowledged\_at} |

**Requirements**

- TRS-16-01 — The dashboard's main tab shall show exactly five panels in this order: month summary, appliance breakdown, spike alert, appliance health, biggest impact change. Nothing else above the fold on that tab. The main tab carries no action controls (v0.6). The spike panel is titled "Looking ahead" (v0.12).
- TRS-16-02 — The month summary shall show month-to-date, projected total, and the projected range (p50 to p90) as a single visual, with the comparison to last month as a signed percentage. Tapping a day that has happened selects it (secondary colour, light yellow) and opens that day's appliance rundown below the chart, in the same rows as the appliance breakdown (v0.12).
- TRS-16-03 — The appliance breakdown shall update live (≤ 5 s latency from a plug sample) for measured appliances and at the rollup cadence for estimated ones. Each tile shall display "measured" or "estimated" (TRS-SYS-02).
- TRS-16-04 — A stale measured tile shall show its staleness; it shall not revert to the estimate (TRS-02-04).
- TRS-16-05 — Every forecast figure shall be shown with its range, never as a point alone.
- TRS-16-06 — The appliance breakdown shall expose the held-out error of the NILM model version in use (TRS-09-05) on a details view, in watts and as a share of that appliance's typical draw. Typical draw is the appliance's learned on-level in the deployed model (v0.12).
- TRS-16-07 — At the demo, any panel driven by replayed data shall carry a visible "simulated feed" marker (§4.2).
- TRS-16-08 — The biggest impact change panel shall show the highest-ranked open action's saving in $/month and kg CO₂/month and its assumption\_text, with a link to the Actions tab. It shall carry no accept, dismiss, or Take action control; actions are taken only on the Actions tab (TRS-16-11).
- TRS-16-09 — The dashboard shall render usably at 400 px width.
- TRS-16-10 — The dashboard shall contain no costing or modelling logic; every number shall arrive from CMP-15 as displayed.

* TRS-16-11 — The dashboard shall have a second tab, Actions, listing the narrator's statements (CMP-20) in CMP-13 rank order, each with its source action\_id and its dollar and CO₂ figures as computed by CMP-15. A right-hand column named "Take action" shall hold one button per statement whose action is viable: status proposed, saving\_usd at or above the TRS-13-04 floor, not dismissed, not suppressed. Beside it, each viable row shall carry a Dismiss button, which transitions the action to dismissed with reason='user' (TRS-17-02). A non-viable row shows neither button. Tapping Take action is the user tap of TRS-SYS-03: it accepts the action (TRS-17-02) and, for an action whose template names an actuator, opens the CMP-19 confirm step (TRS-19-08). No speech synthesis and no voice channel in V1 (changed in v0.4).
* TRS-16-12 — The dashboard shall have a third tab, Savings, showing the running total of verified savings (CMP-18) separate from proposed savings (TRS-18-04), and a list of past actions with their outcome: verified, not verified, dismissed, or expired. Every figure arrives from CMP-15 (TRS-16-10). The tab carries no action controls (v0.8).

**Error handling.** API unreachable: show the last successful payload with its age; never a blank page.

**Verification criteria**

- Switch a plugged kettle on; confirm the tile updates within 5 s and reads "measured".
- Replay a timeline with a fridge fault; confirm the health panel shows the alert after CMP-12 raises it.
- Grep the frontend for usd\_per\_kwh; confirm zero occurrences.

**Dependencies.** CMP-15, CMP-17.

---

### CMP-17 — Action Ledger \[V1\]

| Field | Value |
| --- | --- |
| Class | STORE |
| Flowchart element | "User accepts action?" decision + "Track actual savings" |
| Implementing tool | SpacetimeDB public table `action` plus `action_transition` |
| Owner | Backend lead |

**Purpose.** Makes every suggestion a first-class object with a lifecycle, so that "did it work" can be answered later (TRS-SYS-05).

**Schema**

| Field | Type | Purpose |
| --- | --- | --- |
| action\_id | uuid | Identity |
| household\_id, appliance\_id | text | Scope |
| action\_type, params | text, jsonb | What was simulated |
| saving\_usd, saving\_kg\_co2 | numeric | From CMP-13 |
| assumption\_text | text | From CMP-13 |
| forecast\_made\_at | timestamptz | Which forecast priced it |
| status | enum | proposed, accepted, dismissed, verified, not\_verified |
| status\_at | timestamptz | Last transition |
| verified\_saving\_usd | numeric | From CMP-18, nullable |

**Requirements**

- TRS-17-01 — Rows shall never be deleted. A proposal still open at the end of its week is marked dismissed with reason='expired' (TRS-17-06); a user dismissal carries reason='user'.
- TRS-17-02 — Only CMP-13 shall insert proposed rows; only CMP-16 (via CMP-15) shall transition to accepted or to dismissed by the user; only the week-end close (TRS-17-06) shall transition to dismissed by expiry; only CMP-18 shall transition to verified or not\_verified.
- TRS-17-03 — A household shall have at most 3 rows in status proposed at any time (TRS-13-06).
- TRS-17-04 — Every status transition shall be logged with the actor and timestamp.

* TRS-17-05 — Every row shall carry week\_id (ISO week of issue) and the success\_score it was ranked with, so that CMP-18 can evaluate a week as a unit.
* TRS-17-06 — At the end of each week\_id (Monday 00:00 household local time), every action of that week still in status proposed shall be transitioned to dismissed with reason='expired' and actor='week\_close', logged per TRS-17-04. The close runs with the weekly job (TRS-18-06) and again, idempotently, before the next week's proposals are issued, so no proposal outlives its week.

**Verification criteria**

- Accept an action; confirm status, status\_at, and the transition log entry.
- Dismiss an action; confirm reason='user' and that its slot is refilled at the next refresh but the action is not re-issued that week.
- Leave an action untaken past its week's end; confirm it is dismissed with reason='expired' and actor='week\_close', and that an accepted action of the same week is untouched.
- Confirm no code path issues DELETE on the table.

**Dependencies.** CMP-13, CMP-15, CMP-16, CMP-18.

---

### CMP-18 — Savings Verifier and Outcome Scorer \[V1 / DEMO\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | "Track actual savings vs. forecast baseline" |
| Implementing tool | Python, scheduled daily |
| Owner | Backend lead |

**Purpose.** Closes the loop. At the end of each week, compares what each accepted action's appliance actually cost to what the baseline forecast said it would, records whether the saving appeared, and maintains a per-household success score per action type. That score is how the Advisor learns which kinds of suggestion this family acts on. In V1 the week elapses on the replayed timeline.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Accepted actions | CMP-17 | status = accepted, accepted ≥ 7 days ago |
| Baseline forecast | CMP-08 forecasts at forecast\_made\_at | Per appliance, 168 h |
| Actual kWh | CMP-08 appliance\_hourly | Same window |
| Rate lookup | CMP-04 | rate(ts) |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Verification | CMP-17 | {action\_id, verified\_saving\_usd, status} |

**Requirements**

- TRS-18-01 — Verified saving shall be baseline forecast cost minus actual cost for the appliance over the 7 days after acceptance, both under the tariff in force (TRS-15-01). The window is clipped to the 168 h horizon of the forecast that priced the action, and the expected saving is the priced saving scaled to the hours compared (v0.9).
- TRS-18-02 — An action shall be marked verified when verified\_saving\_usd ≥ 0.5 × saving\_usd, otherwise not\_verified. The threshold shall be a single named constant.
- TRS-18-03 — The verifier shall use the forecast that priced the action (forecast\_made\_at), never a later one.

> Rationale: a later forecast already knows about the behaviour change. Comparing against it erases the saving.

- TRS-18-04 — Verification results shall be shown on the dashboard's Savings tab (TRS-16-12) as a running total of verified savings, separate from proposed savings.

* TRS-18-05 — At each weekly evaluation the verifier shall compute, per household and per action\_type, a success score = (verified + 0.5 × accepted-but-not-yet-verified) / (proposed) over the trailing 8 weeks, and write it to CMP-08 outcome\_scores with week\_id. An action\_type with fewer than 2 proposals shall carry a null score.
* TRS-18-06 — The verifier shall run once per week\_id, after the week's last rollup, and shall also run on demand for the demo.
* TRS-18-07 — Scores shall be recomputed from the ledger each week, never incrementally updated, so that a correction to the ledger changes the score (TRS-SYS-04).

**Verification criteria**

- Accept a shift action on a replayed timeline; replay the next 7 days with the dryer shifted; confirm verified. Replay unshifted; confirm not\_verified.

**Dependencies.** CMP-04, CMP-08, CMP-17.

---

### CMP-19 — Device Actuator \[V1 / DEMO\]

| Field | Value |
| --- | --- |
| Class | DET |
| Flowchart element | "Take action" control under the heating/cooling tile; not yet on the flowchart |
| Implementing tool | V1: simulated thermostat (a state row in CMP-08 plus a dashboard widget). Production: Google Smart Device Management API for Nest; ecobee API as an alternative |
| Owner | Backend lead |

**Purpose.** Turns an accepted setpoint action into a real change on a device, or an accepted schedule action into a schedule the device runs itself (v0.11), so the forecast ends in something the household can see happen. The only component in the Tracker that holds a device handle.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Accepted setpoint action | CMP-17, via a user tap in CMP-16 | {action\_id, appliance\_id, params: {target\_setpoint\_c}} |
| Accepted schedule action (v0.11) | CMP-17, via a user tap in CMP-16 | {action\_id, appliance\_id, params: {schedule, pre\_hours, pre\_cool\_c, peak\_warm\_c, peak\_start, peak\_end}} |
| Device bounds | CMP-14 | {appliance\_id, min\_setpoint\_c, max\_setpoint\_c, max\_step\_c} |
| Device state | Device adapter (simulated or SDM) | {appliance\_id, current\_setpoint\_c, mode, read\_at} |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Device command | Device adapter | set\_setpoint(appliance\_id, target\_c); install\_schedule / remove\_schedule (v0.11) |
| Actuation log | CMP-08 actuations | {action\_id, appliance\_id, previous\_c, requested\_c, applied\_c, result, actor, ts} |
| Undo token | CMP-16 | {action\_id, previous\_c, expires\_at} |

**Requirements**

- TRS-19-01 — The actuator shall execute only in response to a user tap on a specific action\_id in status accepted. It shall expose no interface callable by CMP-11, CMP-12, CMP-13, or any scheduler (TRS-SYS-03).
- TRS-19-02 — The requested setpoint shall be clamped to \[min\_setpoint\_c, max\_setpoint\_c\] from CMP-14, and the change from the current setpoint shall be limited to max\_step\_c per action. Defaults: 18–27 °C, 2 °C per action. The applied value, if clamped, shall be shown to the user before the command is sent.
- TRS-19-03 — Every actuation shall write a log row before the command is sent and update it with the result after. A command with no log row shall be impossible by construction.
- TRS-19-04 — The dashboard shall offer undo for 24 h after an actuation. Undo restores previous\_c through the same actuator and is logged as its own actuation with actor='undo'.
- TRS-19-05 — The actuator shall read the device state before every command and shall refuse to act if the state is older than 5 minutes or the device is unreachable, reporting the reason to the user.
- TRS-19-06 — The device adapter shall be a single interface (read\_state, set\_setpoint, install\_schedule, remove\_schedule) with two implementations: simulated (V1) and SDM (production). No other code shall differ between the two.
- TRS-19-07 — The simulated adapter shall apply the setpoint to the replayed timeline by scaling the hvac track per CMP-13's setpoint factor from the actuation timestamp forward, so that the dashboard's live breakdown visibly responds to the tap. An installed schedule is applied the same way, step by step, while it is in force (v0.11).
- TRS-19-08 — The tap control shall state the device, the current and target setpoint, and the expected saving from CMP-13 before the user confirms. One tap to open, one tap to confirm. Actions with no device change (advice only) are accepted on a single tap of Take action.
- TRS-19-09 — At the demo, the simulated device shall carry the "simulated" marker (TRS-16-07).

* TRS-19-10 — A schedule action (Annex A template with `schedule`) shall install, on one tap to open and one to confirm (TRS-19-08), a weekday schedule on the device: from peak\_start − pre\_hours to peak\_start the setpoint is the current setpoint − pre\_cool\_c; from peak\_start to peak\_end it is the current setpoint + peak\_warm\_c; at other times the current setpoint. Each value is clamped to the CMP-14 bounds and to max\_step\_c from the current setpoint (TRS-19-02), and the clamped values are shown before confirmation. Offsets apply to the setpoint in force at each moment, so a later setpoint tap keeps the schedule relative. V1 precool: peak\_warm\_c 2; pre\_hours (1–3) and pre\_cool\_c (0.5–2 °C) chosen each week by the TRS-13-12 search; weekdays only.
* TRS-19-11 — A schedule shall carry valid\_until = the end of its action's week\_id (Monday 00:00 local, TRS-17-06), after which the device stops applying it. No Tracker component re-sends, extends, or renews a schedule; next week's batch may propose it again. At most one schedule per device is in force at a time.
* TRS-19-12 — Installing and removing a schedule follow TRS-19-03 (log row before the command), TRS-19-04 (undo for 24 h removes it, logged with actor='undo') and TRS-19-05 (fresh device state). The thermostat view shall show an installed schedule, its hours, and when it ends.

**Error handling.** Adapter error: log result='failed' with the error, show it to the user, leave the action in status accepted so it can be retried. Never retry automatically.

**Verification criteria**

- Tap a setpoint action on the simulated device; confirm a log row with previous\_c and applied\_c, the thermostat widget updates, and the hvac tile's live watts change within one rollup cycle.
- Request a 5 °C change; confirm it is clamped to 2 °C and the clamped value is displayed before confirmation.
- Tap undo; confirm previous\_c is restored and a second log row with actor='undo' exists.
- Static check: grep for set\_setpoint; exactly one call site, inside the actuator. Same for install\_schedule and remove\_schedule.
- Tap precool; confirm the preview states both setpoints and the end date, a schedule row and a log row exist, and the replayed hvac track follows the schedule on weekdays only and stops at the week's end.
- Undo an installed schedule within 24 h; confirm it is removed and logged with actor='undo'.
- Confirm no scheduler, model, or API route other than the tap handler can reach the actuator.

**Dependencies.** CMP-08, CMP-13, CMP-14, CMP-16, CMP-17.

**Open issues.** OI-08.

---

### CMP-20 — Advisor: Narrator \[V1\]

| Field | Value |
| --- | --- |
| Class | AI |
| Flowchart element | Not yet on the flowchart; sits between CMP-13 and the Actions tab |
| Implementing tool | Google Gemini via the Gemini API with a JSON response schema, behind a thin NarratorBackend protocol |
| Owner | Backend lead |

**Purpose.** Third sub-component of the Advisor. Turns the simulator's structured actions and the forecaster's spike into short plain-language sentences a household would actually say to each other, shown on the Actions tab. The only AI-classified component in the Tracker.

**Inputs**

| Name | Source | Format |
| --- | --- | --- |
| Priced actions | CMP-13, via CMP-17 | Up to 3: {action\_id, appliance label, action\_type, params, saving\_usd, saving\_kg\_co2, assumption\_text} |
| Spike summary | CMP-15 /spikes | {day, delta\_usd, driver\_appliance} |
| Household vocabulary | CMP-14 | Appliance labels as the household named them |
| Outcome history | CMP-17, CMP-18 | Last week's actions for this household: {action\_id, appliance label, action\_type, status, verified\_saving\_usd}; plus the success\_score per action\_type |

**Outputs**

| Name | Destination | Format |
| --- | --- | --- |
| Statement | CMP-08 statements, CMP-16 Actions tab | {statement\_id, action\_id or spike ref, text, model\_version, created\_at} |

**Requirements**

- TRS-20-01 — The narrator shall receive only structured records. It shall not read raw usage, rollups, weather, or the tariff.
- TRS-20-02 — The narrator shall not originate, round, convert, or alter any number. Every number in its output text shall equal, as a string, a number present in its input record. A statement failing this check shall be discarded and the attempt logged (TRS-SYS-01). A statement discarded for failing a check is replaced by its fallback and retried on the next narrator run (v0.9.1); the prompt asks for 25 words to leave room under the 30-word limit.

> Rationale: "about nine dollars" when the input says 9.10 is a rounding the narrator invented. The simulator decides what to show; the narrator decides how to say it.

- TRS-20-03 — The narrator shall not propose actions. Its output shall be one statement per input action and shall name no appliance, time, or behaviour absent from that action's record.
- TRS-20-04 — Output shall be structured: {action\_id, text}. A response that is not valid against the schema shall be retried once with the schema error, then discarded.
- TRS-20-05 — Each statement shall be at most 30 words. Since v0.12 unit symbols are used ($, °C, °F) as everywhere else on the dashboard, since the voice channel that required spoken-only text was removed in v0.4; abbreviations such as A/C are not.
- TRS-20-06 — The narrator shall run only when CMP-13 produces new actions or CMP-15 reports a new spike; never on a schedule of its own. V1 narrates actions only, re-narrating when an action's structured input changes; spike statements have no surface since the Voice tab was removed (v0.4) and are not built.
- TRS-20-07 — Model access shall go through a NarratorBackend protocol with one method, so that the provider can be swapped without touching any other component. The instructions live in `config/narrator.md`; editing them re-narrates every open action (v0.11.1). Each statement says the concrete change (device, days, times, setting) and then the monthly saving; carbon and history are shown elsewhere on the tab.
- TRS-20-08 — Every statement shall carry model\_version and shall be retained; a superseded statement is marked superseded, never deleted.

* TRS-20-09 — The narrator may reference the outcome history in a statement ("last week's dryer change saved 8.20") and shall use it to choose tone and framing only. TRS-20-02 and TRS-20-03 apply to history figures as to all others: every number verbatim from the input, no action originated.
* TRS-20-10 — Where an action was not\_verified, the narrator shall not claim or imply it saved money.

**Error handling.** Provider unreachable: the Actions tab shows the action's assumption\_text from CMP-13 as a fallback, marked unnarrated; the Take action button is unaffected. Never block the main tab on the narrator.

**Verification criteria**

- Feed an action with saving\_usd = 9.10; confirm the statement contains "9.10" and no other dollar figure.
- Feed a record naming only the dryer; confirm the statement mentions no other appliance.
- Return malformed JSON from a stub backend; confirm one retry, then fallback to assumption\_text.
- Static check: the narrator module imports nothing from the tariff, forecast, or rollup modules.

**Dependencies.** CMP-13, CMP-14, CMP-15, CMP-16, CMP-17.

**Open issues.** OI-09.

### CMP-00 — Activation Library and Evaluation Set \[V1 — PREREQUISITE\]

| Field | Value |
| --- | --- |
| Class | STORE / test asset |
| Flowchart element | Not on the flowchart. It is the precondition for CMP-06, CMP-09, and CMP-12. |
| Implementing tool | Version-controlled Parquet files + pytest corpus |
| Owner | ML lead |

**Purpose.** The cleaned, session-split, per-appliance ground truth from the Dinar et al. dataset. Every model metric in this document is measured against it, and every synthetic timeline is built from it.

**Requirements**

- TRS-00-01 — The library shall hold, per appliance, every activation extracted from every retained session: a contiguous run where sub-metered p\_active\_w > 10 W for ≥ 3 samples, with all 37 fields and a 5-sample margin either side.
- TRS-00-02 — Sessions shall be split into train (12) and test (3) once, by session, and the split recorded in a file. No component shall re-split.
- TRS-00-03 — A session shall be excluded when the sum of its appliance files differs from its aggregate by more than 10% of aggregate mean over the session. Session 05-21 is excluded under this rule: measured ratio 1.18 (not 5.33 as first recorded), caused by six of its eight sub-meter files stopping after about four minutes while the aggregate ran for three hours. CMP-00 records per-appliance coverage alongside the ratio so the cause is visible. All other sessions measure 0.96–1.00.
- TRS-00-04 — The library shall record, per appliance, the activation count and on-time fraction, so that appliances with too few activations (iron, lamp, screen in this dataset) are flagged before anyone trains on them.
- TRS-00-05 — The set shall include at least one real test session with an injected 30 s gap and one with a duplicated timestamp, as negative cases for CMP-05 and CMP-09.
- TRS-00-06 — The set shall be version-controlled and shall serve as the pytest corpus.

**Verification criteria.** Activation count per appliance per session logged and reviewed by a second team member; the split file committed before any training run.

## 6. Traceability

| System requirement | Realised by |
| --- | --- |
| TRS-SYS-01 | TRS-04-04, TRS-09-06, TRS-11-01, TRS-13-02, TRS-13-07, TRS-15-01, TRS-16-10, TRS-20-02, TRS-20-03 |
| TRS-SYS-02 | TRS-02-03, TRS-08-02, TRS-09-08, TRS-15-04, TRS-16-03 |
| TRS-SYS-03 | TRS-19-01, TRS-19-02, TRS-19-03, TRS-19-04, TRS-19-07, TRS-19-10, TRS-19-11, TRS-19-12 |
| TRS-SYS-04 | TRS-03-02, TRS-07-02, TRS-08-06, TRS-11-07 |
| TRS-SYS-05 | TRS-13-03, TRS-13-09, TRS-13-11, TRS-17-01, TRS-17-04, TRS-17-05, TRS-18-04, TRS-18-05 |
| TRS-SYS-06 | Implementing-tool fields of CMP-05 … CMP-18 |
| TRS-SYS-07 | TRS-00-02, TRS-09-03, TRS-09-04, TRS-11-04, TRS-11-05, TRS-16-06 |

## 7. Open issues

| ID | Issue | Blocks | Owner |
| --- | --- | --- | --- |
| OI-01 | RESOLVED 2026-10-03: HVAC is synthesized from weather in CMP-06 (TRS-06-07 to 06-09) with its metrics labelled synthetic (TRS-09-09). Dryer, oven, and EV remain absent; the shift-action demo uses the water heater and hair dryer from the real dataset. UK-DALE activations stay an option for a later version. | CMP-06, CMP-09, CMP-13 | ML lead, before the event |
| OI-02 | RESOLVED 2026-10-03: the demo uses DTE Time of Day 3–7 p.m. (D1.11), a weekday-afternoon peak plan; rates recorded in CMP-04. Remaining: confirm the current card before loading, and note that shift savings are small outside June–September. | CMP-04, CMP-13, CMP-16 | Shamanth, tonight |
| OI-03 | Whether a seq2point CNN trains to a useful F1 on 12 sessions (\~75 h) within the hackathon. Fallback: NILMTK combinatorial optimisation, which needs no training. 2026-10-04: CO baseline built (numpy, `co-v1`) and scored; seq2point not started. CO F1 at 10 W on held-out sessions: fridge 0.98, hair dryer 1.00, iron 0.81, laptop 0.71, water heater 0.63, screen 0.64, straightener 0.33. | CMP-09 | ML lead, first 6 hours |
| OI-04 | Carbon intensity source. V1 uses a static regional average. An hourly feed (Electricity Maps, WattTime) changes the CO₂ value of shift actions and would need an API key. | CMP-04 | Deferred |
| OI-05 | Hardware. Whether a smart plug arrives before the event, and whether anyone wants to clamp a CT on a real mains feed. Without the plug, CMP-02 and CMP-10 are dropped and "measured" never appears on the dashboard. | CMP-02, CMP-10, CMP-16 | Hardware lead |
| OI-06 | Cadence mismatch. The forecaster runs hourly; the anomaly detector runs daily; the dashboard polls every 5 s. Whether one scheduler (APScheduler) or three cron entries is undecided. | CMP-11, CMP-12 | Backend lead |
| OI-07 | Authentication. v0.12: simple accounts (sign-up and log-in, hashed passwords, signed session cookie), every account opening the one demo household. Multi-household auth (an account per home, with its own data) is not specified. | CMP-14, CMP-15 | Deferred |
| OI-08 | No Nest device is available to the team. V1 ships the simulated adapter only; the SDM adapter is specified but untested. Google Device Access enrollment (fee, OAuth, project setup) has not been started and its current terms are unverified. | CMP-19 | Backend lead, if a device turns up |
| OI-09 | Narrator access. The narrator is Gemini (decided). Gemini API key confirmed 2026-10-04 (gemini-2.5-flash on the Gemini API, key in `.env`); quota for the event not yet checked. Voice delivery (speech synthesis, Alexa) was removed from scope in v0.4; the statements are text on the Actions tab. | CMP-20, CMP-16 | Backend lead, before the event |
| OI-10 | Price-plan landing page. Decision of S. Shastry 2026-10-04: at account creation the household enters its price plan on a landing page, so every dollar figure uses its own prices (CMP-14, CMP-04). Implementation held until the dashboard runs end to end; raise it again then. Also settles where the active plan is shown on request (TRS-04-04). | CMP-14, CMP-04, CMP-16 | Claude to raise after step 7 |
| OI-11 | RESOLVED 2026-10-04 (decision of S. Shastry): a tap installs a bounded weekday precool schedule on the thermostat that ends with the action's week (TRS-SYS-03 reworded, TRS-19-10 to 19-12, Annex A). Precool is priced with the thermostat model running that schedule. | Annex A, CMP-19 | S. Shastry |
| OI-12 | TRS-15-05 latency not met on Maincloud (225–650 ms). Options: cache reads per poll in CMP-15, or have the dashboard subscribe to public tables directly. | CMP-15 | Backend lead |
| OI-13 | RESOLVED 2026-10-04 (decision of S. Shastry): NILM rows are stored at 60 s means like the simulated feed (TRS-09-10), about 13,000 rows per household-day. Deployed model co-v2.1 backfilled for the replayed demo days and run by the demo driver each day; the dashboard shows the estimate beside the simulated feed with its held-out error. An earlier fit, co-v2, counted the dataset laptop as always on; its rows for 2025-06-30 and its metrics stay under that version (TRS-08-06). | CMP-09, CMP-08 | S. Shastry |

## 8. Deferred scope

The following are specified above but are not implemented in the 36-hour V1. They are deliberate exclusions, recorded so that their absence reads as a decision rather than an omission.

| Component | Deferred because |
| --- | --- |
| CMP-10 Household fine-tuning | Needs a week of plug-labelled data per household. The demo can show one plug feeding labels but cannot show a fine-tuned model. The pitch describes it. |
| CMP-18 Savings verifier | Promoted to V1 on the replayed timeline, where a week elapses in minutes. Deferred only for live households, where 7 real days must pass before the first score exists. |
| CMP-11 LSTM comparison | LightGBM is the V1 forecaster. The neural comparison earns a slide only if it beats LightGBM on the time-ordered split; otherwise it is a distraction. |
| Hourly carbon intensity (OI-04) | A static average demonstrates the CO₂ panel. |
| Utility data-sharing ingestion | Green Button Connect and aggregator OAuth need utility approval. Named as the production path. |
| Multi-household auth (OI-07) | One household is enough to demonstrate the product. |

## Annex A — Action Template Library (ATL)

The ATL is the complete set of moves the simulator (CMP-13) may price. It bounds the kind of suggestion; the data decides the appliance, the parameters, the saving, and the rank. It is one YAML file, version-controlled, loaded at startup, and referenced by action\_type in CMP-17, CMP-18, and CMP-20.

### A.1 Schema

| Field | Type | Meaning |
| --- | --- | --- |
| action\_type | text, unique | Stable key. Used by the ledger and the success score. Never renamed; retire and add instead. |
| shape | enum | shift, trim, setpoint, maintenance |
| applies\_to | list of appliance types | From the closed list in TRS-14-02 |
| params | map | Fixed parameters for the shape |
| search | map or list of maps, optional | Parameters to optimise: {name, min, max, step} each. The simulator tries every combination (TRS-13-12). |
| requires\_alert | bool | Only priced while a CMP-12 alert is open for that appliance |
| requires\_tou | bool | Only priced when the tariff has more than one period (TRS-13-05) |
| actuator | text, optional | Device adapter to invoke on accept (CMP-19); absent means advice only |
| assumption | text | One sentence with {placeholders} filled from params; becomes assumption\_text |

### A.2 Templates (V1)

| action\_type | shape | applies\_to | params / search | Flags | Assumption |
| --- | --- | --- | --- | --- | --- |
| shift\_out\_of\_peak | shift | water\_heater, hair\_dryer, straightener, iron | from: tariff peak hours; search to\_hour 19–23 step 1 | requires\_tou | assumes weekday {appliance} use moves from {peak\_range} to after {to\_hour\_12} |
| hvac\_setpoint\_away | setpoint | hvac | search delta\_c 1–3 step 1; sign = +1 in cooling mode | actuator: thermostat | assumes the thermostat is set {delta\_c} °C warmer, to {target\_setpoint\_c} °C, all week |
| hvac\_precool | setpoint (schedule, v0.11) | hvac | schedule: precool; peak\_warm\_c 2, weekdays; peak hours from the tariff; search pre\_hours 1–3 step 1 and pre\_cool\_c 0.5–2 step 0.5 | requires\_tou, actuator: thermostat | assumes on weekdays the thermostat cools {pre\_cool\_c} °C from {pre\_range}, then sits {peak\_warm\_c} °C warmer from {peak\_range} |
| water\_heater\_setpoint | trim | water\_heater | factor 0.90 |  | assumes the water heater is turned down to 49 °C (120 °F) |
| trim\_standby | trim | laptop, screen, lamp | factor 0.85 |  | assumes the {appliance} is switched off at the wall when not in use |
| fridge\_service | maintenance | fridge | factor 0.85 | requires\_alert | assumes the fridge's coils are cleaned or its door seal fixed, so it draws its usual power again |

### A.3 Rules

- A template whose applies\_to includes no appliance in the household is skipped silently (CMP-13 error handling).
- A shift template never moves energy into a peak period; the target set is restricted to off-peak hours even when search would prefer otherwise.
- hvac\_setpoint\_away is bounded by the CMP-14 device bounds before pricing, including the per-action step limit max\_step\_c (TRS-19-02); a delta that would leave the bounds or exceed the step is not evaluated, so every priced setpoint is one the device can apply in one tap (v0.9).
- hvac\_precool installs a weekday schedule on the thermostat on the tap (TRS-SYS-03 as of v0.11, TRS-19-10 to 19-12). It is priced by running the thermostat model of TRS-06-07 over the horizon weather with the schedule against the current setpoint, both clamped to the device bounds; the difference in compressor energy per hour is applied to the forecast.
- Adding a template is a TRS revision (this annex) and a YAML change, nothing else. Removing one is a retirement: the row stays with retired: true so historical ledger rows still resolve.
- Heating-season behaviour of hvac\_setpoint\_away (sign = −1) is defined here but inactive in V1 because the thermostat model is cooling-only (TRS-06-07).

## 9. Revision history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-10-03 | S. Shastry | Initial draft from the MHacks 26 architecture flowchart. Not baselined. |
| 0.2 | 2026-10-03 | S. Shastry | TRS-SYS-03 rewritten to permit tap-only device control; CMP-19 Device Actuator added (simulated thermostat V1, Nest SDM production). CMP-11/13 grouped as the Advisor; CMP-20 Gemini Narrator added with AI class; Voice tab (TRS-16-11). CMP-18 promoted to V1 with weekly success scores feeding CMP-13 ranking (TRS-13-08 to 13-13). HVAC synthesized from weather (TRS-06-07 to 06-09, TRS-09-09). DTE D1.11 recorded as reference tariff. Annex A ATL added. OI-01, OI-02 resolved; OI-08, OI-09 added. Not baselined. |
| 0.2.1 | 2026-10-03 | Claude (for S. Shastry) | Scaffold findings, no requirement change: TRS-00-03 ratio for session 05-21 corrected from 5.33 to the measured 1.18 and the sub-meter coverage cause recorded. Open question raised to S. Shastry: the dataset fridge draws a constant ~58 W and never cycles, so the CMP-06/CMP-12 "fridge duty cycle +40%" example cannot be built from real activations; demo fault provisionally a +40% power fault (mean_on_watts). Not baselined. |
| 0.3 | 2026-10-03 | Claude (for S. Shastry) | Demo fridge fault decided by S. Shastry as a +40% power fault (CMP-06 input, TRS-12-05 example, CMP-12 verification restated); the dataset fridge never cycles. Data store changed from TimescaleDB to SpacetimeDB (Maincloud, TypeScript module) by decision of S. Shastry. TRS-SYS-06 rewritten; CMP-04/05/07/08/15/17 implementing tools restated; TRS-05-04/05, TRS-07-01/02/03/05, TRS-08-02/03/04, TRS-15-06 restated in reducer terms; TRS-07-04 retired. Timestamps stored as microsecond integers. Not baselined. |
| 0.4 | 2026-10-03 | Claude (for S. Shastry) | Decision of S. Shastry: the Voice tab becomes the Actions tab (TRS-16-11 rewritten): ranked plain-language suggestions with a "Take action" button column, buttons only on viable actions; speech synthesis and Alexa removed (OI-09 restated). CMP-20 narrator unchanged as the writer of the sentences. Not baselined. |
| 0.5 | 2026-10-03 | Claude (for S. Shastry) | Decision of S. Shastry: V1 dashboard runs on the CMP-06 ground-truth tracks fed through CMP-05 as source='sim' ("simulated feed" label, 60 s means); CMP-09 becomes baseline-if-time with NILM rows shown alongside. TRS-SYS-02, §4.2, CMP-05 inputs, TRS-08-01, TRS-08-03 (gap = five sample periods, writer declares the period) restated. Not baselined. |
| 0.5.1 | 2026-10-04 | Claude (for S. Shastry) | Step 6 built (CMP-04, CMP-11, CMP-13, Annex A YAML). Clarifications only: replayed-demo weather forecast is perfect foresight (§4.2); saving\_usd is the 7-day horizon figure with the $1/month floor on its monthly equivalent (TRS-13-04); p90 method stated (TRS-11-03). Not baselined. |
| 0.6 | 2026-10-04 | Claude (for S. Shastry) | Decision of S. Shastry: the main tab is a past-and-current summary with no action controls; its fifth panel becomes "biggest impact change" (TRS-16-01, TRS-16-08 rewritten, CMP-16 purpose restated). The Actions tab is the only surface where actions are taken. Not baselined. |
| 0.7 | 2026-10-04 | Claude (for S. Shastry) | Decision of S. Shastry: explicit Dismiss button on the Actions tab (TRS-16-11) and implicit expiry of untaken actions at week end (new TRS-17-06). TRS-13-08 refill rule, TRS-13-10 counting and duration, TRS-17-01, TRS-17-02 restated; CMP-17 verification extended. Not baselined. |
| 0.8 | 2026-10-04 | Claude (for S. Shastry) | Decisions of S. Shastry: third dashboard tab, Savings, for verified savings and past outcomes (new TRS-16-12, TRS-18-04 points to it). Price-plan landing page at sign-up recorded as OI-10, implementation held until the dashboard runs. Not baselined. |
| 0.9 | 2026-10-04 | Claude (for S. Shastry) | Steps 7–9 built. Implementation notes recorded: anomaly baseline skips days already scored anomalous and V1 monitors the fridge only (TRS-12-01/02); verification window clipped to the pricing forecast (TRS-18-01); advice-only actions accept on one tap (TRS-19-08); narrator narrates actions only (TRS-20-06); setpoint search bounded by the step limit (Annex A.3); demo clock and complying simulated household (§4.2). New open issues OI-11 (precool vs TRS-SYS-03), OI-12 (API latency on Maincloud), OI-13 (NILM storage cadence). CMP-09 CO baseline built and scored on held-out sessions. Not baselined. |
| 0.9.1 | 2026-10-04 | Claude (for S. Shastry) | Status notes only, no requirement change: harmonics ablation result (TRS-09-01), narrator fallback retried on the next run (TRS-20-02), OI-03 CO baseline results, OI-09 key confirmed. Flowchart `docs/flowchart.mmd` redrawn to match. Not baselined. |
| 0.10 | 2026-10-04 | Claude (for S. Shastry) | Decision of S. Shastry: OI-13 resolved, NILM output stored at 60 s means. New TRS-09-10 (deployed model co-v2.1: power-only CO, synthetic hvac state, per-day baseload estimate; stored output and its held-out results); §4.2 and CMP-08 error handling restated for 60 s rows; CMP-09 gap rule restated per minute. Not baselined. |
| 0.11 | 2026-10-04 | Claude (for S. Shastry) | Decision of S. Shastry: OI-11 resolved. TRS-SYS-03 and §1.3 reworded so a tap may install a bounded, week-long schedule on the device; new TRS-19-10 to 19-12 (precool schedule, expiry at week end, logging and undo); TRS-19-06/07, TRS-13-01, TRS-13-12 (search over several parameters, so precool adapts to each week), CMP-19 inputs and outputs, §4.2, Annex A (schema, hvac\_precool row, A.3) restated. Priced with the thermostat model, a fixed 2 h × 2 °C precool fell below the floor at a 26 °C setpoint; the search picks the week's best. Not baselined. |
| 0.11.1 | 2026-10-04 | Claude (for S. Shastry) | Wording, at S. Shastry's request: Annex A assumption sentences rewritten to state the concrete change with 12-hour times (placeholders {peak\_range}, {pre\_range}, {to\_hour\_12}); narrator instructions moved to `config/narrator.md` with a fixed shape (change, then monthly saving) (TRS-20-07). No behaviour change. Not baselined. |
| 0.12 | 2026-10-04 | Claude (for S. Shastry) | Decisions of S. Shastry: simple sign-up and log-in (TRS-14-01, OI-07); the splitter estimate leads every per-appliance figure, forecast, priced action and verification, with the simulated feed as an on-request comparison and CMP-12 kept on the simulated feed (TRS-08-01, §4.2); a tapped bill day opens its appliance rundown (TRS-16-02); spike panel titled "Looking ahead" (TRS-16-01); unit symbols everywhere, including narrator statements (TRS-20-05). TRS-16-06 typical draw defined. Not baselined. |
