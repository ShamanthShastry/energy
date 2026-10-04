import { type ReactNode, useState } from 'react';

export function Card({ title, subtitle, children, aside, id }: { title: string; subtitle?: ReactNode; children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <section className="card" aria-labelledby={id ? `${id}-h` : undefined}>
      <header className="card-head">
        <div>
          <h2 id={id ? `${id}-h` : undefined}>{title}</h2>
          {subtitle ? <p className="card-sub">{subtitle}</p> : null}
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function Chip({ tone = 'neutral', children, icon }: { tone?: 'neutral' | 'green' | 'warn' | 'crit' | 'sim'; children: ReactNode; icon?: string }) {
  return <span className={`chip chip-${tone}`}>{icon ? <span aria-hidden="true" className="chip-icon">{icon}</span> : null}{children}</span>;
}

export function Stale({ error, okAt }: { error: string | null; okAt: number | null }) {
  if (!error) return null;
  const age = okAt ? Math.round((Date.now() - okAt) / 1000) : null;
  return (
    <p className="stale" role="status">
      <Chip tone="crit" icon="!">Data error</Chip>
      {age !== null ? ` Showing the last update from ${age < 90 ? `${age} s` : `${Math.round(age / 60)} min`} ago.` : ' Waiting for the first update.'}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

/** Shared hover tooltip for SVG marks: label + value lines, positioned at the pointer. */
export function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; lines: string[] } | null>(null);
  const node = tip ? (
    <div className="tooltip" style={{ left: tip.x, top: tip.y }} role="tooltip">
      {tip.lines.map((l, i) => <div key={i} className={i === 0 ? 'tooltip-title' : ''}>{l}</div>)}
    </div>
  ) : null;
  const bind = (lines: string[]) => ({
    onMouseMove: (e: React.MouseEvent) => {
      const host = (e.currentTarget as Element).closest('.chart') as HTMLElement | null;
      const r = host?.getBoundingClientRect();
      setTip({ x: e.clientX - (r?.left ?? 0) + 12, y: e.clientY - (r?.top ?? 0) - 12, lines });
    },
    onMouseLeave: () => setTip(null),
    onFocus: (e: React.FocusEvent) => {
      const host = (e.currentTarget as Element).closest('.chart') as HTMLElement | null;
      const r = host?.getBoundingClientRect();
      const b = (e.currentTarget as Element).getBoundingClientRect();
      setTip({ x: b.left - (r?.left ?? 0) + b.width + 6, y: b.top - (r?.top ?? 0), lines });
    },
    onBlur: () => setTip(null),
  });
  return { node, bind };
}
