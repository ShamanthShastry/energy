import type { Savings } from '../api';
import { Card, Chip, Empty } from './ui';

// TRS-16-12 / TRS-18-04: verified savings, kept apart from promised ones, and every past outcome.
const TONE: Record<string, 'green' | 'neutral'> = { verified: 'green', accepted: 'green' };

export function SavingsTab({ s }: { s: Savings | null }) {
  if (!s) return <Card title="Savings"><Empty>Loading…</Empty></Card>;
  return (
    <div className="stack">
      <Card id="savings" title="Money actually saved" subtitle="Measured a week after each change, against what the forecast said would have happened.">
        <div className="hero">{s.verified_total_display}<span className="unit"> dollars</span></div>
        <p className="muted">Changes you took were expected to save {s.promised_total_display} dollars over their weeks.</p>
      </Card>
      <Card id="history" title="What happened to each suggestion">
        {s.items.length === 0 ? <Empty>Nothing yet. Suggestions show up here once taken, dismissed, or past their week.</Empty> : (
          <ul className="history">
            {s.items.map(i => (
              <li key={i.action_id}>
                <div className="history-week small muted">{i.week_label}</div>
                <div className="history-body">
                  <div>{i.sentence}</div>
                  {i.detail ? <div className="small muted">{i.detail}</div> : null}
                </div>
                <Chip tone={TONE[i.outcome] ?? 'neutral'}>{i.outcome_label}</Chip>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
