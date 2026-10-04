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
const GAP_THRESHOLD_S = 10.0; // TRS-05-03
const NOMINAL_PERIOD_S = 2.0; // TRS-01-02
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
 * Writes plug (CMP-05) or NILM (CMP-09) rows and maintains the hourly/daily rollups.
 * dtS = interval since the previous row of the same key when <= 10 s, else the nominal 2 s,
 * so a gap contributes no energy (TRS-08-03). TRS-08-01 duplicates are skipped; TRS-08-02
 * nilm rows require modelVersion; TRS-08-06 a new modelVersion adds rows under its own key.
 */
export const writeAppliancePower = spacetimedb.reducer(
  { rows: t.array(AppliancePowerRow), source: t.string(), modelVersion: t.string() },
  (ctx, { rows, source, modelVersion }) => {
    requireOwner(ctx);
    if (source !== 'plug' && source !== 'nilm') throw new SenderError(`bad source '${source}'`);
    if (source === 'nilm' && modelVersion === '') throw new SenderError('TRS-08-02: nilm rows require modelVersion');
    if (source === 'plug' && modelVersion !== '') throw new SenderError('plug rows carry no modelVersion');
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
        if (prev === r.tsUs) continue; // duplicate (TRS-08-01)
        throw new SenderError(`out-of-order row for ${r.applianceId} at ${r.tsUs}`);
      }
      const deltaS = prev < 0n ? NOMINAL_PERIOD_S : Number(r.tsUs - prev) / 1e6;
      const dtS = deltaS > 0 && deltaS <= GAP_THRESHOLD_S ? deltaS : NOMINAL_PERIOD_S;
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
