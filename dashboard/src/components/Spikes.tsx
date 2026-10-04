import type { Spikes as S } from '../api';
import { roundTop } from './MonthSummary';
import { Card, Chip, Empty, useTooltip } from './ui';

// TRS-15-03 spike: a forecast day more than 25% above the usual day. Amber plus a text label
// (never colour alone).
export function Spikes({ s }: { s: S | null }) {
  const tip = useTooltip();
  if (!s) return <Card title="Looking ahead"><Empty>Loading…</Empty></Card>;
  if (!s.days.length) return <Card title="Looking ahead"><Empty>No forecast yet. It appears after the first full week.</Empty></Card>;
  const W = 380, H = 170, padL = 30, padB = 22, padT = 18;
  const max = Math.max(...(s.ticks ?? []).map(t => t.value), ...s.days.map(d => d.p90_usd), s.baseline_usd ?? 0, 0.01);
  const slot = (W - padL) / s.days.length;
  const bw = Math.min(24, slot - 2);
  const y = (v: number) => H - padB - (v / max) * (H - padB - padT);
  const sp = s.spike;
  return (
    <Card id="spikes" title="Looking ahead"
      subtitle={sp ? <><strong>{sp.label}</strong> looks about {sp.delta_display} above a usual day, mostly from the {sp.driver_label?.toLowerCase()}. The line on each bar reaches a high-end estimate.</>
        : <>No day in the next week looks more than {s.margin_pct}% above a usual {s.baseline_display} day.</>}
      aside={sp ? <Chip tone="warn" icon="▲">Heads-up</Chip> : <Chip tone="green" icon="✓">Calm week</Chip>}>
      <div className="chart">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Forecast cost for the next 7 days">
          {(s.ticks ?? []).map(t => (
            <g key={t.value}>
              <line x1={padL} x2={W} y1={y(t.value)} y2={y(t.value)} className="grid" />
              <text x={padL - 6} y={y(t.value) + 4} className="axis" textAnchor="end">{t.display}</text>
            </g>
          ))}
          {s.baseline_usd ? (
            <g>
              <line x1={padL} x2={W} y1={y(s.baseline_usd)} y2={y(s.baseline_usd)} className="ref" />
              <text x={W} y={y(s.baseline_usd) - 4} className="axis" textAnchor="end">usual day</text>
            </g>
          ) : null}
          <line x1={padL} x2={W} y1={H - padB} y2={H - padB} className="baseline" />
          {s.days.map((d, i) => {
            const x = padL + i * slot + (slot - bw) / 2;
            const top = y(d.p50_usd);
            return (
              <g key={d.day} className="mark" tabIndex={0} {...tip.bind([d.label, `About ${d.p50_display}, up to ${d.p90_display}`, ...(d.spike ? [`Higher than usual: mostly ${d.driver_label}`] : [])])}>
                <rect x={x - 4} y={padT} width={bw + 8} height={H - padB - padT} fill="transparent" />
                <path d={roundTop(x, top, bw, H - padB - top)} className={`rise-y ${d.spike ? 'bar-spike' : 'bar-forecast'}`} style={{ animationDelay: `${0.35 + i * 0.05}s` }} />
                <line x1={x + bw / 2} x2={x + bw / 2} y1={y(d.p90_usd)} y2={top} className={d.spike ? 'range-line warn' : 'range-line'} />
                {d.spike ? <text x={x + bw / 2} y={y(d.p90_usd) - 5} className="axis strong" textAnchor="middle">high</text> : null}
                <text x={x + bw / 2} y={H - 6} className="axis" textAnchor="middle">{d.label.split(' ')[0]}</text>
              </g>
            );
          })}
        </svg>
        {tip.node}
      </div>
    </Card>
  );
}
