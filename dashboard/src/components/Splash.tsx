import { useEffect, useRef, useState } from 'react';
import { Bolt } from './Logo';
import { crackle, tick, unlock } from './sound';

// Intro before sign-in: "Synergy" types across the screen (a soft tick per letter); once typed, the S
// crackles (electrical fizz) with white sparks off its top and bottom ends, then turns into a golden
// bolt the size of the letters; then the page hands over. Click anywhere to skip.
const TITLE = 'Synergy';
const TYPE_MS = 140;
const SPARKS = 26;

type Phase = 'type' | 'crackle' | 'bolt' | 'out';
type Spark = { id: number; end: 'top' | 'bottom'; dx: number; dy: number; delay: number; life: number; size: number };

function makeSparks(): Spark[] {
  const out: Spark[] = [];
  for (let i = 0; i < SPARKS; i++) {
    const end = i % 2 ? 'top' : 'bottom';
    const up = end === 'top' ? -1 : 1;
    const angle = (Math.random() * 1.3 - 0.65) + (up < 0 ? -Math.PI / 2 : Math.PI / 2);
    const speed = 40 + Math.random() * 90;
    out.push({ id: i, end, dx: Math.cos(angle) * speed, dy: Math.sin(angle) * speed, delay: Math.random() * 450, life: 350 + Math.random() * 350, size: 3 + Math.random() * 3 });
  }
  return out;
}

export function Splash({ onDone }: { onDone: () => void }) {
  const [typed, setTyped] = useState(0);
  const [phase, setPhase] = useState<Phase>('type');
  const [sparks, setSparks] = useState<Spark[]>([]);
  const sRef = useRef<HTMLSpanElement>(null);
  const [sBox, setSBox] = useState<{ w: number; h: number } | null>(null);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const timers: number[] = [];
    const at = (ms: number, f: () => void) => timers.push(window.setTimeout(f, ms));
    if (reduced) {
      setTyped(TITLE.length);
      setPhase('bolt');
      at(900, () => done.current());
      return () => timers.forEach(window.clearTimeout);
    }
    unlock();
    for (let i = 1; i <= TITLE.length; i++) at(300 + i * TYPE_MS, () => { setTyped(i); tick(); });
    const typedAt = 300 + TITLE.length * TYPE_MS;
    at(typedAt + 350, () => {
      setPhase('crackle');
      setSparks(makeSparks());
      crackle();
    });
    at(typedAt + 1150, () => setPhase('bolt'));
    at(typedAt + 2500, () => setPhase('out'));
    at(typedAt + 3100, () => done.current());
    return () => timers.forEach(window.clearTimeout);
  }, []);

  useEffect(() => {
    if (sRef.current) { const r = sRef.current.getBoundingClientRect(); setSBox({ w: r.width, h: r.height }); }
  }, [typed]);

  const showS = typed >= 1;
  return (
    <div className={`splash phase-${phase}`} onClick={() => done.current()} role="presentation">
      <div className="type-title" aria-label={TITLE}>
        <span className="type-s-slot" style={sBox ? { width: sBox.w, height: sBox.h } : undefined}>
          <span ref={sRef} className={`type-s ${showS ? '' : 'type-hidden'}`}>S</span>
          <Bolt className="type-bolt" />
          {phase === 'crackle' ? (
            <span className="sparks" aria-hidden="true">
              {sparks.map(s => (
                <i key={s.id} className={`spark spark-${s.end}`}
                  style={{ '--dx': `${s.dx}px`, '--dy': `${s.dy}px`, animationDelay: `${s.delay}ms`, animationDuration: `${s.life}ms`, width: s.size, height: s.size } as React.CSSProperties} />
              ))}
            </span>
          ) : null}
        </span>
        <span className="type-rest">{TITLE.slice(1, Math.max(typed, 1))}</span>
        <span className={`caret ${phase === 'type' ? '' : 'caret-off'}`} aria-hidden="true" />
      </div>
    </div>
  );
}
