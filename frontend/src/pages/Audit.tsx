import { useState } from 'react';
import { useApp, useData } from '../context';
import { Async, Card, Empty, Hash, PageHeader } from '../components/ui';
import type { AuditVerifyOut } from '../api/types';
import { fmtTime } from '../format';

export function VerifyPanel() {
  const { api, bump } = useApp();
  const [res, setRes] = useState<AuditVerifyOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function verify() {
    setBusy(true); setErr(null);
    try { setRes(await api.verifyAudit()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <Card title="Chain verification" id="verify">
      <p className="sub">Each row hashes its content together with the previous row's hash. Editing or deleting any row breaks every hash after it.</p>
      <div className="row-wrap">
        <button type="button" className="btn primary" onClick={verify} disabled={busy}>{busy ? 'Verifying...' : 'Verify chain'}</button>
        {api.mockTamper && (
          <button type="button" className="btn" onClick={async () => { await api.mockTamper?.(); setRes(null); bump(); }}>
            Tamper with one row (mock demo only)
          </button>
        )}
      </div>
      <div aria-live="polite" className="verify-out">
        {err && <p className="callout bad" role="alert">{err}</p>}
        {res && res.ok && <p className="callout ok" data-testid="verify-ok"><strong>{'✓'} Chain OK.</strong> {res.checked} rows checked, every hash and link matches.</p>}
        {res && !res.ok && <p className="callout bad" data-testid="verify-broken"><strong>{'✕'} Chain BROKEN</strong> at sequence {res.first_bad_seq}. {res.checked} rows verified before the break. The record has been altered after it was written.</p>}
      </div>
    </Card>
  );
}

export default function Audit() {
  const q = useData((a) => a.audit(200));
  const ev = useData((a) => a.events(30));
  return (
    <>
      <PageHeader title="Audit log" sub="Append-only, hash-chained record of every proposal, decision, execution and agent write." />
      <VerifyPanel />
      <Card title="Audit events" id="events">
        <Async state={q} what="audit events" empty={(d) => (d.length ? null : <Empty title="No audit events" />)}>
          {(rows) => (
            <div className="table-wrap">
              <table className="audit">
                <caption className="sr-only">Audit events, newest first</caption>
                <thead><tr><th>Seq</th><th>Time</th><th>Actor</th><th>Event</th><th>Entity</th><th>Hash</th><th>Prev hash</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.seq}>
                      <td data-label="Seq">{r.seq}</td>
                      <td data-label="Time">{fmtTime(r.at)}</td>
                      <td data-label="Actor"><code>{r.actor_id}</code></td>
                      <td data-label="Event"><strong>{r.event_type}</strong>
                        {Object.keys(r.data).length > 0 && <details><summary>data</summary><pre className="json">{JSON.stringify(r.data, null, 2)}</pre></details>}</td>
                      <td data-label="Entity">{r.entity_ref ? <code>{r.entity_ref}</code> : '-'}</td>
                      <td data-label="Hash"><Hash value={r.hash} /></td>
                      <td data-label="Prev hash"><Hash value={r.prev_hash} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Card>
      <Card title="Recent domain events" id="domain-events">
        <Async state={ev} what="events" empty={(d) => (d.length ? null : <Empty title="No events" />)}>
          {(rows) => (
            <ul className="plain">{rows.map((e) => <li key={e.id}><span className="muted">{fmtTime(e.at)}</span> <strong>{e.event_type}</strong> {e.entity_ref && <code>{e.entity_ref}</code>} <span className="muted">via {e.source}</span></li>)}</ul>
          )}
        </Async>
      </Card>
    </>
  );
}
