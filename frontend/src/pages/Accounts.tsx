import { Link, useParams } from 'react-router-dom';
import { useData } from '../context';
import { Async, Card, Conf, Empty, ErrorBox, FitBadge, Origins, OriginBadge, PageHeader, StatusBadge } from '../components/ui';
import type { ResolvedField } from '../api/types';
import { fmtDate, fmtTime, titleCase } from '../format';

/** The backend sometimes sends a stringified dict like "{'text': '...'}". Show the text only. */
export function questionText(x: unknown): string {
  if (x && typeof x === 'object') return String((x as { text?: unknown }).text ?? JSON.stringify(x));
  const s = String(x);
  const m = /^\{\s*['"]text['"]\s*:\s*['"](.*)['"]\s*\}$/.exec(s);
  return m ? m[1] : s;
}

export function AccountList() {
  const q = useData((a) => a.accounts());
  return (
    <>
      <PageHeader title="Accounts" sub="One persistent account agent per account. Open an account to see resolved fields with provenance and the agent's working state." />
      <Async state={q} what="accounts" empty={(d) => (d.length ? null : <Empty title="No accounts" />)}>
        {(rows) => (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Accounts</caption>
              <thead><tr><th>Account</th><th>Industry</th><th>Employees</th><th>Lifecycle</th><th>Fit</th><th>Owner</th><th>Open proposals</th><th>Last interaction</th><th>Origin</th></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td data-label="Account"><Link to={`/accounts/${a.id}`}><strong>{a.name}</strong></Link><br /><span className="muted">{a.domain}</span></td>
                    <td data-label="Industry">{a.industry ?? '-'}</td>
                    <td data-label="Employees">{a.employees?.toLocaleString('en-GB') ?? '-'}</td>
                    <td data-label="Lifecycle"><StatusBadge status={a.lifecycle} /></td>
                    <td data-label="Fit"><FitBadge band={a.fit_band} /></td>
                    <td data-label="Owner">{a.owner ?? '-'}</td>
                    <td data-label="Open proposals">{a.open_proposals > 0 ? <Link to="/approvals">{a.open_proposals}</Link> : 0}</td>
                    <td data-label="Last interaction">{fmtTime(a.last_interaction_at)}</td>
                    <td data-label="Origin"><Origins list={a.data_origins} /></td>
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

const OWNER_TEXT: Record<string, string> = { human: 'Human-owned: only changed via an approved proposal', provider: 'Resolved from provider observations', agent: 'Written by the account agent (ai_*)', system: 'System-managed' };

function FieldRow({ f }: { f: ResolvedField }) {
  const isAi = f.owner === 'agent' || f.key.startsWith('ai_');
  return (
    <tr className={isAi ? 'ai-row' : ''}>
      <th scope="row" data-label="Field">
        {f.label}
        {isAi && <> <span className="badge tone-ai" title={OWNER_TEXT.agent}>AI-written</span></>}
        {f.owner === 'human' && <> <span className="badge tone-muted" title={OWNER_TEXT.human}>human-owned</span></>}
        <br /><code className="muted">{f.key}</code>
      </th>
      <td data-label="Value">
        {f.value == null ? <span className="muted">not set</span> : typeof f.value === 'number' ? f.value.toLocaleString('en-GB') : f.value}
        {f.conflict && (
          <details className="conflict">
            <summary><span className="badge tone-warn"><span aria-hidden="true">{'⚠'}</span> conflict</span> {f.alternatives.length} other value(s)</summary>
            <ul className="plain">
              {f.alternatives.map((alt, i) => (
                <li key={i}>{typeof alt.value === 'number' ? alt.value.toLocaleString('en-GB') : alt.value} from {alt.source} (conf {alt.confidence.toFixed(2)}, {fmtDate(alt.as_of)})</li>
              ))}
              <li className="muted">Winner chosen by confidence then freshness; the disagreement is kept visible.</li>
            </ul>
          </details>
        )}
      </td>
      <td data-label="Source"><span className="chip" title={OWNER_TEXT[f.owner]}>{f.source}</span> <OriginBadge origin={f.data_origin} /></td>
      <td data-label="Confidence"><Conf value={f.confidence} /></td>
      <td data-label="Freshness"><span className={`badge fresh-${f.freshness}`}>{f.freshness}</span> <span className="muted">{f.freshness_days}d old</span></td>
    </tr>
  );
}

export function AccountPage() {
  const id = Number(useParams().id);
  const q = useData((a) => a.account(id), [id]);
  if (Number.isNaN(id)) return <ErrorBox error={new Error('Invalid account id')} />;
  return (
    <Async state={q} what="account">
      {(a) => {
        const st = a.agent_state;
        return (
          <>
            <PageHeader title={a.name} sub={<><Link to="/accounts">Accounts</Link> / account #{a.id} / {a.domain}</>}>
              <StatusBadge status={a.lifecycle} /> <FitBadge band={a.fit_band} /> <Origins list={a.data_origins} />
            </PageHeader>

            <Card title="Resolved fields and provenance" id="fields">
              <p className="sub">Each value shows where it came from, how confident the source is, how old it is, and whether providers disagree. Rows tagged AI-written are agent-owned and never overwrite human-owned fields.</p>
              <div className="table-wrap">
                <table className="fields">
                  <caption className="sr-only">Resolved account fields</caption>
                  <thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Confidence</th><th>Freshness</th></tr></thead>
                  <tbody>{a.fields.map((f) => <FieldRow key={f.key} f={f} />)}</tbody>
                </table>
              </div>
            </Card>

            {st ? (
              <Card title="Account agent state" id="agent" actions={<span className="muted">v{st.version} / updated {fmtTime(st.updated_at)} / model mode: <strong>{st.mode}</strong></span>}>
                <div className="ai-callout"><span className="badge tone-ai">AI-written</span> Everything in this card was written by the account agent using a <strong>deterministic mock model</strong>. Claims point to the records that support them.</div>
                <h3>Summary</h3>
                <p>{st.summary}</p>
                {st.summary_refs.length > 0 && <p className="muted">Evidence: {st.summary_refs.map((r) => <code key={r} className="ref">{r}</code>)}</p>}
                <div className="grid-2">
                  <div>
                    <h3>Stakeholders</h3>
                    {st.stakeholders.length === 0 ? <p className="muted">None known.</p> : (
                      <ul className="plain">{st.stakeholders.map((s) => (<li key={s.name}><strong>{s.name}</strong>, {s.role} <span className="badge tone-muted">{s.stance}</span> <code className="ref">{s.source_ref}</code></li>))}</ul>
                    )}
                    <h3>Open questions</h3>
                    {st.open_questions.length === 0 ? <p className="muted">None.</p> : <ul>{st.open_questions.map((x) => <li key={x}>{questionText(x)}</li>)}</ul>}
                  </div>
                  <div>
                    <h3>Risks</h3>
                    {st.risks.length === 0 ? <p className="muted">None flagged.</p> : (
                      <ul className="plain">{st.risks.map((r, i) => (<li key={i}><StatusBadge status={r.severity} label={r.severity} /> {r.text} {r.refs.map((x) => <code key={x} className="ref">{x}</code>)}</li>))}</ul>
                    )}
                    <h3>Commitments</h3>
                    {st.commitments.length === 0 ? <p className="muted">None recorded.</p> : (
                      <ul className="plain">{st.commitments.map((c, i) => (<li key={i}><strong>{c.party}:</strong> {c.text} {c.due && <span className="muted">(due {c.due})</span>} <span className="badge tone-muted">{c.status}</span></li>))}</ul>
                    )}
                  </div>
                </div>
                <h3>Next actions</h3>
                {st.next_actions.length === 0 ? <p className="muted">No actions. "No action" is the expected result most of the time.</p> : (
                  <ul className="plain">
                    {st.next_actions.map((n) => (
                      <li key={n.id}><code>{n.action}</code> {n.text || (n.proposal_id ? `see proposal #${n.proposal_id}` : '')} <span className="badge tone-muted">{n.status.replace(/_/g, ' ')}</span>{' '}
                        {n.proposal_id && <Link to={`/approvals/${n.proposal_id}`}>proposal #{n.proposal_id}</Link>}
                        {n.rationale && <span className="muted"> ({n.rationale})</span>}</li>
                    ))}
                  </ul>
                )}
                {st.last_decision && <p className="muted">Last decision: <code>{st.last_decision.action}</code>, confidence {st.last_decision.confidence.toFixed(2)}. Would change its mind if: {st.last_decision.would_change_mind}</p>}
              </Card>
            ) : <Empty title="No agent state yet">The account agent has not been provisioned.</Empty>}

            <div className="grid-2">
              <Card title="Interaction timeline" id="timeline">
                {a.interactions.length === 0 ? <p className="muted">No interactions.</p> : (
                  <ol className="timeline">
                    {a.interactions.map((i) => (
                      <li key={i.id}>
                        <span className="tl-time">{fmtTime(i.at)}</span>
                        <span className="tl-body"><span className="badge tone-muted">{titleCase(i.kind)}</span> {i.summary} <OriginBadge origin={i.data_origin} />
                          {i.detail && <details><summary>Show detail</summary><p className="quote">{i.detail}</p></details>}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </Card>
              <div>
                <Card title="Related proposals" id="props">
                  {a.proposals.length === 0 ? <p className="muted">None.</p> : (
                    <ul className="plain">
                      {[...a.proposals].sort((x, y) => x.id - y.id).map((p) => (
                        <li key={p.id}><Link to={`/approvals/${p.id}`}>#{p.id} {titleCase(p.type)}</Link> <StatusBadge status={p.status} />{p.depends_on && <span className="muted"> after #{p.depends_on}</span>}</li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card title="Opportunities" id="opps">
                  {a.opportunities.length === 0 ? <p className="muted">None yet.</p> : (
                    <ul className="plain">{a.opportunities.map((o) => (<li key={o.id}><strong>{o.name}</strong> <span className="badge tone-muted">{o.stage}</span> {o.amount != null ? `${o.currency} ${o.amount.toLocaleString('en-GB')}` : <span className="muted">amount not set (human-owned)</span>}</li>))}</ul>
                  )}
                </Card>
              </div>
            </div>
          </>
        );
      }}
    </Async>
  );
}
