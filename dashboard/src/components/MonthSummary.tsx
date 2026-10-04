import type { Summary } from '../api';
import { Card, Chip, Empty, useTooltip } from './ui';

// TRS-16-02: month-to-date, projected total, and the p50–p90 range as one visual, plus a signed
// comparison to last month. TRS-16-05: forecast figures always shown with their range.
export function MonthSummary({ s }: { s: Summary | null }) {
  const tip = useTooltip();
  if (!s) return <Card title="This month's bill"><Empty>Loading…</Empty></Card>;
  const W = 640, H = 150, padL = 36, padB = 22, padT = 8;
  const days = s.daily;
  const max = Math.max(...s.ticks.map(t => t.value), ...days.map(d => d.p90_usd ?? d.usd ?? 0), 0.01);
  const slot = (W - padL) / days.length;
  const bw = Math.min(24, slot - 2);
  const y = (v: number) => H - padB - (v / max) * (H - padB - padT);
  return (
    <Card id="summary" title="This month's bill" subtitle={`${s.month_label} · ${s.fixed_charge_note}`}>
      <div className="summary-top">
        <div>
          <div className="label">So far</div>
          <div className="hero">{s.month_to_date_display}<span className="unit"> dollars</span></div>
          <div className="delta">
            {s.vs_last_month_display ? (
              <><strong>{s.vs_last_month_display}</strong> vs the same days last month</>
            ) : <span className="muted">{s.vs_last_month_note}</span>}
          </div>
        </div>
        <div className="projection">
          <div className="label">Heading for</div>
          {s.projected ? (
            <>
              <div className="proj-figure">{s.projected.p50_display}<span className="muted"> to {s.projected.p90_display}</span></div>
              <RangeBar mtd={s.daily.filter(d => d.kind === 'actual').reduce((a, d) => a + (d.usd ?? 0), 0)} p50={s.projected.p50} p90={s.projected.p90} />
              <div className="small muted">Likely total, and a high-end estimate</div>
            </>
          ) : <div className="muted">No forecast yet</div>}
        </div>
      </div>
      <div className="chart" aria-label="Daily cost this month">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Daily cost: actual days solid, forecast days light with a range line">
          {s.ticks.map(t => (
            <g key={t.value}>
              <line x1={padL} x2={W} y1={y(t.value)} y2={y(t.value)} className="grid" />
              <text x={padL - 6} y={y(t.value) + 4} className="axis" textAnchor="end">{t.display}</text>
            </g>
          ))}
          <line x1={padL} x2={W} y1={H - padB} y2={H - padB} className="baseline" />
          {days.map((d, i) => {
            const x = padL + i * slot + (slot - bw) / 2;
            const lines = [d.label, d.kind === 'actual' ? `${d.display} dollars` : d.kind === 'forecast' ? `About ${d.display}, up to ${d.p90_display} dollars` : 'No data'];
            if (d.usd == null) return null;
            const top = y(d.usd);
            return (
              <g key={d.day} {...tip.bind(lines)} tabIndex={0} className="mark">
                <rect x={x - 1} y={padT} width={bw + 2} height={H - padB - padT} fill="transparent" />
                <path d={roundTop(x, top, bw, H - padB - top)} className={d.kind === 'actual' ? 'bar-actual' : 'bar-forecast'} />
                {d.kind === 'forecast' && d.p90_usd != null ? (
                  <line x1={x + bw / 2} x2={x + bw / 2} y1={y(d.p90_usd)} y2={top} className="range-line" />
                ) : null}
                {i % 7 === 0 ? <text x={x + bw / 2} y={H - 6} className="axis" textAnchor="middle">{d.label.split(' ').slice(1).join(' ')}</text> : null}
              </g>
            );
          })}
        </svg>
        <div className="legend">
          <span><i className="key key-actual" />Spent</span>
          <span><i className="key key-forecast" />Forecast, with its high-end line</span>
        </div>
        {tip.node}
      </div>
    </Card>
  );
}

function RangeBar({ mtd, p50, p90 }: { mtd: number; p50: number; p90: number }) {
  const max = p90 * 1.05;
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`;
  return (
    <div className="rangebar" aria-hidden="true">
      <div className="rb-track" />
      <div className="rb-range" style={{ left: pct(p50), width: `calc(${pct(p90)} - ${pct(p50)})` }} />
      <div className="rb-mtd" style={{ width: pct(mtd) }} />
      <div className="rb-p50" style={{ left: pct(p50) }} />
    </div>
  );
}

export function roundTop(x: number, y: number, w: number, h: number, r = 4): string {
  if (h <= 0) return '';
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

export { Chip };
