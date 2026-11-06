import { Link } from 'react-router-dom';
import { useData } from '../context';
import { Async, Empty, FitBadge, Origins, PageHeader, StatusBadge } from '../components/ui';
import { fmtTime, titleCase } from '../format';

export default function Leads() {
  const q = useData((a) => a.leads());
  return (
    <>
      <PageHeader title="Leads" sub="Inbound enquiries, triaged and scored. Suspected vendors, recruiters and spam are held (reversible), never deleted." />
      <Async state={q} what="leads" empty={(d) => (d.length ? null : <Empty title="No leads yet">Submit the scripted enquiry from Demo control.</Empty>)}>
        {(leads) => (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Inbound leads</caption>
              <thead><tr><th>Received</th><th>From</th><th>Triage</th><th>Fit</th><th>Status</th><th>Account</th><th>Origin</th></tr></thead>
              <tbody>
                {leads.map((l) => (
                  <tr key={l.id}>
                    <td data-label="Received">{fmtTime(l.received_at)}</td>
                    <td data-label="From">
                      <strong>{l.name}</strong><br /><span className="muted">{l.company ?? l.email}</span>
                      <p className="excerpt">{l.message}</p>
                    </td>
                    <td data-label="Triage">{l.triage_class ? titleCase(l.triage_class) : '-'}{l.service_line && <><br /><span className="muted">{l.service_line}</span></>}</td>
                    <td data-label="Fit"><FitBadge band={l.fit_band} score={l.fit_score} /></td>
                    <td data-label="Status">
                      <StatusBadge status={l.status} />
                      {l.held && <p className="held-note"><strong>Held:</strong> {l.held_reason ?? 'held for review'}</p>}
                    </td>
                    <td data-label="Account">{l.account_id ? <Link to={`/accounts/${l.account_id}`}>Account #{l.account_id}</Link> : <span className="muted">none</span>}</td>
                    <td data-label="Origin"><Origins list={l.data_origins} /></td>
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
