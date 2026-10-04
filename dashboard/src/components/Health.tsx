import type { Alerts } from '../api';
import { Card, Chip, Empty } from './ui';

// CMP-12 alerts. "act" is amber with an icon and a word; "watch" is a muted chip (design tokens).
export function Health({ a }: { a: Alerts | null }) {
  if (!a) return <Card title="Appliance health"><Empty>Loading…</Empty></Card>;
  return (
    <Card id="health" title="Appliance health" subtitle={a.monitored.length ? `Watching: ${a.monitored.join(', ')}` : undefined}>
      {a.items.length === 0 ? (
        <p className="ok-line"><Chip tone="green" icon="✓">All normal</Chip> Nothing is behaving unusually.</p>
      ) : (
        <ul className="alerts">
          {a.items.map(x => (
            <li key={x.alert_id}>
              {x.severity === 'act' ? <Chip tone="warn" icon="⚠">Check soon</Chip> : <Chip tone="neutral" icon="•">Keep an eye on</Chip>}
              <div>
                <div className="alert-text">{x.text}</div>
                <div className="small muted">Since {x.since_label}. Usual causes for a fridge: dusty coils or a worn door seal.</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
