import { useEffect, useState } from 'react';
import { api, ApiError, usePoll, type Actions, type Me, type Alerts, type Appliances, type Meta, type Savings, type Spikes as SpikesT, type Summary, type Thermostat } from './api';
import { ActionsTab } from './components/ActionsTab';
import { AuthScreen } from './components/AuthScreen';
import { Biggest } from './components/Biggest';
import { Breakdown } from './components/Breakdown';
import { Health } from './components/Health';
import { MonthSummary } from './components/MonthSummary';
import { SavingsTab } from './components/SavingsTab';
import { Spikes } from './components/Spikes';
import { Stale } from './components/ui';

type Tab = 'home' | 'actions' | 'savings';
const TABS: { id: Tab; label: string }[] = [{ id: 'home', label: 'Home' }, { id: 'actions', label: 'Actions' }, { id: 'savings', label: 'Savings' }];

function initialTab(): Tab {
  const h = window.location.hash.replace('#', '');
  return (TABS.find(t => t.id === h)?.id) ?? 'home';
}

// v0.12: the dashboard opens behind a simple sign-up / log-in (CMP-14).
export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    api.get<Me>('/api/auth/me').then(setMe).catch(e => setMe(e instanceof ApiError && e.status === 401 ? null : null));
  }, []);
  if (me === undefined) return <div className="app"><p className="empty">Loading…</p></div>;
  if (me === null) return <AuthScreen onIn={m => { window.location.hash = 'home'; setMe(m); }} />;
  return <Dashboard me={me} onOut={() => { api.post('/api/auth/logout').finally(() => setMe(null)); }} />;
}

function Dashboard({ me, onOut }: { me: Me; onOut: () => void }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  useEffect(() => { window.location.hash = tab; }, [tab]);
  useEffect(() => {
    const onHash = () => setTab(initialTab());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const meta = usePoll<Meta>('/api/meta');
  const summary = usePoll<Summary>('/api/summary', 15000);
  const apps = usePoll<Appliances>('/api/appliances');
  const spikes = usePoll<SpikesT>('/api/spikes', 30000);
  const alerts = usePoll<Alerts>('/api/alerts', 15000);
  const actions = usePoll<Actions>('/api/actions');
  const savings = usePoll<Savings>('/api/savings', 15000);
  const thermo = usePoll<Thermostat>('/api/thermostat');
  const anyError = [meta, summary, apps, spikes, alerts, actions, savings, thermo].find(p => p.error);
  const refresh = () => { actions.reload(); thermo.reload(); savings.reload(); };
  const openCount = actions.data?.items.filter(i => i.viable).length ?? 0;

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden="true">⌁</span>
          <span>Synergy</span>
        </div>
        <div className="top-meta">
          <span className="small muted">{me.name}</span>
          <button className="btn btn-quiet" onClick={onOut}>Log out</button>
        </div>
      </header>
      <div className="home-head">
        <h1>{me.name.split(' ')[0]}'s home</h1>
      </div>
      <nav className="tabs" role="tablist" aria-label="Sections">
        {TABS.map(t => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'tab active' : 'tab'} onClick={() => setTab(t.id)}>
            {t.label}{t.id === 'actions' && openCount ? <span className="badge">{openCount}</span> : null}
          </button>
        ))}
      </nav>
      <main>
        {anyError ? <Stale error={anyError.error} okAt={anyError.okAt} /> : null}
        {tab === 'home' ? (
          <div className="grid">
            <div className="span-2"><MonthSummary s={summary.data} /></div>
            <Breakdown a={apps.data} />
            <Spikes s={spikes.data} />
            <Health a={alerts.data} />
            <Biggest a={actions.data} onGo={() => setTab('actions')} />
          </div>
        ) : tab === 'actions' ? (
          <ActionsTab a={actions.data} t={thermo.data} refresh={refresh} />
        ) : (
          <SavingsTab s={savings.data} />
        )}
      </main>
      <footer className="foot small muted">
        {meta.data ? <>{meta.data.simulated_feed ? 'Simulated feed · ' : ''}{meta.data.tariff_name} · {meta.data.weather_note} Practice-home data from the Dinar et al. NILM dataset.</> : null}
      </footer>
    </div>
  );
}
