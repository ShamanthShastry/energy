import { useEffect, useRef, useState } from 'react';
import { Bolt } from './Logo';

// Intro before sign-in: "Synergy" types across the screen; once typed, the S crackles (synthesised
// electrical fizz, white sparks off its top and bottom ends) and turns into a golden bolt the size
// of the letters; then the page hands over. Click anywhere to skip.
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

/** A short electrical crackle: band-passed noise with random clicks. Needs a user gesture on most
 * browsers; returns false when the browser kept the audio context suspended. */
function crackle(): boolean {
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return false;
  const ctx = new AC();
  const dur = 0.9;
  const buf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * dur), ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const band = ctx.createBiquadFilter();
  band.type = 'bandpass';
  band.frequency.value = 3200;
  band.Q.value = 0.7;
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0.0001, ctx.currentTime);
  let t = ctx.currentTime + 0.02;
  while (t < ctx.currentTime + dur) {
    gain.gain.setValueAtTime(0.15 + Math.random() * 0.5, t);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.012 + Math.random() * 0.02);
    t += 0.02 + Math.random() * 0.05;
  }
  src.connect(band).connect(gain).connect(ctx.destination);
  src.start();
  src.onended = () => { ctx.close().catch(() => undefined); };
  if (ctx.state === 'suspended') { ctx.resume().catch(() => undefined); return ctx.state !== 'suspended'; }
  return true;
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
    for (let i = 1; i <= TITLE.length; i++) at(300 + i * TYPE_MS, () => setTyped(i));
    const typedAt = 300 + TITLE.length * TYPE_MS;
    at(typedAt + 350, () => {
      setPhase('crackle');
      setSparks(makeSparks());
      if (!crackle()) {
        const once = () => { crackle(); window.removeEventListener('pointerdown', once); window.removeEventListener('keydown', once); };
        window.addEventListener('pointerdown', once);
        window.addEventListener('keydown', once);
        timers.push(window.setTimeout(() => { window.removeEventListener('pointerdown', once); window.removeEventListener('keydown', once); }, 2500));
      }
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
