/**
 * HomeWatt SpacetimeDB module: reducers for build-order steps 1-4.
 *
 * TRS-05-05: ingestBatch is the ONLY reducer that inserts into raw_aggregate, and only the
 * database owner (the Python ingestion service, authenticated with the owner token) may call
 * any write reducer. TRS-07-02: no reducer updates or deletes raw_aggregate rows.
 */
import { SenderError, t, type InferSchema, type ReducerCtx } from 'spacetimedb/server';
import spacetimedb from './schema';

export { default } from './schema';

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;

// ------------------------------------------------------------------ constants (shared with Python)
// TRS-05-03 gap threshold for the 2 s sensor is GAP_PERIODS * 2 s = 10 s.
const GAP_PERIODS = 5; // TRS-08-03: a gap is more than five sample periods of the stream
const SOURCES = new Set(['plug', 'nilm', 'sim']); // TRS-SYS-02 (v0.5)
const ON_THRESHOLD_W = 10.0;
const HOUR_US = 3_600_000_000n;
const DAY_US = 86_400_000_000n;
// TRS-14-02 closed list
const APPLIANCE_TYPES = new Set([
  'fridge', 'water_heater', 'hair_dryer', 'iron', 'laptop', 'screen', 'lamp',
  'straightener', 'hvac', 'dryer', 'oven', 'ev', 'other',
]);

// ------------------------------------------------------------------ helpers
function requireOwner(ctx: Ctx): void {
  const o = ctx.db.owner.id.find(0);
  if (!o || !o.identity.equals(ctx.sender)) {
    throw new SenderError('only the database owner may call write reducers');
  }
}

function nowUs(ctx: Ctx): bigint {
  return ctx.timestamp.microsSinceUnixEpoch;
}

/** Demo-aware time for a household: the replay clock when set (§4.2), else the wall clock. */
function nowFor(ctx: Ctx, householdId: string): bigint {
  const c = ctx.db.simClock.householdId.find(householdId);
  return c ? c.nowUs : nowUs(ctx);
}

/** Add a sample's contribution to the hourly and daily rollups (TRS-08-03). */
function addToRollups(
  ctx: Ctx,
  householdId: string,
  applianceId: string,
  source: string,
  modelVersion: string,
  tsUs: bigint,
  watts: number,
  dtS: number
): void {
  const wh = (watts * dtS) / 3600.0;
  const onS = watts > ON_THRESHOLD_W ? dtS : 0;
  const hourBucket = tsUs - (tsUs % HOUR_US);
  const dayBucket = tsUs - (tsUs % DAY_US);

  const h = [...ctx.db.applianceHourly.byKeyBucket.filter([householdId, applianceId, source, modelVersion, hourBucket])][0];
  if (h) {
    ctx.db.applianceHourly.id.update({
      ...h,
      kwh: h.kwh + wh / 1000.0,
      coveredS: h.coveredS + dtS,
      onS: h.onS + onS,
      nSamples: h.nSamples + 1,
    });
  } else {
    ctx.db.applianceHourly.insert({
      id: 0n, householdId, applianceId, source, modelVersion, bucketUs: hourBucket,
      kwh: wh / 1000.0, coveredS: dtS, onS, nSamples: 1,
    });
  }

  const d = [...ctx.db.applianceDaily.byKeyBucket.filter([householdId, applianceId, source, modelVersion, dayBucket])][0];
  if (d) {
    ctx.db.applianceDaily.id.update({
      ...d,
      kwh: d.kwh + wh / 1000.0,
      coveredS: d.coveredS + dtS,
      onS: d.onS + onS,
      nSamples: d.nSamples + 1,
    });
  } else {
    ctx.db.applianceDaily.insert({
      id: 0n, householdId, applianceId, source, modelVersion, bucketUs: dayBucket,
      kwh: wh / 1000.0, coveredS: dtS, onS, nSamples: 1,
    });
  }
}

// ------------------------------------------------------------------ lifecycle
export const init = spacetimedb.init(ctx => {
  // The publisher becomes the owner. Re-publishing keeps the first owner.
  if (!ctx.db.owner.id.find(0)) {
    ctx.db.owner.insert({ id: 0, identity: ctx.sender });
  }
});

// ------------------------------------------------------------------ argument types
const AggregateSample = t.object('AggregateSample', {
  householdId: t.string(),
  tsUs: t.i64(),
  // 36 numeric fields in NUMERIC_FIELDS order: p_active_w, irms_a, vrms_v, power_factor, h1..h32
  v: t.array(t.f32()),
});

const AppliancePowerRow = t.object('AppliancePowerRow', {
  householdId: t.string(),
  applianceId: t.string(),
  tsUs: t.i64(),
  watts: t.f32(),
  onProb: t.f32(), // -1 when absent
});

// ------------------------------------------------------------------ CMP-05 / CMP-07 ingestion
/**
 * The single write path for aggregate samples (TRS-05-05). Validation (bounds, monotonicity,
 * gaps) happens in the Python ingestion service before the call; this reducer enforces the
 * store rules: 36 fields present, (householdId, tsUs) unique with duplicates counted
 * (TRS-07-03), append only.
 */
export const ingestBatch = spacetimedb.reducer(
  { samples: t.array(AggregateSample) },
  (ctx, { samples }) => {
    requireOwner(ctx);
    const perHousehold = new Map<string, { accepted: number; duplicates: number; lastTs: bigint }>();
    for (const s of samples) {
      if (s.v.length !== 36) {
        throw new SenderError(`sample ${s.householdId}@${s.tsUs} has ${s.v.length} fields, expected 36`);
      }
      const stat = perHousehold.get(s.householdId) ?? { accepted: 0, duplicates: 0, lastTs: 0n };
      const dup = [...ctx.db.rawAggregate.byHouseholdTs.filter([s.householdId, s.tsUs])].length > 0;
      if (dup) {
        stat.duplicates += 1;
      } else {
        const v = s.v;
        ctx.db.rawAggregate.insert({
          id: 0n,
          householdId: s.householdId,
          tsUs: s.tsUs,
          pActiveW: v[0], irmsA: v[1], vrmsV: v[2], powerFactor: v[3],
          h1: v[4], h2: v[5], h3: v[6], h4: v[7], h5: v[8], h6: v[9], h7: v[10], h8: v[11],
          h9: v[12], h10: v[13], h11: v[14], h12: v[15], h13: v[16], h14: v[17], h15: v[18], h16: v[19],
          h17: v[20], h18: v[21], h19: v[22], h20: v[23], h21: v[24], h22: v[25], h23: v[26], h24: v[27],
          h25: v[28], h26: v[29], h27: v[30], h28: v[31], h29: v[32], h30: v[33], h31: v[34], h32: v[35],
          ingestedAt: ctx.timestamp,
        });
        stat.accepted += 1;
        if (s.tsUs > stat.lastTs) stat.lastTs = s.tsUs;
      }
      perHousehold.set(s.householdId, stat);
    }
    for (const [householdId, stat] of perHousehold) {
      const existing = ctx.db.ingestStats.householdId.find(householdId);
      if (existing) {
        ctx.db.ingestStats.householdId.update({
          ...existing,
          accepted: existing.accepted + BigInt(stat.accepted),
          duplicates: existing.duplicates + BigInt(stat.duplicates),
          batches: existing.batches + 1n,
          lastTsUs: stat.lastTs > existing.lastTsUs ? stat.lastTs : existing.lastTsUs,
          updatedAt: ctx.timestamp,
        });
      } else {
        ctx.db.ingestStats.insert({
          householdId,
          accepted: BigInt(stat.accepted),
          duplicates: BigInt(stat.duplicates),
          batches: 1n,
          lastTsUs: stat.lastTs,
          updatedAt: ctx.timestamp,
        });
      }
    }
  }
);

/** TRS-05-03 gap event. */
export const logGap = spacetimedb.reducer(
  { householdId: t.string(), gapStartUs: t.i64(), gapEndUs: t.i64(), samplesDropped: t.u32() },
  (ctx, { householdId, gapStartUs, gapEndUs, samplesDropped }) => {
    requireOwner(ctx);
    ctx.db.ingestLog.insert({
      id: 0n, householdId, kind: 'gap', gapStartUs, gapEndUs, samplesDropped,
      countersJson: '', loggedAt: ctx.timestamp,
    });
  }
);

/** Rejection counters by reason, written when the ingestion service closes. */
export const logCounters = spacetimedb.reducer(
  { householdId: t.string(), kind: t.string(), countersJson: t.string() },
  (ctx, { householdId, kind, countersJson }) => {
    requireOwner(ctx);
    ctx.db.ingestLog.insert({
      id: 0n, householdId, kind, gapStartUs: 0n, gapEndUs: 0n, samplesDropped: 0,
      countersJson, loggedAt: ctx.timestamp,
    });
  }
);

// ------------------------------------------------------------------ CMP-08 appliance power
/**
 * Writes plug (CMP-05), sim (CMP-06 ground truth, demo) or NILM (CMP-09) rows and maintains
 * the hourly/daily rollups. periodS is the stream's sample period (2 for the sensor, 60 for the
 * simulated feed). dtS = interval since the previous row of the same key when <= 5 periods,
 * else one period, so a gap contributes no energy (TRS-08-03). TRS-08-01 duplicates are
 * skipped; TRS-08-02 nilm and sim rows require modelVersion; TRS-08-06 a new modelVersion adds
 * rows under its own key.
 */
export const writeAppliancePower = spacetimedb.reducer(
  { rows: t.array(AppliancePowerRow), source: t.string(), modelVersion: t.string(), periodS: t.f32() },
  (ctx, { rows, source, modelVersion, periodS }) => {
    requireOwner(ctx);
    if (!SOURCES.has(source)) throw new SenderError(`bad source '${source}'`);
    if (source !== 'plug' && modelVersion === '') throw new SenderError('TRS-08-02: nilm and sim rows require modelVersion');
    if (source === 'plug' && modelVersion !== '') throw new SenderError('plug rows carry no modelVersion');
    if (!(periodS > 0 && periodS <= 3600)) throw new SenderError('periodS must be in (0, 3600]');
    if (rows.length === 0) return;

    // Rows must be in time order per key; track the previous timestamp per key within the batch
    // and look up the store for the first row of each key.
    const prevTs = new Map<string, bigint>();
    for (const r of rows) {
      if (r.watts < 0) throw new SenderError('watts must be >= 0');
      const key = `${r.householdId}\u0000${r.applianceId}`;
      let prev = prevTs.get(key);
      if (prev === undefined) {
        // last stored row for this key: scan the key's range and keep the max (btree order)
        let last = -1n;
        for (const e of ctx.db.appliancePower.byKeyTs.filter([r.householdId, r.applianceId, source, modelVersion])) {
          if (e.tsUs > last) last = e.tsUs;
        }
        prev = last;
      }
      if (prev >= r.tsUs) {
        // A row at or before the last stored one is a duplicate if that exact key exists (a
        // replayed day sent twice): skip it (TRS-08-01). Anything else is out of order.
        const exists = [...ctx.db.appliancePower.byKeyTs.filter([r.householdId, r.applianceId, source, modelVersion, r.tsUs])].length > 0;
        if (exists) continue;
        throw new SenderError(`out-of-order row for ${r.applianceId} at ${r.tsUs}`);
      }
      const deltaS = prev < 0n ? periodS : Number(r.tsUs - prev) / 1e6;
      const dtS = deltaS > 0 && deltaS <= GAP_PERIODS * periodS ? deltaS : periodS;
      ctx.db.appliancePower.insert({
        id: 0n,
        householdId: r.householdId,
        applianceId: r.applianceId,
        tsUs: r.tsUs,
        watts: r.watts,
        source,
        modelVersion,
        dtS,
        onProb: r.onProb,
      });
      addToRollups(ctx, r.householdId, r.applianceId, source, modelVersion, r.tsUs, r.watts, dtS);
      prevTs.set(key, r.tsUs);
    }
  }
);

// ------------------------------------------------------------------ CMP-14 (minimal, for seeding)
export const upsertHousehold = spacetimedb.reducer(
  {
    householdId: t.string(), zip: t.string(), lat: t.f64(), lon: t.f64(),
    tariffId: t.string(), occupants: t.u8(), localTz: t.string(),
  },
  (ctx, a) => {
    requireOwner(ctx);
    const existing = ctx.db.household.householdId.find(a.householdId);
    if (existing) {
      ctx.db.household.householdId.update({ ...existing, ...a });
    } else {
      ctx.db.household.insert({ ...a, createdAtUs: nowUs(ctx) });
    }
  }
);

export const upsertAppliance = spacetimedb.reducer(
  {
    householdId: t.string(), applianceId: t.string(), type: t.string(), label: t.string(),
    minSetpointC: t.f32(), maxSetpointC: t.f32(), maxStepC: t.f32(),
  },
  (ctx, a) => {
    requireOwner(ctx);
    if (!APPLIANCE_TYPES.has(a.type)) throw new SenderError(`TRS-14-02: unknown appliance type '${a.type}'`);
    const existing = [...ctx.db.appliance.byHouseholdAppliance.filter([a.householdId, a.applianceId])][0];
    if (existing) {
      ctx.db.appliance.id.update({ ...existing, ...a });
    } else {
      ctx.db.appliance.insert({ id: 0n, ...a, createdAtUs: nowUs(ctx) });
    }
  }
);

// ------------------------------------------------------------------ CMP-04 tariff (TRS-04-04 exposure)
const TariffPeriodRow = t.object('TariffPeriodRow', {
  tariffId: t.string(), season: t.string(), seasonStart: t.string(), seasonEnd: t.string(),
  periodName: t.string(), days: t.string(), startHour: t.u8(), endHour: t.u8(),
  usdPerKwh: t.f64(), kgCo2PerKwh: t.f64(), validFrom: t.string(),
});

/** Replace all rows of (tariffId, validFrom); coverage was validated by the Python loader. */
export const upsertTariff = spacetimedb.reducer(
  { rows: t.array(TariffPeriodRow), tariffId: t.string(), validFrom: t.string(), fixedUsdPerMonth: t.f64() },
  (ctx, { rows, tariffId, validFrom, fixedUsdPerMonth }) => {
    requireOwner(ctx);
    for (const r of [...ctx.db.tariffPeriod.byTariff.filter([tariffId, validFrom])]) ctx.db.tariffPeriod.id.delete(r.id);
    for (const r of rows) ctx.db.tariffPeriod.insert({ id: 0n, ...r });
    for (const f of [...ctx.db.tariffFixedCharge.iter()]) {
      if (f.tariffId === tariffId && f.validFrom === validFrom) ctx.db.tariffFixedCharge.id.delete(f.id);
    }
    ctx.db.tariffFixedCharge.insert({ id: 0n, tariffId, validFrom, usdPerMonth: fixedUsdPerMonth });
  }
);

// ------------------------------------------------------------------ CMP-03 weather
const WeatherRow = t.object('WeatherRow', {
  tsUs: t.i64(), tempC: t.f32(), humidityPct: t.f32(), cloudCoverPct: t.f32(),
});

/** TRS-03-02: observed and forecast rows both kept; a fetch adds rows under its fetchedAtUs. */
export const writeWeather = spacetimedb.reducer(
  { rows: t.array(WeatherRow), locationId: t.string(), isForecast: t.bool(), fetchedAtUs: t.i64() },
  (ctx, { rows, locationId, isForecast, fetchedAtUs }) => {
    requireOwner(ctx);
    for (const r of rows) {
      const same = [...ctx.db.weather.byLocationTs.filter([locationId, r.tsUs])].find(
        w => w.isForecast === isForecast && w.fetchedAtUs === fetchedAtUs
      );
      if (same) continue;
      ctx.db.weather.insert({ id: 0n, locationId, isForecast, fetchedAtUs, ...r });
    }
  }
);

// ------------------------------------------------------------------ CMP-11 forecasts
const ForecastRow = t.object('ForecastRow', {
  householdId: t.string(), applianceId: t.string(), tsUs: t.i64(),
  kwhP50: t.f32(), kwhP90: t.f32(), modelVersion: t.string(),
});

/** TRS-11-07: every row carries madeAtUs; superseded forecasts are retained. */
export const writeForecasts = spacetimedb.reducer(
  { rows: t.array(ForecastRow), madeAtUs: t.i64() },
  (ctx, { rows, madeAtUs }) => {
    requireOwner(ctx);
    for (const r of rows) {
      if (r.kwhP50 < 0 || r.kwhP90 < r.kwhP50) throw new SenderError('TRS-11-03: need 0 <= p50 <= p90');
      const dup = [...ctx.db.forecast.byKeyTs.filter([r.householdId, r.applianceId, madeAtUs, r.tsUs])].length > 0;
      if (dup) continue;
      ctx.db.forecast.insert({ id: 0n, madeAtUs, ...r });
    }
  }
);

const ModelMetricRow = t.object('ModelMetricRow', {
  modelVersion: t.string(), component: t.string(), applianceType: t.string(), metric: t.string(),
  value: t.f64(), synthetic: t.bool(), evalSessions: t.string(),
});

/** TRS-09-05 / TRS-11-05: held-out metrics per model version; latest row per key wins on read. */
export const writeModelMetrics = spacetimedb.reducer(
  { rows: t.array(ModelMetricRow) },
  (ctx, { rows }) => {
    requireOwner(ctx);
    for (const r of rows) {
      for (const old of [...ctx.db.modelMetric.byModel.filter([r.modelVersion, r.component, r.applianceType, r.metric])]) {
        ctx.db.modelMetric.id.delete(old.id);
      }
      ctx.db.modelMetric.insert({ id: 0n, ...r, recordedAtUs: nowUs(ctx) });
    }
  }
);

// ------------------------------------------------------------------ CMP-13 -> CMP-17 proposals
const MAX_ACTIONS = 3; // TRS-13-06, TRS-17-03

const ProposedAction = t.object('ProposedAction', {
  actionId: t.string(), householdId: t.string(), applianceId: t.string(), actionType: t.string(),
  paramsJson: t.string(), baselineUsd: t.f64(), counterfactualUsd: t.f64(), savingUsd: t.f64(),
  savingKgCo2: t.f64(), assumptionText: t.string(), forecastMadeAtUs: t.i64(), weekId: t.string(),
  successScore: t.f32(),
  surfaced: t.bool(), // above the TRS-13-04 floor; only surfaced candidates may fill a slot
});

function logTransition(ctx: Ctx, actionId: string, from: string, to: string, actor: string, reason: string, atUs: bigint): void {
  ctx.db.actionTransition.insert({ id: 0n, actionId, fromStatus: from, toStatus: to, actor, reason, atUs });
}

/**
 * TRS-17-06: every action still proposed when its week ends becomes dismissed with
 * reason 'expired', actor 'week_close'. Idempotent: closed rows are no longer proposed.
 */
function closeOpenProposals(ctx: Ctx, householdId: string, weekEnded: (weekId: string) => boolean): number {
  const now = nowFor(ctx, householdId);
  let n = 0;
  for (const a of [...ctx.db.action.byHouseholdStatus.filter([householdId, 'proposed'])]) {
    if (!weekEnded(a.weekId)) continue;
    ctx.db.action.id.update({ ...a, status: 'dismissed', statusAtUs: now, statusReason: 'expired' });
    logTransition(ctx, a.actionId, 'proposed', 'dismissed', 'week_close', 'expired', now);
    n += 1;
  }
  return n;
}

/**
 * CMP-13 issues the week's batch (TRS-13-08, TRS-17-02). `rows` are all priced candidates in
 * rank order. Behaviour:
 *  - proposals left from earlier weeks are closed first (TRS-17-06), so none outlives its week;
 *  - an action already issued this week keeps its slot: re-priced in place while proposed,
 *    untouched once accepted or dismissed, and never re-issued after a dismissal;
 *  - free slots (3 minus this week's non-dismissed actions) are filled by surfaced candidates
 *    in the order given. A dismissal therefore frees a slot for the next refresh.
 */
export const proposeActions = spacetimedb.reducer(
  { rows: t.array(ProposedAction), householdId: t.string(), weekId: t.string() },
  (ctx, { rows, householdId, weekId }) => {
    requireOwner(ctx);
    closeOpenProposals(ctx, householdId, w => w < weekId);
    const now = nowFor(ctx, householdId);
    const issued = [...ctx.db.action.byHouseholdStatus.filter(householdId)].filter(a => a.weekId === weekId);
    let members = issued.filter(a => a.status !== 'dismissed').length;
    for (const r of rows) {
      if (r.householdId !== householdId || r.weekId !== weekId) throw new SenderError('row does not match household/week');
      const same = issued.find(a => a.applianceId === r.applianceId && a.actionType === r.actionType);
      if (same) {
        if (same.status === 'proposed') {
          ctx.db.action.id.update({
            ...same, paramsJson: r.paramsJson, baselineUsd: r.baselineUsd, counterfactualUsd: r.counterfactualUsd,
            savingUsd: r.savingUsd, savingKgCo2: r.savingKgCo2, assumptionText: r.assumptionText,
            forecastMadeAtUs: r.forecastMadeAtUs, successScore: r.successScore,
          });
        }
        continue;
      }
      if (!r.surfaced || members >= MAX_ACTIONS) continue;
      const { surfaced: _s, ...fields } = r;
      ctx.db.action.insert({
        id: 0n, ...fields, status: 'proposed', statusAtUs: now, statusReason: '', verifiedSavingUsd: NaN, createdAtUs: now,
      });
      logTransition(ctx, r.actionId, '', 'proposed', 'cmp13', `week ${weekId}`, now);
      members += 1;
    }
  }
);

/** TRS-17-06 week-end close, run by the weekly job for every week that has ended. */
export const closeWeek = spacetimedb.reducer(
  { householdId: t.string(), throughWeekId: t.string() },
  (ctx, { householdId, throughWeekId }) => {
    requireOwner(ctx);
    closeOpenProposals(ctx, householdId, w => w <= throughWeekId);
  }
);

function userTransition(ctx: Ctx, actionId: string, to: 'accepted' | 'dismissed', reason: string): void {
  const a = ctx.db.action.actionId.find(actionId);
  if (!a) throw new SenderError(`no action ${actionId}`);
  if (a.status !== 'proposed') throw new SenderError(`action ${actionId} is ${a.status}; only a proposed action can be ${to}`);
  const now = nowFor(ctx, a.householdId);
  ctx.db.action.id.update({ ...a, status: to, statusAtUs: now, statusReason: reason });
  logTransition(ctx, actionId, 'proposed', to, 'user', reason, now);
}

/** Dismiss button on the Actions tab (TRS-16-11), via CMP-15 (TRS-17-02). */
export const dismissAction = spacetimedb.reducer(
  { actionId: t.string() },
  (ctx, { actionId }) => {
    requireOwner(ctx);
    userTransition(ctx, actionId, 'dismissed', 'user');
  }
);

/** Ledger half of Take action (TRS-16-11, TRS-17-02). The CMP-19 actuator flow is built later. */
export const acceptAction = spacetimedb.reducer(
  { actionId: t.string() },
  (ctx, { actionId }) => {
    requireOwner(ctx);
    userTransition(ctx, actionId, 'accepted', '');
  }
);

export const recordSuppression = spacetimedb.reducer(
  { householdId: t.string(), actionType: t.string(), fromWeekId: t.string(), untilWeekId: t.string(), reason: t.string() },
  (ctx, a) => {
    requireOwner(ctx);
    const existing = [...ctx.db.actionSuppression.byHouseholdType.filter([a.householdId, a.actionType])].find(s => s.fromWeekId === a.fromWeekId);
    if (!existing) ctx.db.actionSuppression.insert({ id: 0n, ...a });
  }
);

// ------------------------------------------------------------------ CMP-19 state seed (onboarding)
export const initThermostatState = spacetimedb.reducer(
  { householdId: t.string(), applianceId: t.string(), setpointC: t.f32(), simulated: t.bool() },
  (ctx, { householdId, applianceId, setpointC, simulated }) => {
    requireOwner(ctx);
    const existing = [...ctx.db.thermostatState.byHouseholdAppliance.filter([householdId, applianceId])][0];
    if (existing) {
      ctx.db.thermostatState.id.update({ ...existing, currentSetpointC: setpointC, readAtUs: nowUs(ctx), simulated });
    } else {
      ctx.db.thermostatState.insert({ id: 0n, householdId, applianceId, currentSetpointC: setpointC, mode: 'cool', readAtUs: nowUs(ctx), simulated });
    }
  }
);

// ------------------------------------------------------------------ demo clock
export const setSimClock = spacetimedb.reducer(
  { householdId: t.string(), nowUs: t.i64() },
  (ctx, { householdId, nowUs: at }) => {
    requireOwner(ctx);
    const c = ctx.db.simClock.householdId.find(householdId);
    if (c) ctx.db.simClock.householdId.update({ householdId, nowUs: at });
    else ctx.db.simClock.insert({ householdId, nowUs: at });
  }
);

// ------------------------------------------------------------------ CMP-12 anomaly detector
const DayFeatureRow = t.object('DayFeatureRow', {
  householdId: t.string(), applianceId: t.string(), day: t.string(), source: t.string(),
  dutyCycle: t.f64(), cyclesPerDay: t.f64(), meanOnWatts: t.f64(), coveredS: t.f64(),
  zDutyCycle: t.f64(), zMeanOnWatts: t.f64(), zCyclesPerDay: t.f64(), baselineDays: t.u32(),
});

/** Derived daily features; a recomputation of the same day replaces its row. */
export const writeDayFeatures = spacetimedb.reducer(
  { rows: t.array(DayFeatureRow) },
  (ctx, { rows }) => {
    requireOwner(ctx);
    for (const r of rows) {
      for (const old of [...ctx.db.applianceDayFeature.byHouseholdApplianceDay.filter([r.householdId, r.applianceId, r.day])]) {
        ctx.db.applianceDayFeature.id.delete(old.id);
      }
      ctx.db.applianceDayFeature.insert({ id: 0n, ...r });
    }
  }
);

/** TRS-12-03/05/06: one open alert per (appliance, feature); a later day updates it. */
export const upsertAlert = spacetimedb.reducer(
  {
    householdId: t.string(), applianceId: t.string(), feature: t.string(), tsUs: t.i64(),
    todayValue: t.f64(), baselineMedian: t.f64(), baselineMad: t.f64(), z: t.f64(), severity: t.string(), text: t.string(),
  },
  (ctx, a) => {
    requireOwner(ctx);
    if (a.severity !== 'watch' && a.severity !== 'act') throw new SenderError('severity must be watch or act');
    const open = [...ctx.db.alert.byHouseholdClosed.filter([a.householdId, 0n])].find(
      x => x.applianceId === a.applianceId && x.feature === a.feature
    );
    if (open) ctx.db.alert.id.update({ ...open, ...a });
    else ctx.db.alert.insert({ id: 0n, ...a, acknowledgedAtUs: 0n, closedAtUs: 0n });
  }
);

export const closeAlert = spacetimedb.reducer(
  { alertId: t.u64() },
  (ctx, { alertId }) => {
    requireOwner(ctx);
    const a = ctx.db.alert.id.find(alertId);
    if (!a || a.closedAtUs !== 0n) return;
    ctx.db.alert.id.update({ ...a, closedAtUs: nowFor(ctx, a.householdId) });
  }
);

export const acknowledgeAlert = spacetimedb.reducer(
  { alertId: t.u64() },
  (ctx, { alertId }) => {
    requireOwner(ctx);
    const a = ctx.db.alert.id.find(alertId);
    if (!a) throw new SenderError(`no alert ${alertId}`);
    if (a.acknowledgedAtUs === 0n) ctx.db.alert.id.update({ ...a, acknowledgedAtUs: nowFor(ctx, a.householdId) });
  }
);

// ------------------------------------------------------------------ CMP-18 verifier
/** TRS-17-02: only CMP-18 moves accepted -> verified / not_verified. */
export const verifyAction = spacetimedb.reducer(
  { actionId: t.string(), verifiedSavingUsd: t.f64(), status: t.string() },
  (ctx, { actionId, verifiedSavingUsd, status }) => {
    requireOwner(ctx);
    if (status !== 'verified' && status !== 'not_verified') throw new SenderError('status must be verified or not_verified');
    const a = ctx.db.action.actionId.find(actionId);
    if (!a) throw new SenderError(`no action ${actionId}`);
    if (a.status !== 'accepted') throw new SenderError(`action ${actionId} is ${a.status}; only accepted actions are verified`);
    const now = nowFor(ctx, a.householdId);
    ctx.db.action.id.update({ ...a, status, statusAtUs: now, statusReason: '', verifiedSavingUsd });
    logTransition(ctx, actionId, 'accepted', status, 'cmp18', `verified saving ${verifiedSavingUsd.toFixed(2)}`, now);
  }
);

const OutcomeScoreRow = t.object('OutcomeScoreRow', {
  actionType: t.string(), proposed: t.u32(), accepted: t.u32(), verified: t.u32(), successScore: t.f32(),
});

/** TRS-18-05/07: recomputed from the ledger each week; a recompute of the same week replaces it. */
export const writeOutcomeScores = spacetimedb.reducer(
  { householdId: t.string(), weekId: t.string(), rows: t.array(OutcomeScoreRow) },
  (ctx, { householdId, weekId, rows }) => {
    requireOwner(ctx);
    const now = nowFor(ctx, householdId);
    for (const old of [...ctx.db.outcomeScore.iter()]) {
      if (old.householdId === householdId && old.weekId === weekId) ctx.db.outcomeScore.id.delete(old.id);
    }
    for (const r of rows) ctx.db.outcomeScore.insert({ id: 0n, householdId, weekId, ...r, computedAtUs: now });
  }
);

// ------------------------------------------------------------------ CMP-19 simulated thermostat
/** Simulated device poll: the simulated thermostat answers at once (TRS-19-05 freshness). */
export const pollThermostat = spacetimedb.reducer(
  { householdId: t.string(), applianceId: t.string() },
  (ctx, { householdId, applianceId }) => {
    requireOwner(ctx);
    const st = [...ctx.db.thermostatState.byHouseholdAppliance.filter([householdId, applianceId])][0];
    if (!st) throw new SenderError(`no thermostat ${applianceId}`);
    ctx.db.thermostatState.id.update({ ...st, readAtUs: nowFor(ctx, householdId) });
  }
);

/** TRS-19-03: the log row is written before any command; status 'pending'. */
export const beginActuation = spacetimedb.reducer(
  {
    actuationId: t.string(), actionId: t.string(), householdId: t.string(), applianceId: t.string(),
    previousC: t.f32(), requestedC: t.f32(), appliedC: t.f32(), actor: t.string(),
  },
  (ctx, a) => {
    requireOwner(ctx);
    if (a.actor !== 'user' && a.actor !== 'undo') throw new SenderError('TRS-19-01: actuations come only from a user tap or an undo');
    const now = nowFor(ctx, a.householdId);
    ctx.db.actuation.insert({
      id: 0n, ...a, result: 'pending', error: '', tsUs: now,
      undoExpiresAtUs: a.actor === 'user' ? now + 86_400_000_000n : 0n,
    });
  }
);

/**
 * The simulated adapter's set_setpoint. It can only apply a pending, logged actuation, so a
 * command without a log row is impossible by construction (TRS-19-03).
 */
export const applySetpoint = spacetimedb.reducer(
  { actuationId: t.string() },
  (ctx, { actuationId }) => {
    requireOwner(ctx);
    const act = ctx.db.actuation.actuationId.find(actuationId);
    if (!act) throw new SenderError(`no actuation ${actuationId}`);
    if (act.result !== 'pending') throw new SenderError(`actuation ${actuationId} is ${act.result}`);
    const st = [...ctx.db.thermostatState.byHouseholdAppliance.filter([act.householdId, act.applianceId])][0];
    if (!st) throw new SenderError(`no thermostat ${act.applianceId}`);
    const now = nowFor(ctx, act.householdId);
    ctx.db.thermostatState.id.update({ ...st, currentSetpointC: act.appliedC, readAtUs: now });
    ctx.db.actuation.id.update({ ...act, result: 'applied' });
  }
);

export const failActuation = spacetimedb.reducer(
  { actuationId: t.string(), result: t.string(), error: t.string() },
  (ctx, { actuationId, result, error }) => {
    requireOwner(ctx);
    if (result !== 'failed' && result !== 'refused') throw new SenderError('result must be failed or refused');
    const act = ctx.db.actuation.actuationId.find(actuationId);
    if (!act) throw new SenderError(`no actuation ${actuationId}`);
    ctx.db.actuation.id.update({ ...act, result, error });
  }
);

// ------------------------------------------------------------------ v0.12 CMP-14 accounts
/** Sign-up. The API validates and hashes; this refuses a duplicate email. Owner only, like every write. */
export const createUserAccount = spacetimedb.reducer(
  { email: t.string(), name: t.string(), zip: t.string(), passwordHash: t.string(), householdId: t.string() },
  (ctx, a) => {
    requireOwner(ctx);
    const email = a.email.trim().toLowerCase();
    if (!email.includes('@')) throw new SenderError('email looks wrong');
    if (!/^\d{5}$/.test(a.zip)) throw new SenderError('ZIP must be 5 digits');
    if (ctx.db.userAccount.email.find(email)) throw new SenderError('an account with this email already exists');
    if (!ctx.db.household.householdId.find(a.householdId)) throw new SenderError(`no household ${a.householdId}`);
    ctx.db.userAccount.insert({ ...a, email, createdAtUs: ctx.timestamp.microsSinceUnixEpoch });
  }
);

// ------------------------------------------------------------------ v0.11 device schedules (TRS-19-10..12)
const ScheduleSpec = t.object('ScheduleSpec', {
  scheduleId: t.string(), actionId: t.string(), householdId: t.string(), applianceId: t.string(), kind: t.string(),
  weekdaysOnly: t.bool(), preStartHour: t.u8(), peakStartHour: t.u8(), peakEndHour: t.u8(), preCoolC: t.f32(),
  peakWarmC: t.f32(), minC: t.f32(), maxC: t.f32(), maxStepC: t.f32(), validUntilUs: t.i64(),
});

function scheduleInForce(ctx: Ctx, householdId: string, applianceId: string, now: bigint) {
  return [...ctx.db.thermostatSchedule.byHouseholdAppliance.filter([householdId, applianceId])].find(
    s => (s.status === 'installed' || s.status === 'removing' || s.status === 'pending') && s.validUntilUs > now
  );
}

/** TRS-19-03: the schedule row is written 'pending' before the install command. One in force per device (TRS-19-11). */
export const beginScheduleInstall = spacetimedb.reducer({ spec: ScheduleSpec }, (ctx, { spec }) => {
  requireOwner(ctx);
  if (spec.kind !== 'precool') throw new SenderError(`unknown schedule kind ${spec.kind}`);
  if (!(spec.preStartHour < spec.peakStartHour && spec.peakStartHour < spec.peakEndHour && spec.peakEndHour <= 24)) {
    throw new SenderError('schedule hours out of order');
  }
  if (spec.preCoolC < 0 || spec.peakWarmC < 0 || spec.preCoolC > spec.maxStepC || spec.peakWarmC > spec.maxStepC) {
    throw new SenderError('TRS-19-02: schedule offsets exceed the step limit');
  }
  const now = nowFor(ctx, spec.householdId);
  if (spec.validUntilUs <= now) throw new SenderError('schedule would end before it starts');
  if (spec.validUntilUs - now > 7n * 86_400_000_000n) throw new SenderError('TRS-19-11: a schedule lasts at most its week');
  if (scheduleInForce(ctx, spec.householdId, spec.applianceId, now)) throw new SenderError('TRS-19-11: a schedule is already in force on this device');
  ctx.db.thermostatSchedule.insert({
    id: 0n, ...spec, validFromUs: now, status: 'pending', error: '', removedBy: '', removedAtUs: 0n,
    undoExpiresAtUs: now + 86_400_000_000n, tsUs: now,
  });
});

/** The simulated adapter's install_schedule: only a pending, logged schedule can be installed. */
export const installSchedule = spacetimedb.reducer({ scheduleId: t.string() }, (ctx, { scheduleId }) => {
  requireOwner(ctx);
  const s = ctx.db.thermostatSchedule.scheduleId.find(scheduleId);
  if (!s) throw new SenderError(`no schedule ${scheduleId}`);
  if (s.status !== 'pending') throw new SenderError(`schedule ${scheduleId} is ${s.status}`);
  ctx.db.thermostatSchedule.id.update({ ...s, status: 'installed' });
});

/** TRS-19-03 for removal: logged 'removing' (with who asked) before the remove command. */
export const beginScheduleRemoval = spacetimedb.reducer({ scheduleId: t.string(), removedBy: t.string() }, (ctx, { scheduleId, removedBy }) => {
  requireOwner(ctx);
  if (removedBy !== 'undo') throw new SenderError('TRS-19-01: a schedule is removed only by the user (undo)');
  const s = ctx.db.thermostatSchedule.scheduleId.find(scheduleId);
  if (!s) throw new SenderError(`no schedule ${scheduleId}`);
  if (s.status !== 'installed') throw new SenderError(`schedule ${scheduleId} is ${s.status}`);
  ctx.db.thermostatSchedule.id.update({ ...s, status: 'removing', removedBy });
});

/** The simulated adapter's remove_schedule. */
export const removeSchedule = spacetimedb.reducer({ scheduleId: t.string() }, (ctx, { scheduleId }) => {
  requireOwner(ctx);
  const s = ctx.db.thermostatSchedule.scheduleId.find(scheduleId);
  if (!s) throw new SenderError(`no schedule ${scheduleId}`);
  if (s.status !== 'removing') throw new SenderError(`schedule ${scheduleId} is ${s.status}`);
  ctx.db.thermostatSchedule.id.update({ ...s, status: 'removed', removedAtUs: nowFor(ctx, s.householdId) });
});

/** A failed install ends 'failed'; a failed removal goes back to 'installed' with the error. */
export const failSchedule = spacetimedb.reducer({ scheduleId: t.string(), error: t.string() }, (ctx, { scheduleId, error }) => {
  requireOwner(ctx);
  const s = ctx.db.thermostatSchedule.scheduleId.find(scheduleId);
  if (!s) throw new SenderError(`no schedule ${scheduleId}`);
  if (s.status === 'pending') ctx.db.thermostatSchedule.id.update({ ...s, status: 'failed', error });
  else if (s.status === 'removing') ctx.db.thermostatSchedule.id.update({ ...s, status: 'installed', removedBy: '', error });
  else throw new SenderError(`schedule ${scheduleId} is ${s.status}`);
});

// ------------------------------------------------------------------ CMP-20 narrator statements
/** TRS-20-08: a new statement for an action supersedes the current one; nothing is deleted. */
export const writeStatement = spacetimedb.reducer(
  {
    statementId: t.string(), householdId: t.string(), actionId: t.string(), spikeRefJson: t.string(),
    text: t.string(), modelVersion: t.string(), unnarrated: t.bool(), inputSha: t.string(),
  },
  (ctx, a) => {
    requireOwner(ctx);
    const now = nowFor(ctx, a.householdId);
    for (const old of [...ctx.db.statement.byHouseholdCreated.filter(a.householdId)]) {
      if (old.actionId === a.actionId && old.spikeRefJson === a.spikeRefJson && old.supersededAtUs === 0n) {
        ctx.db.statement.id.update({ ...old, supersededAtUs: now });
      }
    }
    ctx.db.statement.insert({ id: 0n, ...a, supersededAtUs: 0n, createdAtUs: now });
  }
);
