import { useState } from 'react';
import { useApp, useData } from '../context';
import { Async, BasisBadge, Card, Empty, OriginBadge, PageHeader, StatusBadge, BASIS_TEXT } from '../components/ui';
import type { EvalScenario, EvidenceBasis } from '../api/types';
import { fmtTime } from '../format';

const num = (v: number | string) => (typeof v === 'number' && !Number.isInteger(v) ? String(Math.round(v * 1000) / 1000) : String(v));

export const HONEST_STATEMENT =
  'Synthetic results are not real-world evidence. Everything below was measured on a generated world with a deterministic mock model and simulated providers. It shows that the machinery behaves as designed and how accurate it is on simulated data. It does not show that this system would improve conversion, revenue or lead quality for a real business.';

function Scenario({ s }: { s: EvalScenario }) {
  return (
    <Card id={`sc-${s.id}`} title={<><code>{s.id}</code> {s.title}</>} actions={<><StatusBadge status={s.passed ? 'passed' : 'failed'} label={s.passed ? 'pass' : 'fail'} /> <BasisBadge basis={s.evidence_basis} /></>}>
      <p>{s.description}</p>
      <p className="row-wrap"><span className="muted">Data origins:</span> {s.data_origins.map((o) => <OriginBadge key={o} origin={o} />)}</p>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Metrics for {s.id}</caption>
          <thead><tr><th>Metric</th><th>Value</th><th>Target</th><th>Result</th><th>Basis</th></tr></thead>
          <tbody>
            {s.metrics.slice(0, 5).map((m) => (
              <tr key={m.name}>
                <td data-label="Metric">{m.name}</td>
                <td data-label="Value"><strong>{num(m.value)}</strong> <span className="muted">{m.unit}</span></td>
                <td data-label="Target">{m.target == null ? '-' : num(m.target)}</td>
                <td data-label="Result">{m.passed == null ? <span className="muted">{m.evidence_basis === 'modelled_impact' ? 'n/a (illustrative)' : 'reported, no target'}</span> : <StatusBadge status={m.passed ? 'passed' : 'failed'} label={m.passed ? 'pass' : 'fail'} />}</td>
                <td data-label="Basis"><BasisBadge basis={m.evidence_basis} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s.metrics.length > 5 && (
        <details><summary>{s.metrics.length - 5} more metric(s)</summary>
          <ul className="plain">{s.metrics.slice(5).map((m) => <li key={m.name}><code>{m.name}</code> = <strong>{num(m.value)}</strong> <span className="muted">{m.unit}</span> <BasisBadge basis={m.evidence_basis} /></li>)}</ul>
        </details>
      )}
      {s.detail && <p className="muted">{s.detail}</p>}
    </Card>
  );
}

export default function Evaluation() {
  const { api, bump } = useApp();
  const q = useData((a) => a.evals());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function rerun() {
    setBusy(true); setErr(null);
    try { await api.runEvals(); bump(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHeader title="Evaluation" sub="Scenario results and system invariants.">
        <button type="button" className="btn" onClick={rerun} disabled={busy}>{busy ? 'Running...' : 'Re-run evaluation'}</button>
      </PageHeader>
      <div className="callout bad honest" role="note" data-testid="honest-statement">
        <strong>Read this first.</strong> {HONEST_STATEMENT}
      </div>
      {err && <p className="form-error" role="alert">{err}</p>}
      <Async state={q} what="evaluation results" empty={(d) => (d.totals.total === 0 ? <Empty title="No evaluation has been run yet">Press "Re-run evaluation" (it can take up to a minute against the real backend). {d.notice}</Empty> : null)}>
        {(d) => {
          const byBasis = (['measured_on_simulation', 'machinery_check', 'modelled_impact'] as EvidenceBasis[]).map((b) => [b, d.scenarios.filter((s) => s.evidence_basis === b)] as const);
          return (
            <>
              <Card title="Summary" id="sum">
                <p><StatusBadge status={d.totals.failed ? 'failed' : 'passed'} label={`${d.totals.passed} of ${d.totals.total} scenarios pass`} /> <span className="muted">{d.run_id != null && <>Run #{d.run_id} at </>}{d.run_id == null && 'At '} {fmtTime(d.ran_at)} / llm mode: <strong>{d.mode}</strong> / baseline compared: {d.baseline?.compared ? `yes (${d.baseline.regressions} regressions)` : 'no'}</span></p>
                <p className="muted">{d.notice}</p>
                <ul className="basis-key">
                  {byBasis.map(([b, list]) => (<li key={b}><BasisBadge basis={b} /> <strong>{list.length}</strong> scenario(s). {BASIS_TEXT[b][1]}</li>))}
                </ul>
                {api.mode === 'mock' && <p className="muted">Mock mode: these scenario results are static browser fixtures that illustrate the report layout. Connect the backend to see real results from <code>gtm.eval</code>.</p>}
              </Card>
              <Card title="System invariants" id="inv">
                <ul className="inv">
                  {d.invariants.map((i) => (<li key={i.name}><StatusBadge status={i.passed ? 'passed' : 'failed'} label={i.passed ? 'pass' : 'fail'} /> <code>{i.name}</code>{!i.passed && <span> {i.violations.length} violation(s)</span>}</li>))}
                </ul>
              </Card>
              <div className="stack">{d.scenarios.map((s) => <Scenario key={s.id} s={s} />)}</div>
            </>
          );
        }}
      </Async>
    </>
  );
}
