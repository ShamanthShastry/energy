// The dashboard's only data source is CMP-15 (TRS-16-10). Every number arrives as a display string.
import { useCallback, useEffect, useRef, useState } from 'react';

export type Tick = { value: number; display: string };

export type Meta = {
  household_id: string; now_label: string; simulated_clock: boolean; simulated_feed: boolean;
  tariff_name: string; weather_note: string;
};
export type DailyPoint = {
  day: string; label: string; kind: 'actual' | 'forecast' | 'none'; usd: number | null; p90_usd: number | null;
  display: string | null; p90_display: string | null;
};
export type Summary = {
  month_label: string; month_to_date_display: string;
  projected: { p50: number; p90: number; p50_display: string; p90_display: string } | null;
  projected_reason: string | null; vs_last_month_pct: number | null; vs_last_month_display: string | null;
  vs_last_month_note: string | null; daily: DailyPoint[]; ticks: Tick[]; fixed_charge_note: string;
};
export type ApplianceItem = {
  appliance_id: string; label: string; usd_mtd: number; usd_mtd_display: string; share_pct: number; share_display: string;
  kwh_today_display: string; live_watts_display: string | null; stale: boolean; source: string; source_label: string;
  model_version: string; error_detail: string; nilm_note: string | null;
  est_usd_mtd: number | null; est_usd_mtd_display: string | null; est_share_pct: number | null; est_label: string | null;
};
export type Appliances = { items: ApplianceItem[]; total_display: string; as_of: string; nilm_model_version: string | null };
export type SpikeDay = {
  day: string; label: string; p50_usd: number; p90_usd: number; p50_display: string; p90_display: string;
  spike: boolean; delta_display: string; driver_label: string | null;
};
export type Spikes = {
  days: SpikeDay[]; baseline_usd?: number; baseline_display: string | null; spike: (SpikeDay & { delta_usd: number }) | null;
  margin_pct: number; ticks?: Tick[];
};
export type Alert = { alert_id: number; appliance_label: string; text: string; severity: 'watch' | 'act'; since_label: string; acknowledged: boolean };
export type Alerts = { items: Alert[]; monitored: string[] };
export type ActionItem = {
  action_id: string; rank: number; appliance_label: string; action_type: string; sentence: string; narrated: boolean;
  saving_month_display: string; kg_month_display: string; status: string; status_label: string; viable: boolean;
  take_kind: 'thermostat' | 'schedule' | 'accept';
};
export type Actions = { week_id: string; week_label: string; first_week: boolean; items: ActionItem[]; biggest: ActionItem | null };
export type SavingsItem = {
  action_id: string; week_label: string; this_week: boolean; appliance_label: string; sentence: string;
  outcome: 'verified' | 'not_verified' | 'accepted' | 'dismissed' | 'expired'; outcome_label: string; detail: string;
};
export type Savings = {
  verified_total_display: string; promised_total_display: string; counts: Record<string, number>; items: SavingsItem[];
};
export type Thermostat = {
  present: boolean; label?: string; setpoint_c?: number; simulated?: boolean;
  last_change?: {
    actuation_id: string; actor: string; result: string; error: string; previous_c: number; applied_c: number;
    at_label: string; can_undo: boolean; undo_until_label: string | null;
  } | null;
  schedule?: ScheduleView | null;
};
export type TakeResult =
  | { kind: 'accepted' }
  | { kind: 'thermostat'; preview: { device_label: string; current_c: number; requested_c: number; applied_c: number; clamped: boolean; simulated: boolean; saving_month_display: string } }
  | { kind: 'schedule'; preview: SchedulePreview };
export type SchedulePreview = {
  device_label: string; current_display: string; lines: string[]; days_label: string; until_label: string; simulated: boolean; saving_month_display: string;
};
export type ScheduleView = {
  schedule_id: string; state: 'on' | 'ended' | 'undone' | 'failed'; error: string; title: string; lines: string[];
  days_label: string; until_label: string; now_display: string; now_differs: boolean; can_undo: boolean; undo_until_label: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'content-type': 'application/json' }, ...init });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* keep status */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string) => request<T>(path, { method: 'POST' }),
};

/** Poll an endpoint (TRS-16-03: <= 5 s). On failure keep the last good payload and report its age
 * (CMP-16 error handling: never a blank page). */
export function usePoll<T>(path: string, intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [okAt, setOkAt] = useState<number | null>(null);
  const timer = useRef<number | null>(null);
  const load = useCallback(async () => {
    try {
      const d = await api.get<T>(path);
      setData(d);
      setError(null);
      setOkAt(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [path]);
  useEffect(() => {
    load();
    timer.current = window.setInterval(load, intervalMs);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [load, intervalMs]);
  return { data, error, okAt, reload: load };
}
