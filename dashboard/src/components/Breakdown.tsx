import { useState, type ReactNode } from 'react';
import type { ApplianceItem, ApplianceRow, Appliances } from '../api';
import { Card, Chip, Empty } from './ui';

// TRS-16-03/04/06, TRS-SYS-02: each row says where its numbers come from. v0.12: rows lead with
// the splitter's estimate, as a deployed home would; the simulated feed (the practice home's answer
// key) appears only when a row is opened.
export function Breakdown({ a }: { a: Appliances | null }) {
  if (!a) return <Card title="Where the power goes"><Empty>Loading…</Empty></Card>;
  return (
    <Card id="breakdown" title="Where the power goes" subtitle={`This month so far · ${a.total_display}`}
      aside={<Chip tone="green">{a.source_label === 'estimated' && a.nilm_model_version ? `Estimated · ${a.nilm_model_version}` : a.source_label}</Chip>}>
      <ApplianceRows items={a.items} extra={i => {
        const m = i as ApplianceItem;
        return <div>Today {m.kwh_today_display} kWh{m.live_watts_display ? ` · now ${m.live_watts_display} W` : ''}{m.stale ? ' · no recent reading' : ''}</div>;
      }} />
    </Card>
  );
}

/** Shared rows for the month panel and the bill chart's day box. */
export function ApplianceRows({ items, extra }: { items: ApplianceRow[]; extra?: (i: ApplianceRow) => ReactNode }) {
  const [open, setOpen] = useState<string | null>(null);
  const max = Math.max(...items.map(i => Math.max(i.share_pct, i.compare_share_pct ?? 0)), 1);
  if (!items.length) return <Empty>No usage recorded.</Empty>;
  return (
    <ul className="bars">
      {items.map(i => (
        <li key={i.appliance_id}>
          <button className="bar-row" aria-expanded={open === i.appliance_id} onClick={() => setOpen(open === i.appliance_id ? null : i.appliance_id)}>
            <span className="bar-label">{i.label}</span>
            <span className="bar-track"><span className="bar-fill" style={{ width: `${(i.share_pct / max) * 100}%` }} /></span>
            <span className="bar-value">{i.usd_display}<span className="muted"> · {i.share_display}</span></span>
          </button>
          {open === i.appliance_id ? (
            <div className="bar-detail">
              {extra ? extra(i) : <div>{i.kwh_display} kWh</div>}
              <div className="muted">{i.source_label === 'estimated' ? 'Estimated by the appliance splitter' : i.source_label}{i.model_version ? ` · ${i.model_version}` : ''}.</div>
              {i.error_note ? <div className="muted">{i.error_note}</div> : null}
              {i.compare_label && i.compare_share_pct !== null ? (
                <div className="compare">
                  <span className="compare-label">{i.compare_label}: {i.compare_usd_display}</span>
                  <span className="bar-track"><span className="bar-compare" style={{ width: `${(i.compare_share_pct / max) * 100}%` }} /></span>
                </div>
              ) : null}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
