import { useState } from 'react';
import { useApp, useData } from '../context';
import { Card, PageHeader } from '../components/ui';
import type { DemoResultOut } from '../api/types';
import { fmtTime } from '../format';

const ADVANCES: [string, number][] = [['+1 hour', 3600], ['+1 day', 86400], ['+3 days', 3 * 86400], ['+7 days', 7 * 86400]];

export default function Demo() {
  const { api, bump } = useApp();
  const health = useData((a) => a.health());
  const ov = useData((a) => a.overview());
  const [log, setLog] = useState<{ label: string; r: DemoResultOut }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run(label: string, fn: () => Promise<DemoResultOut>) {
    setBusy(label); setErr(null);
    try { const r = await fn(); setLog((l) => [{ label, r }, ...l].slice(0, 8)); bump(); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }
  const next = ov.data?.golden_thread.find((s) => !s.done);
  const hints: Record<string, string> = {
    enquiry: 'Press "Submit scripted enquiry".', triage: 'Press "Submit scripted enquiry".', account: 'Press "Submit scripted enquiry".', agent: 'Press "Submit scripted enquiry".',
    crm: 'Open Approvals and approve the CRM-create proposal first.', send: 'Approve the intro reply (it unblocks once the CRM proposal executes; it may park until you advance time). You can try Edit and approve with a price in the text to see the gateway block it.',
    reply: 'Press "Deliver scripted customer reply".', intel: 'Open the account page to see the updated intelligence.',
  };
  const Btn = ({ label, onClick, kind = '' }: { label: string; onClick: () => void; kind?: string }) => (
    <button type="button" className={`btn ${kind}`} onClick={onClick} disabled={busy !== null}>{busy === label ? 'Working...' : label}</button>
  );
  return (
    <>
      <PageHeader title="Demo control" sub="Drive the golden-thread story. Everything is scripted and simulated; time only moves when you move it." />
      <Card title="Simulated clock" id="clock">
        <p className="bigclock"><time dateTime={health.data?.clock}>{health.data ? fmtTime(health.data.clock) : '...'}</time></p>
        <p className="muted">The simulator and the audit log use this clock, not wall-clock time.</p>
        {next && <p className="callout info"><strong>Next step:</strong> {next.label}. {hints[next.key]}</p>}
        {ov.data && !next && <p className="callout ok"><strong>Golden thread complete.</strong> Explore Accounts, Audit and Runs, or reset to replay.</p>}
      </Card>
      <div className="grid-2">
        <Card title="1. Inbound" id="step1">
          <p>Submit the scripted website enquiry from a fictional freight operator. Creates a lead, an enriched account and two linked proposals (CRM create, then intro reply).</p>
          <Btn label="Submit scripted enquiry" kind="primary" onClick={() => run('Submit scripted enquiry', () => api.demoEnquiry())} />
        </Card>
        <Card title="2. Customer reply" id="step2">
          <p>Deliver the scripted customer reply (available once the intro reply has been approved and sent). The account agent wakes and updates its state.</p>
          <Btn label="Deliver scripted customer reply" kind="primary" onClick={() => run('Deliver scripted customer reply', () => api.demoReply())} />
        </Card>
        <Card title="Advance simulated time" id="time">
          <p>Proposals expire, parked runs resume and stall detectors run as simulated time passes.</p>
          <div className="row-wrap">{ADVANCES.map(([l, s]) => <Btn key={l} label={`Advance ${l}`} onClick={() => run(`Advance ${l}`, () => api.demoAdvance(s))} />)}</div>
        </Card>
        <Card title="Reset" id="reset">
          <p>{api.mode === 'mock' ? 'Restore the browser fixtures to their seed state.' : 'Reset the backend database to the seeded world.'} This discards all demo progress.</p>
          <Btn label="Reset demo" kind="danger" onClick={() => run('Reset demo', () => api.demoReset())} />
        </Card>
      </div>
      {err && <p className="form-error" role="alert">{err}</p>}
      <Card title="Results" id="log">
        {log.length === 0 ? <p className="muted">Actions you take appear here.</p> : (
          <ul className="plain" aria-live="polite">
            {log.map((l, i) => (<li key={i}><strong>{l.label}</strong> <span className={l.r.ok ? 'ok-text' : 'bad-text'}>{l.r.ok ? '✓ ok' : '✕ not done'}</span>. {l.r.message}</li>))}
          </ul>
        )}
      </Card>
    </>
  );
}
