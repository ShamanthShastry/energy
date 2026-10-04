/**
 * HomeWatt SpacetimeDB schema (TRS-HOMEWATT-001 v0.3). One table per store named in the TRS.
 *
 * Conventions
 * - Timestamps are `*_us`: i64 microseconds since the Unix epoch, UTC. Plain integers keep SQL
 *   filters and JSON reducer arguments unambiguous; the dashboard converts for display.
 * - SpacetimeDB has no composite primary keys, so every table carries an auto-increment `id`
 *   and a multi-column btree index that plays the role of the TRS uniqueness rule. Reducers
 *   check that index before inserting (TRS-07-03, TRS-08-01).
 * - Enums are strings so they can be filtered in SQL: source 'plug'|'nilm', status, severity.
 * - Dashboard-facing tables are public; raw_aggregate and appliance_power are private and read
 *   by server components with the owner token (TRS-05-05, TRS-15-06).
 */
import { schema, table, t } from 'spacetimedb/server';

// ------------------------------------------------------------------ ownership
// Identity of the publisher, captured at init. Write reducers require ctx.sender to equal it.
export const owner = table(
  { name: 'owner' },
  {
    id: t.u8().primaryKey(),
    identity: t.identity(),
  }
);

// ------------------------------------------------------------------ CMP-14 households, appliances
export const household = table(
  { name: 'household', public: true },
  {
    householdId: t.string().primaryKey(),
    zip: t.string(),
    lat: t.f64(),
    lon: t.f64(),
    tariffId: t.string(),
    occupants: t.u8(),
    localTz: t.string(),
    createdAtUs: t.i64(),
  }
);

// TRS-14-04: profile edits are versioned; each save appends a row.
export const householdProfileVersion = table(
  {
    name: 'household_profile_version',
    indexes: [{ accessor: 'byHousehold', algorithm: 'btree', columns: ['householdId', 'version'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    version: t.u32(),
    profileJson: t.string(),
    savedAtUs: t.i64(),
  }
);

// TRS-14-02 closed type list is enforced by the upsert reducer (APPLIANCE_TYPES).
export const appliance = table(
  {
    name: 'appliance',
    public: true,
    indexes: [{ accessor: 'byHouseholdAppliance', algorithm: 'btree', columns: ['householdId', 'applianceId'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    type: t.string(),
    label: t.string(),
    // CMP-19 device bounds (TRS-19-02); 0 when not a device
    minSetpointC: t.f32(),
    maxSetpointC: t.f32(),
    maxStepC: t.f32(),
    createdAtUs: t.i64(),
  }
);

// TRS-14-03: rebinding closes the previous row with unboundAtUs (0 = open), never overwrites.
export const plugBinding = table(
  {
    name: 'plug_binding',
    public: true,
    indexes: [{ accessor: 'byHouseholdPlug', algorithm: 'btree', columns: ['householdId', 'plugId', 'unboundAtUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    plugId: t.string(),
    applianceId: t.string(),
    boundAtUs: t.i64(),
    unboundAtUs: t.i64(),
  }
);

// ------------------------------------------------------------------ CMP-07 raw aggregate store
// TRS-07-02: never updated or deleted by any reducer (no reducer touches it except ingestBatch insert).
// TRS-07-03: (householdId, tsUs) unique via byHouseholdTs check in ingestBatch.
export const rawAggregate = table(
  {
    name: 'raw_aggregate',
    indexes: [{ accessor: 'byHouseholdTs', algorithm: 'btree', columns: ['householdId', 'tsUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    tsUs: t.i64(), // sensor-assigned (TRS-01-03)
    pActiveW: t.f32(),
    irmsA: t.f32(),
    vrmsV: t.f32(),
    powerFactor: t.f32(),
    h1: t.f32(), h2: t.f32(), h3: t.f32(), h4: t.f32(), h5: t.f32(), h6: t.f32(), h7: t.f32(), h8: t.f32(),
    h9: t.f32(), h10: t.f32(), h11: t.f32(), h12: t.f32(), h13: t.f32(), h14: t.f32(), h15: t.f32(), h16: t.f32(),
    h17: t.f32(), h18: t.f32(), h19: t.f32(), h20: t.f32(), h21: t.f32(), h22: t.f32(), h23: t.f32(), h24: t.f32(),
    h25: t.f32(), h26: t.f32(), h27: t.f32(), h28: t.f32(), h29: t.f32(), h30: t.f32(), h31: t.f32(), h32: t.f32(),
    ingestedAt: t.timestamp(), // server time, lag monitoring
  }
);

// CMP-05 gap events (TRS-05-03) and rejection summaries; read by CMP-16 via CMP-07.
export const ingestLog = table(
  {
    name: 'ingest_log',
    public: true,
    indexes: [{ accessor: 'byHouseholdKind', algorithm: 'btree', columns: ['householdId', 'kind', 'gapStartUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    kind: t.string(), // 'gap' | 'rejection_summary' | 'buffer_drop'
    gapStartUs: t.i64(),
    gapEndUs: t.i64(),
    samplesDropped: t.u32(),
    countersJson: t.string(),
    loggedAt: t.timestamp(),
  }
);

// Per-household ingest counters maintained by ingestBatch (reducers cannot return values).
export const ingestStats = table(
  { name: 'ingest_stats', public: true },
  {
    householdId: t.string().primaryKey(),
    accepted: t.u64(),
    duplicates: t.u64(),
    batches: t.u64(),
    lastTsUs: t.i64(),
    updatedAt: t.timestamp(),
  }
);

// ------------------------------------------------------------------ CMP-08 appliance power store
// TRS-08-01 unique (householdId, applianceId, source, modelVersion, tsUs) via byKeyTs.
// TRS-08-02 nilm rows need a non-empty modelVersion (checked in writeAppliancePower).
// TRS-08-03 dtS is the interval the sample covers (<= 10 s); the rollup integrates watts*dtS.
export const appliancePower = table(
  {
    name: 'appliance_power',
    indexes: [
      { accessor: 'byKeyTs', algorithm: 'btree', columns: ['householdId', 'applianceId', 'source', 'modelVersion', 'tsUs'] },
    ],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    tsUs: t.i64(),
    watts: t.f32(),
    source: t.string(), // 'plug' | 'nilm'
    modelVersion: t.string(), // '' for plug rows
    dtS: t.f32(),
    onProb: t.f32(), // -1 when not provided (plug rows)
  }
);

// Hourly rollup, maintained incrementally by writeAppliancePower (TRS-08-03/04).
// kwh = sum(watts * dtS) / 3.6e6; onS = sum(dtS where watts > 10); coveredS = sum(dtS).
export const applianceHourly = table(
  {
    name: 'appliance_hourly',
    public: true,
    indexes: [
      { accessor: 'byKeyBucket', algorithm: 'btree', columns: ['householdId', 'applianceId', 'source', 'modelVersion', 'bucketUs'] },
    ],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    source: t.string(),
    modelVersion: t.string(),
    bucketUs: t.i64(),
    kwh: t.f64(),
    coveredS: t.f64(),
    onS: t.f64(),
    nSamples: t.u32(),
  }
);

export const applianceDaily = table(
  {
    name: 'appliance_daily',
    public: true,
    indexes: [
      { accessor: 'byKeyBucket', algorithm: 'btree', columns: ['householdId', 'applianceId', 'source', 'modelVersion', 'bucketUs'] },
    ],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    source: t.string(),
    modelVersion: t.string(),
    bucketUs: t.i64(),
    kwh: t.f64(),
    coveredS: t.f64(),
    onS: t.f64(),
    nSamples: t.u32(),
  }
);

// ------------------------------------------------------------------ CMP-03 weather
// TRS-03-02: forecast and observed rows both kept; latest fetchedAtUs wins on read.
export const weather = table(
  {
    name: 'weather',
    public: true,
    indexes: [{ accessor: 'byLocationTs', algorithm: 'btree', columns: ['locationId', 'tsUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    locationId: t.string(),
    tsUs: t.i64(),
    tempC: t.f32(),
    humidityPct: t.f32(),
    cloudCoverPct: t.f32(),
    isForecast: t.bool(),
    fetchedAtUs: t.i64(),
  }
);

// ------------------------------------------------------------------ CMP-04 tariff and carbon table
export const tariffPeriod = table(
  {
    name: 'tariff_period',
    public: true,
    indexes: [{ accessor: 'byTariff', algorithm: 'btree', columns: ['tariffId', 'validFrom'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    tariffId: t.string(),
    season: t.string(),
    seasonStart: t.string(), // 'MM-DD' inclusive
    seasonEnd: t.string(),
    periodName: t.string(), // 'peak' | 'off_peak'
    days: t.string(), // comma-joined subset of weekday,weekend,holiday
    startHour: t.u8(),
    endHour: t.u8(), // half-open, local time
    usdPerKwh: t.f64(),
    kgCo2PerKwh: t.f64(),
    validFrom: t.string(), // 'YYYY-MM-DD' (TRS-04-03)
  }
);

// TRS-04-05: stored, excluded from all per-appliance and per-action figures.
export const tariffFixedCharge = table(
  { name: 'tariff_fixed_charge', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    tariffId: t.string(),
    validFrom: t.string(),
    usdPerMonth: t.f64(),
  }
);

// ------------------------------------------------------------------ CMP-11 forecasts
// TRS-11-07: madeAtUs retained; superseded forecasts kept.
export const forecast = table(
  {
    name: 'forecast',
    public: true,
    indexes: [{ accessor: 'byKeyTs', algorithm: 'btree', columns: ['householdId', 'applianceId', 'madeAtUs', 'tsUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    tsUs: t.i64(),
    kwhP50: t.f32(),
    kwhP90: t.f32(),
    modelVersion: t.string(), // 'naive' when < 14 days of history
    madeAtUs: t.i64(),
  }
);

// TRS-09-05 / TRS-11-05 held-out metrics per model version. synthetic=true labels HVAC (TRS-09-09).
export const modelMetric = table(
  {
    name: 'model_metric',
    public: true,
    indexes: [{ accessor: 'byModel', algorithm: 'btree', columns: ['modelVersion', 'component', 'applianceType', 'metric'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    modelVersion: t.string(),
    component: t.string(), // 'cmp09_nilm' | 'cmp11_forecaster'
    applianceType: t.string(),
    metric: t.string(), // 'mae_w' | 'f1_10w' | 'energy_ratio' | 'mae_kwh_h' | ...
    value: t.f64(),
    synthetic: t.bool(),
    evalSessions: t.string(), // comma-joined session ids (TRS-SYS-07 provenance)
    recordedAtUs: t.i64(),
  }
);

// ------------------------------------------------------------------ CMP-12 alerts
export const alert = table(
  {
    name: 'alert',
    public: true,
    indexes: [{ accessor: 'byHouseholdClosed', algorithm: 'btree', columns: ['householdId', 'closedAtUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    tsUs: t.i64(),
    feature: t.string(), // duty_cycle | cycles_per_day | mean_on_watts
    todayValue: t.f64(),
    baselineMedian: t.f64(),
    baselineMad: t.f64(),
    z: t.f64(),
    severity: t.string(), // 'watch' | 'act' (TRS-12-06)
    text: t.string(), // TRS-12-05 plain terms, no cause
    acknowledgedAtUs: t.i64(), // 0 = not acknowledged
    closedAtUs: t.i64(), // 0 = open
  }
);

// ------------------------------------------------------------------ CMP-17 action ledger
// TRS-17-01 never deleted; TRS-17-05 weekId and successScore at ranking time.
export const action = table(
  {
    name: 'action',
    public: true,
    indexes: [{ accessor: 'byHouseholdStatus', algorithm: 'btree', columns: ['householdId', 'status'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    actionId: t.string().unique(), // uuid assigned by CMP-13
    householdId: t.string(),
    applianceId: t.string(),
    actionType: t.string(), // ATL key (Annex A)
    paramsJson: t.string(),
    baselineUsd: t.f64(),
    counterfactualUsd: t.f64(),
    savingUsd: t.f64(),
    savingKgCo2: t.f64(),
    assumptionText: t.string(),
    forecastMadeAtUs: t.i64(), // TRS-18-03
    weekId: t.string(), // ISO week, e.g. 2026-W28
    successScore: t.f32(), // -1 = null (cold start, TRS-13-13)
    status: t.string(), // proposed | accepted | dismissed | verified | not_verified
    statusAtUs: t.i64(),
    statusReason: t.string(),
    verifiedSavingUsd: t.f64(), // NaN until CMP-18 verifies
    createdAtUs: t.i64(),
  }
);

// TRS-17-04: every transition logged with actor and timestamp.
export const actionTransition = table(
  {
    name: 'action_transition',
    public: true,
    indexes: [{ accessor: 'byAction', algorithm: 'btree', columns: ['actionId', 'atUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    actionId: t.string(),
    fromStatus: t.string(),
    toStatus: t.string(),
    actor: t.string(), // 'cmp13' | 'user' | 'cmp18' | 'undo'
    reason: t.string(),
    atUs: t.i64(),
  }
);

// TRS-13-10 suppression of an action type dismissed 3 consecutive weeks.
export const actionSuppression = table(
  {
    name: 'action_suppression',
    public: true,
    indexes: [{ accessor: 'byHouseholdType', algorithm: 'btree', columns: ['householdId', 'actionType'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    actionType: t.string(),
    fromWeekId: t.string(),
    untilWeekId: t.string(),
    reason: t.string(),
  }
);

// ------------------------------------------------------------------ CMP-18 outcome scores
export const outcomeScore = table(
  {
    name: 'outcome_score',
    public: true,
    indexes: [{ accessor: 'byHouseholdTypeWeek', algorithm: 'btree', columns: ['householdId', 'actionType', 'weekId'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    actionType: t.string(),
    weekId: t.string(),
    proposed: t.u32(),
    accepted: t.u32(),
    verified: t.u32(),
    successScore: t.f32(), // -1 = null when proposed < 2
    computedAtUs: t.i64(),
  }
);

// ------------------------------------------------------------------ CMP-19 actuator
export const thermostatState = table(
  {
    name: 'thermostat_state',
    public: true,
    indexes: [{ accessor: 'byHouseholdAppliance', algorithm: 'btree', columns: ['householdId', 'applianceId'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    currentSetpointC: t.f32(),
    mode: t.string(),
    readAtUs: t.i64(),
    simulated: t.bool(), // TRS-19-09
  }
);

// TRS-19-03: log row written before the command, updated after.
export const actuation = table(
  {
    name: 'actuation',
    public: true,
    indexes: [{ accessor: 'byHouseholdTs', algorithm: 'btree', columns: ['householdId', 'tsUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    actuationId: t.string().unique(),
    actionId: t.string(),
    householdId: t.string(),
    applianceId: t.string(),
    previousC: t.f32(),
    requestedC: t.f32(),
    appliedC: t.f32(),
    result: t.string(), // pending | applied | failed | refused
    error: t.string(),
    actor: t.string(), // 'user' | 'undo'
    tsUs: t.i64(),
    undoExpiresAtUs: t.i64(), // TRS-19-04: ts + 24 h
  }
);

// v0.11 TRS-19-10..12: a schedule installed on the device by a user tap (precool). The row is the
// log: written 'pending' before the command, then 'installed' or 'failed'; removal goes
// 'removing' -> 'removed'. It ends by itself at validUntilUs (end of the action's week).
export const thermostatSchedule = table(
  {
    name: 'thermostat_schedule',
    public: true,
    indexes: [{ accessor: 'byHouseholdAppliance', algorithm: 'btree', columns: ['householdId', 'applianceId'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    scheduleId: t.string().unique(),
    actionId: t.string(),
    householdId: t.string(),
    applianceId: t.string(),
    kind: t.string(), // 'precool'
    weekdaysOnly: t.bool(),
    preStartHour: t.u8(),
    peakStartHour: t.u8(),
    peakEndHour: t.u8(),
    preCoolC: t.f32(),
    peakWarmC: t.f32(),
    minC: t.f32(),
    maxC: t.f32(),
    maxStepC: t.f32(),
    validFromUs: t.i64(),
    validUntilUs: t.i64(),
    status: t.string(), // pending | installed | failed | removing | removed
    error: t.string(),
    removedBy: t.string(), // '' | 'undo'
    removedAtUs: t.i64(),
    undoExpiresAtUs: t.i64(), // TRS-19-04: install time + 24 h
    tsUs: t.i64(),
  }
);

// ------------------------------------------------------------------ CMP-20 narrator statements
// TRS-20-08: retained; superseded marked, never deleted.
export const statement = table(
  {
    name: 'statement',
    public: true,
    indexes: [{ accessor: 'byHouseholdCreated', algorithm: 'btree', columns: ['householdId', 'createdAtUs'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    statementId: t.string().unique(),
    householdId: t.string(),
    actionId: t.string(), // '' when the statement narrates a spike
    spikeRefJson: t.string(),
    text: t.string(),
    modelVersion: t.string(),
    unnarrated: t.bool(), // fallback to assumptionText (CMP-20 error handling)
    supersededAtUs: t.i64(), // 0 = current
    createdAtUs: t.i64(),
    inputSha: t.string().default(''), // digest of the structured input; a changed input re-narrates
  }
);

// ------------------------------------------------------------------ demo clock (§4.2)
// The replayed demo runs on the timeline's own clock. When a row exists for a household, every
// ledger, alert and actuation timestamp for it uses this time instead of the wall clock.
export const simClock = table(
  { name: 'sim_clock', public: true },
  {
    householdId: t.string().primaryKey(),
    nowUs: t.i64(),
  }
);

// ------------------------------------------------------------------ CMP-12 daily features
export const applianceDayFeature = table(
  {
    name: 'appliance_day_feature',
    public: true,
    indexes: [{ accessor: 'byHouseholdApplianceDay', algorithm: 'btree', columns: ['householdId', 'applianceId', 'day'] }],
  },
  {
    id: t.u64().primaryKey().autoInc(),
    householdId: t.string(),
    applianceId: t.string(),
    day: t.string(), // local date 'YYYY-MM-DD'
    source: t.string(),
    dutyCycle: t.f64(),
    cyclesPerDay: t.f64(),
    meanOnWatts: t.f64(),
    coveredS: t.f64(),
    zDutyCycle: t.f64(), // NaN when insufficient history (TRS-12-04)
    zMeanOnWatts: t.f64(),
    zCyclesPerDay: t.f64(),
    baselineDays: t.u32(),
  }
);

const spacetimedb = schema({
  owner,
  household,
  householdProfileVersion,
  appliance,
  plugBinding,
  rawAggregate,
  ingestLog,
  ingestStats,
  appliancePower,
  applianceHourly,
  applianceDaily,
  weather,
  tariffPeriod,
  tariffFixedCharge,
  forecast,
  modelMetric,
  alert,
  action,
  actionTransition,
  actionSuppression,
  outcomeScore,
  thermostatState,
  actuation,
  thermostatSchedule,
  statement,
  simClock,
  applianceDayFeature,
});

export default spacetimedb;
