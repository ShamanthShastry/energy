import { useState } from 'react';
import { api, ApiError, type Actions, type SchedulePreview, type TakeResult, type Thermostat } from '../api';
import { Card, Chip, Empty } from './ui';

type Preview = Extract<TakeResult, { kind: 'thermostat' }>['preview'];

// TRS-16-11 (v0.7): ranked suggestions, a Take action column and a Dismiss button on viable rows.
// A thermostat action needs two taps: open (state current and target), then confirm (TRS-19-08).
// v0.11: precool installs a week-long weekday schedule the same way (TRS-19-10..12).
export function ActionsTab({ a, t, refresh }: { a: Actions | null; t: Thermostat | null; refresh: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'green' | 'crit' | 'neutral'; text: string } | null>(null);
  const [confirm, setConfirm] = useState<{ id: string; p: Preview } | null>(null);
  const [sched, setSched] = useState<{ id: string; p: SchedulePreview } | null>(null);

  async function run<T>(id: string, f: () => Promise<T>): Promise<T | null> {
    setBusy(id);
    setMsg(null);
    try { return await f(); }
    catch (e) { setMsg({ tone: 'crit', text: e instanceof ApiError ? e.message : String(e) }); return null; }
    finally { setBusy(null); refresh(); }
  }
  async function take(id: string) {
    const r = await run(id, () => api.post<TakeResult>(`/api/actions/${id}/take`));
    if (!r) return;
    if (r.kind === 'thermostat') setConfirm({ id, p: r.preview });
    else if (r.kind === 'schedule') setSched({ id, p: r.preview });
    else setMsg({ tone: 'green', text: 'Marked as taken. We will check next week whether it saved money.' });
  }
  async function confirmIt() {
    if (!confirm) return;
    const id = confirm.id;
    setConfirm(null);
    const r = await run(id, () => api.post<{ result: string; applied_c: number; error: string }>(`/api/actions/${id}/confirm`));
    if (r) setMsg(r.result === 'applied'
      ? { tone: 'green', text: `Thermostat set to ${r.applied_c} °C. You can undo this for 24 hours.` }
      : { tone: 'crit', text: `The thermostat did not change: ${r.error}` });
  }
  async function confirmSchedule() {
    if (!sched) return;
    const { id, p } = sched;
    setSched(null);
    const r = await run(id, () => api.post<{ result: string; error: string }>(`/api/actions/${id}/confirm`));
    if (r) setMsg(r.result === 'installed'
      ? { tone: 'green', text: `Precool schedule installed on the ${p.device_label}, ${p.days_label} through ${p.until_label}. You can undo this for 24 hours.` }
      : { tone: 'crit', text: `The schedule was not installed: ${r.error}` });
  }
  async function undoSchedule(scheduleId: string) {
    const r = await run(scheduleId, () => api.post<{ result: string; error: string }>(`/api/schedules/${scheduleId}/undo`));
    if (r) setMsg(r.result === 'removed' ? { tone: 'neutral', text: 'Undone. The precool schedule is off.' } : { tone: 'crit', text: `The schedule is still on: ${r.error}` });
  }
  async function dismiss(id: string) {
    const r = await run(id, () => api.post(`/api/actions/${id}/dismiss`));
    if (r) setMsg({ tone: 'neutral', text: 'Dismissed. Another suggestion may take its place at the next update.' });
  }
  async function undo(actuationId: string) {
    const r = await run(actuationId, () => api.post<{ result: string; applied_c: number }>(`/api/actuations/${actuationId}/undo`));
    if (r) setMsg({ tone: 'neutral', text: `Undone. Thermostat back to ${r.applied_c} °C.` });
  }

  return (
    <div className="stack">
      {t?.present ? (
        <Card id="thermostat" title="Thermostat" aside={t.simulated ? <Chip tone="sim" icon="◌">Simulated device</Chip> : undefined}>
          <div className="thermo">
            <div><span className="big-num">{t.setpoint_c}</span> <span className="muted">°C cooling setpoint</span></div>
            {t.last_change ? (
              <div className="small">
                {t.last_change.result === 'failed'
                  ? <Chip tone="crit" icon="!">Change failed</Chip>
                  : <>Last change {t.last_change.at_label}: {t.last_change.previous_c} → {t.last_change.applied_c} °C{t.last_change.actor === 'undo' ? ' (undo)' : ''}</>}
                {t.last_change.can_undo ? (
                  <button className="btn btn-quiet" disabled={!!busy} onClick={() => undo(t.last_change!.actuation_id)}>Undo (until {t.last_change.undo_until_label})</button>
                ) : null}
              </div>
            ) : <div className="small muted">No changes yet.</div>}
            {t.schedule ? (
              <div className="schedule small">
                <div><strong>{t.schedule.title}</strong>{' '}
                  {t.schedule.state === 'on' ? <Chip tone="green">On</Chip>
                    : t.schedule.state === 'failed' ? <Chip tone="crit" icon="!">Not installed</Chip>
                    : <Chip tone="neutral">{t.schedule.state === 'undone' ? 'Undone' : 'Ended'}</Chip>}
                </div>
                <div className="muted">{t.schedule.days_label} {t.schedule.until_label}</div>
                <ul className="schedule-lines">{t.schedule.lines.map(l => <li key={l}>{l}</li>)}</ul>
                {t.schedule.state === 'on' && t.schedule.now_differs ? <div>Right now: {t.schedule.now_display} °C</div> : null}
                {t.schedule.can_undo ? (
                  <button className="btn btn-quiet" disabled={!!busy} onClick={() => undoSchedule(t.schedule!.schedule_id)}>Undo (until {t.schedule.undo_until_label})</button>
                ) : null}
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}

      <Card id="actions" title="Suggestions" subtitle={a ? <>{a.week_label}{a.first_week ? ' · Still learning what works for your home' : ''}</> : undefined}>
        {msg ? <p className={`notice notice-${msg.tone}`} role="status">{msg.text}</p> : null}
        {!a ? <Empty>Loading…</Empty> : a.items.length === 0 ? <Empty>No suggestions this week yet. They arrive at the start of each week.</Empty> : (
          <table className="actions-table">
            <thead>
              <tr><th scope="col">#</th><th scope="col">Suggestion</th><th scope="col" className="num">Saves a month</th><th scope="col" className="take-col">Take action</th></tr>
            </thead>
            <tbody>
              {a.items.map(i => (
                <tr key={i.action_id} className={i.viable ? '' : 'row-done'}>
                  <td className="rank">{i.rank}</td>
                  <td>
                    <div className="sentence">{i.sentence}</div>
                    <div className="small muted">{i.appliance_label}{i.narrated ? '' : ' · plain text, writer unavailable'}</div>
                  </td>
                  <td className="num">
                    <div className="money">{i.saving_month_display}</div>
                    <div className="small muted">{i.kg_month_display} kg CO₂</div>
                  </td>
                  <td className="take-col">
                    {i.viable ? (
                      <div className="btns">
                        <button className="btn btn-primary" disabled={!!busy} onClick={() => take(i.action_id)}>{busy === i.action_id ? '…' : 'Take action'}</button>
                        <button className="btn btn-quiet" disabled={!!busy} onClick={() => dismiss(i.action_id)}>Dismiss</button>
                      </div>
                    ) : <Chip tone={i.status === 'accepted' || i.status === 'verified' ? 'green' : 'neutral'}>{i.status_label}</Chip>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {sched ? (
        <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="sched-h">
          <div className="modal">
            <h2 id="sched-h">Install a precool schedule on the {sched.p.device_label}?</h2>
            <p>Normally {sched.p.current_display} °C. On {sched.p.days_label} through <strong>{sched.p.until_label}</strong>:</p>
            <ul className="schedule-lines">{sched.p.lines.map(l => <li key={l}><strong>{l}</strong></li>)}</ul>
            <p className="muted">The thermostat runs this itself and stops at the end of the week. Expected saving: {sched.p.saving_month_display} a month. You can undo for 24 hours.{sched.p.simulated ? ' This is the simulated thermostat.' : ''}</p>
            <div className="btns">
              <button className="btn btn-primary" onClick={confirmSchedule}>Install schedule</button>
              <button className="btn btn-quiet" onClick={() => setSched(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}

      {confirm ? (
        <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="confirm-h">
          <div className="modal">
            <h2 id="confirm-h">Change the {confirm.p.device_label}?</h2>
            <p>From <strong>{confirm.p.current_c} °C</strong> to <strong>{confirm.p.applied_c} °C</strong>.
              {confirm.p.clamped ? <> You asked for {confirm.p.requested_c} °C; your limits allow {confirm.p.applied_c} °C in one step.</> : null}</p>
            <p className="muted">Expected saving: {confirm.p.saving_month_display} a month. You can undo for 24 hours.{confirm.p.simulated ? ' This is the simulated thermostat.' : ''}</p>
            <div className="btns">
              <button className="btn btn-primary" onClick={confirmIt}>Confirm</button>
              <button className="btn btn-quiet" onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
