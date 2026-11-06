import { Link } from 'react-router-dom';
import { useData } from '../context';
import { Async, Card, Empty, OriginBadge, PageHeader, StatusBadge } from '../components/ui';
import { fmtTime } from '../format';

export default function Alerts() {
  const q = useData((a) => a.alerts());
  return (
    <>
      <PageHeader title="Pipeline alerts" sub="Stalled or at-risk deals, each with the reasons the detector fired and a recommended human action. Detection is rule-based; recommendations are AI-written (mock)." />
      <Async state={q} what="alerts" empty={(d) => (d.length ? null : <Empty title="No alerts">Nothing is stalled.</Empty>)}>
        {(alerts) => (
          <div className="stack">
            {alerts.map((a) => (
              <Card key={a.id} id={`alert-${a.id}`} title={<>{a.opportunity_name} <span className="muted">/ <Link to={`/accounts/${a.account_id}`}>{a.account_name}</Link></span></>}
                actions={<><StatusBadge status={a.severity} label={`${a.severity} severity`} /> <OriginBadge origin={a.data_origin} /></>}>
                <p className="muted">{a.kind.replace(/_/g, ' ')} / {a.days_stalled} days / raised {fmtTime(a.raised_at)}</p>
                <h3>Why this fired</h3>
                <ul>{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                <div className="callout info"><strong>Recommendation.</strong> {a.recommendation}</div>
              </Card>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}
