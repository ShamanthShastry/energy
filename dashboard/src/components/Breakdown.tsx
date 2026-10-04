import { useState } from 'react';
import type { Appliances } from '../api';
import { Card, Chip, Empty } from './ui';

// TRS-16-03/04/06, TRS-SYS-02: each tile says where its numbers come from; stale tiles say so.
export function Breakdown({ a }: { a: Appliances | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!a) return <Card title="Where the power goes"><Empty>Loading…</Empty></Card>;
  const max = Math.max(...a.items.map(i => i.share_pct), 1);
  return (
    <Card id="breakdown" title="Where the power goes" subtitle={`This month so far · ${a.total_display} dollars · updated ${a.as_of}`}
      aside={<Chip tone="sim" icon="◌">Simulated feed</Chip>}>
      <ul className="bars">
        {a.items.map(i => (
          <li key={i.appliance_id}>
            <button className="bar-row" aria-expanded={open === i.appliance_id} onClick={() => setOpen(open === i.appliance_id ? null : i.appliance_id)}>
              <span className="bar-label">{i.label}</span>
              <span className="bar-track"><span className="bar-fill" style={{ width: `${(i.share_pct / max) * 100}%` }} /></span>
              <span className="bar-value">{i.usd_mtd_display}<span className="muted"> · {i.share_display}</span></span>
            </button>
            {open === i.appliance_id ? (
              <div className="bar-detail">
                <div>Today {i.kwh_today_display} kWh{i.live_watts_display ? ` · now ${i.live_watts_display} W` : ''}{i.stale ? ' · no recent reading' : ''}</div>
                <div className="muted">{i.source_label}{i.model_version ? ` · ${i.model_version}` : ''}. {i.error_detail}</div>
                {i.nilm_note ? <div className="muted">{i.nilm_note}</div> : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}
