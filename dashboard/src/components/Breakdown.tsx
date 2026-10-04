import { useState } from 'react';
import type { Appliances } from '../api';
import { Card, Chip, Empty } from './ui';

// TRS-16-03/04/06, TRS-SYS-02: each tile says where its numbers come from; stale tiles say so.
// OI-13: the thin line under each bar is the splitter's estimate (source nilm) of the same thing.
export function Breakdown({ a }: { a: Appliances | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!a) return <Card title="Where the power goes"><Empty>Loading…</Empty></Card>;
  const max = Math.max(...a.items.map(i => Math.max(i.share_pct, i.est_share_pct ?? 0)), 1);
  return (
    <Card id="breakdown" title="Where the power goes" subtitle={`This month so far · ${a.total_display} dollars · updated ${a.as_of}`}
      aside={<Chip tone="sim" icon="◌">Simulated feed</Chip>}>
      {a.nilm_model_version ? <p className="bars-key muted"><span className="key-fill" /> Simulated feed <span className="key-est" /> Splitter estimate ({a.nilm_model_version})</p> : null}
      <ul className="bars">
        {a.items.map(i => (
          <li key={i.appliance_id}>
            <button className="bar-row" aria-expanded={open === i.appliance_id} onClick={() => setOpen(open === i.appliance_id ? null : i.appliance_id)}>
              <span className="bar-label">{i.label}</span>
              <span className="bar-track">
                <span className="bar-fill" style={{ width: `${(i.share_pct / max) * 100}%` }} />
                {i.est_share_pct !== null ? <span className="bar-est" style={{ width: `${(i.est_share_pct / max) * 100}%` }} /> : null}
              </span>
              <span className="bar-value">{i.usd_mtd_display}<span className="muted"> · {i.share_display}{i.est_usd_mtd_display ? ` · est. ${i.est_usd_mtd_display}` : ''}</span></span>
            </button>
            {open === i.appliance_id ? (
              <div className="bar-detail">
                <div>Today {i.kwh_today_display} kWh{i.live_watts_display ? ` · now ${i.live_watts_display} W` : ''}{i.stale ? ' · no recent reading' : ''}</div>
                <div className="muted">{i.source_label}{i.model_version ? ` · ${i.model_version}` : ''}. {i.error_detail}</div>
                {i.est_label ? <div className="muted">Splitter estimate this month: {i.est_usd_mtd_display} dollars ({i.est_label}).</div> : null}
                {i.nilm_note ? <div className="muted">{i.nilm_note}</div> : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}
