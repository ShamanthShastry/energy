import { useState, type FormEvent } from 'react';
import { api, ApiError, type Me } from '../api';

// v0.12 CMP-14: sign up (name, email, password, ZIP) or log in, then straight to the Home tab.
// Simple accounts on purpose: every account opens the demo home (OI-07).
export function AuthScreen({ onIn }: { onIn: (me: Me) => void }) {
  const [mode, setMode] = useState<'signup' | 'login'>('signup');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body = Object.fromEntries(f.entries());
    setBusy(true);
    setErr(null);
    try {
      onIn(await api.post<Me>(mode === 'signup' ? '/api/auth/signup' : '/api/auth/login', body));
    } catch (x) {
      setErr(x instanceof ApiError ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="brand auth-brand"><span className="logo" aria-hidden="true">⌁</span><span>Synergy</span></div>
      <section className="card auth-card">
        <div className="auth-tabs" role="tablist" aria-label="Sign up or log in">
          <button role="tab" aria-selected={mode === 'signup'} className={mode === 'signup' ? 'tab active' : 'tab'} onClick={() => { setMode('signup'); setErr(null); }}>Sign up</button>
          <button role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'tab active' : 'tab'} onClick={() => { setMode('login'); setErr(null); }}>Log in</button>
        </div>
        <form className="auth-form" onSubmit={submit} key={mode}>
          {mode === 'signup' ? (
            <label>Name<input id="auth-name" name="name" autoComplete="name" required /></label>
          ) : null}
          <label>Email<input id="auth-email" name="email" type="email" autoComplete="email" required /></label>
          <label>Password<input id="auth-password" name="password" type="password" minLength={mode === 'signup' ? 8 : undefined}
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} required /></label>
          {mode === 'signup' ? (
            <label>ZIP code<input id="auth-zip" name="zip" inputMode="numeric" pattern="[0-9]{5}" maxLength={5} autoComplete="postal-code" required /></label>
          ) : null}
          {err ? <p className="notice notice-crit" role="alert">{err}</p> : null}
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? '…' : mode === 'signup' ? 'Create account' : 'Log in'}</button>
          {mode === 'signup' ? <p className="small muted">Password at least 8 characters. Your account opens the practice home.</p> : null}
        </form>
      </section>
    </div>
  );
}
