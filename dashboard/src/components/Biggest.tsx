import type { Actions } from '../api';
import { Card, Empty } from './ui';

// TRS-16-08 (v0.6): information only. Acting happens on the Actions tab.
export function Biggest({ a, onGo }: { a: Actions | null; onGo: () => void }) {
  const b = a?.biggest;
  return (
    <Card id="biggest" title="Biggest saving available">
      {!a ? <Empty>Loading…</Empty> : !b ? <Empty>No suggestions yet. They arrive at the start of each week.</Empty> : (
        <div className="biggest">
          <p className="biggest-sentence">{b.sentence}</p>
          <div className="biggest-figures">
            <div className="stat"><div className="big-num">{b.saving_month_display}</div><div className="caption">A month</div></div>
            <div className="stat"><div className="mid-num">{b.kg_month_display} kg</div><div className="caption">CO₂ a month</div></div>
          </div>
          <button className="link-btn" onClick={onGo}>See all suggestions →</button>
        </div>
      )}
    </Card>
  );
}
