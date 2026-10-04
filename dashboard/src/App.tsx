import { useEffect, useState } from 'react';
import { usePoll, type Actions, type Alerts, type Appliances, type Meta, type Savings, type Spikes as SpikesT, type Summary, type Thermostat } from './api';
import { ActionsTab } from './components/ActionsTab';
import { Biggest } from './components/Biggest';
import { Breakdown } from './components/Breakdown';
import { Health } from './components/Health';
import { MonthSummary } from './components/MonthSummary';
import { SavingsTab } from './components/SavingsTab';
import { Spikes } from './components/Spikes';
import { Chip, Stale } from './components/ui';

type Tab = 'home' | 'actions' | 'savings';
const TABS: { id: Tab; label: string }[] = [{ id: 'home', label: 'Home' }, { id: 'actions', label: 'Actions' }, { id: 'savings', label: 'Savings' }];

function initialTab(): Tab {
  const h = window.location.hash.replace('#', '');
  return (TABS.find(t => t.id === h)?.id) ?? 'home';
}

export default function App() {
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
          <span>HomeWatt</span>
        </div>
        <div className="top-meta">
          {meta.data ? <span className="clock">{meta.data.now_label}</span> : null}
          {meta.data?.simulated_feed ? <Chip tone="sim" icon="◌">Simulated feed</Chip> : null}
        </div>
      </header>
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
        {meta.data ? <>{meta.data.tariff_name} · {meta.data.weather_note} Practice-home data from the Dinar et al. NILM dataset.</> : null}
      </footer>
    </div>
  );
}
