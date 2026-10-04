// Intro sounds, synthesised with Web Audio (no files). Browsers keep audio silent until the person
// has clicked or pressed a key on the page, so every call is best-effort and `unlock` resumes the
// context on the first gesture.
let ctx: AudioContext | null = null;

function get(): AudioContext | null {
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  if (!ctx) ctx = new AC();
  if (ctx.state === 'suspended') ctx.resume().catch(() => undefined);
  return ctx;
}

export function unlock(): void {
  const once = () => { get(); window.removeEventListener('pointerdown', once); window.removeEventListener('keydown', once); };
  window.addEventListener('pointerdown', once);
  window.addEventListener('keydown', once);
}

function noise(c: AudioContext, seconds: number): AudioBufferSourceNode {
  const buf = c.createBuffer(1, Math.ceil(c.sampleRate * seconds), c.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  const src = c.createBufferSource();
  src.buffer = buf;
  return src;
}

/** A soft key tick: a 12 ms low-passed noise burst, quiet. */
export function tick(): void {
  const c = get();
  if (!c || c.state !== 'running') return;
  const t = c.currentTime;
  const src = noise(c, 0.03);
  const lp = c.createBiquadFilter();
  lp.type = 'lowpass';
  lp.frequency.value = 1400 + Math.random() * 600;
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.07, t + 0.002);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.014);
  src.connect(lp).connect(g).connect(c.destination);
  src.start(t);
  src.stop(t + 0.03);
}

/** An electrical crackle: band-passed noise with random clicks, just under a second. */
export function crackle(): void {
  const c = get();
  if (!c || c.state !== 'running') return;
  const t0 = c.currentTime;
  const dur = 0.9;
  const src = noise(c, dur);
  const band = c.createBiquadFilter();
  band.type = 'bandpass';
  band.frequency.value = 3200;
  band.Q.value = 0.7;
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t0);
  let t = t0 + 0.02;
  while (t < t0 + dur) {
    g.gain.setValueAtTime(0.15 + Math.random() * 0.5, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.012 + Math.random() * 0.02);
    t += 0.02 + Math.random() * 0.05;
  }
  src.connect(band).connect(g).connect(c.destination);
  src.start(t0);
  src.stop(t0 + dur);
}
