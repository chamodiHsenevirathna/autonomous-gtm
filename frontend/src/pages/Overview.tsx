import { Link } from 'react-router-dom';
import { useData } from '../context';
import { Async, Card, OriginBadge, PageHeader, BasisBadge, ORIGIN_TEXT } from '../components/ui';
import type { DataOrigin } from '../api/types';
import { fmtTime } from '../format';

const ORIGINS = Object.keys(ORIGIN_TEXT) as DataOrigin[];

export default function Overview() {
  const ov = useData((a) => a.overview());
  return (
    <>
      <PageHeader title="Overview" sub="An AI-assisted go-to-market system for a fictional consultancy. Agents propose; humans approve; a gateway executes; everything is audited." />
      <Async state={ov} what="overview">
        {(d) => {
          const k = d.counts;
          const tiles: [string, number, string][] = [
            ['Leads', k.leads, '/leads'], ['Accounts', k.accounts, '/accounts'], ['Open proposals', k.open_proposals, '/approvals'],
            ['Workflow runs', k.runs, '/runs'], ['Pipeline alerts', k.alerts, '/alerts'], ['Audit events', k.audit_events, '/audit'],
          ];
          const doneN = d.golden_thread.filter((s) => s.done).length;
          return (
            <>
              <ul className="kpis" aria-label="Key figures">
                {tiles.map(([label, n, to]) => (
                  <li key={label}><Link to={to} className="kpi"><span className="kpi-n">{n}</span><span className="kpi-l">{label}</span></Link></li>
                ))}
              </ul>

              <Card title="Golden thread" id="gt" actions={<span className="muted">{doneN} of {d.golden_thread.length} steps complete</span>}>
                <p className="sub">One scripted enquiry followed end to end. Go to <Link to="/demo">Demo control</Link> to drive it.</p>
                <ol className="thread">
                  {d.golden_thread.map((s, i) => (
                    <li key={s.key} className={s.done ? 'done' : ''}>
                      <span className="thread-dot" aria-hidden="true">{s.done ? '✓' : i + 1}</span>
                      <span className="thread-label">{s.label}<span className="sr-only">{s.done ? ' (done)' : ' (not yet)'}</span></span>
                      {s.detail && <span className="thread-detail">{s.detail}</span>}
                    </li>
                  ))}
                </ol>
              </Card>

              <div className="grid-2">
                <Card title="Data-origin legend" id="legend">
                  <p className="sub">Every record carries an origin label. Nothing on this site is production data.</p>
                  <dl className="legend">
                    {ORIGINS.map((o) => (<div key={o}><dt><OriginBadge origin={o} /></dt><dd>{ORIGIN_TEXT[o]}</dd></div>))}
                  </dl>
                  <p className="sub">Evaluation metrics also carry an evidence basis:</p>
                  <p className="row-wrap"><BasisBadge basis="measured_on_simulation" /> <BasisBadge basis="machinery_check" /> <BasisBadge basis="modelled_impact" /></p>
                </Card>
                <Card title="Recent activity" id="recent">
                  {d.recent_activity.length === 0 ? <p className="muted">No activity yet.</p> : (
                    <ul className="plain">
                      {d.recent_activity.map((r, i) => (<li key={i}><span className="muted">{fmtTime(r.at)}</span> {r.text}{r.ref && <> <code>{r.ref}</code></>}</li>))}
                    </ul>
                  )}
                  <p><Link to="/audit">Open the audit log</Link></p>
                </Card>
              </div>
            </>
          );
        }}
      </Async>
    </>
  );
}
