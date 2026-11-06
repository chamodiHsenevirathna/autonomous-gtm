import { Link, useParams } from 'react-router-dom';
import { useData } from '../context';
import { Async, Card, Empty, PageHeader, StatusBadge } from '../components/ui';
import { fmtTime } from '../format';

export function RunList() {
  const q = useData((a) => a.runs());
  return (
    <>
      <PageHeader title="Workflow runs" sub="Each run is a graph of typed nodes (code, tool, llm, agent, wait, approval). Open a run to see the step-by-step trace." />
      <Async state={q} what="runs" empty={(d) => (d.length ? null : <Empty title="No runs yet" />)}>
        {(runs) => (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Workflow runs</caption>
              <thead><tr><th>Run</th><th>Workflow</th><th>Status</th><th>Trigger</th><th>Account</th><th>Progress</th><th>Started</th><th>Model cost</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td data-label="Run"><Link to={`/runs/${r.id}`}>#{r.id}</Link></td>
                    <td data-label="Workflow"><strong>{r.workflow}</strong></td>
                    <td data-label="Status"><StatusBadge status={r.status} /></td>
                    <td data-label="Trigger"><code>{r.trigger}</code></td>
                    <td data-label="Account">{r.account_id ? <Link to={`/accounts/${r.account_id}`}>{r.account_name}</Link> : '-'}</td>
                    <td data-label="Progress">{r.steps_done}/{r.steps_total} steps</td>
                    <td data-label="Started">{fmtTime(r.started_at)}</td>
                    <td data-label="Model cost">${r.cost_usd.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </>
  );
}

export function RunPage() {
  const id = Number(useParams().id);
  const q = useData((a) => a.run(id), [id]);
  return (
    <Async state={q} what="run">
      {(r) => (
        <>
          <PageHeader title={`Run #${r.id}: ${r.workflow}`} sub={<><Link to="/runs">Runs</Link> / trigger <code>{r.trigger}</code>{r.account_id && <> / <Link to={`/accounts/${r.account_id}`}>{r.account_name}</Link></>}</>}>
            <StatusBadge status={r.status} />
          </PageHeader>
          <Card title="Step trace" id="trace" actions={<span className="muted">Model cost ${r.cost_usd.toFixed(2)} (mock model: no spend). Provider cost is in simulated units, not money.</span>}>
            <ol className="trace">
              {r.steps.map((s) => (
                <li key={s.id} className={`step step-${s.status}`}>
                  <div className="step-head">
                    <span className="step-n">{s.seq}</span>
                    <strong>{s.node}</strong>
                    <span className="badge tone-muted">{s.node_type}</span>
                    <StatusBadge status={s.status} />
                    <span className="muted">attempts: {s.attempts}</span>
                    {s.model_mode && <span className="badge tone-ai">model: {s.model_mode}</span>}
                  </div>
                  <div className="step-body">
                    <span className="muted">{s.started_at ? fmtTime(s.started_at) : 'not started'}{s.finished_at && ` to ${fmtTime(s.finished_at)}`}</span>
                    {s.sim_units > 0 && <span className="muted"> / {s.sim_units} simulated provider units</span>}
                    {s.cost_usd > 0 && <span className="muted"> / ${s.cost_usd.toFixed(4)}</span>}
                    {s.note && <p>{s.note}</p>}
                    {s.waiting_for && s.status === 'waiting' && <p className="callout info"><strong>Waiting for</strong> <code>{s.waiting_for}</code>{s.waiting_for.startsWith('approval:') && <> / <Link to={`/approvals/${s.waiting_for.split(':')[1]}`}>open proposal</Link></>}</p>}
                    {s.parked_until && <p className="callout warn"><strong>Parked</strong> until {fmtTime(s.parked_until)} (retry-after respected; advance simulated time to resume).</p>}
                    {s.error && <p className="callout bad"><strong>{s.error.class}:</strong> {s.error.message}</p>}
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        </>
      )}
    </Async>
  );
}
