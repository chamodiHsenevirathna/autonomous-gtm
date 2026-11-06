import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useApp, useData } from '../context';
import { Async, Card, Conf, Empty, Hash, Origins, PageHeader, StatusBadge } from '../components/ui';
import type { DecisionKind, DecisionRecord, ExecutionOut, ProposalOut } from '../api/types';
import { fmtTime, titleCase } from '../format';
import { lineDiff, payloadLines } from '../diff';

/** Fallback for backends that do not return `old_payload`: remember the pre-edit payload in this browser session. */
const editCache = new Map<string, Record<string, unknown>>();

export const DECIDER = 'user:maya';
const REJECT_REASONS: [string, string][] = [
  ['wrong_recipient', 'Wrong recipient'], ['inaccurate_claim', 'Inaccurate or unsupported claim'], ['tone', 'Tone or wording'],
  ['not_ready', 'Not ready / wrong timing'], ['duplicate', 'Duplicate of other work'], ['policy', 'Policy or compliance concern'], ['other', 'Other'],
];
const EDIT_REASONS: [string, string][] = [['fact_fix', 'Fixed a fact'], ['tone_edit', 'Tone or wording'], ['removed_claim', 'Removed a claim'], ['other', 'Other']];

const OPEN = new Set(['pending', 'blocked', 'parked']);
const isDecidable = (p: ProposalOut) => p.status === 'pending' || (p.status === 'blocked' && p.execution?.block_kind === 'soft');

export default function Approvals() {
  const params = useParams();
  const nav = useNavigate();
  const [filter, setFilter] = useState<'open' | 'all'>('open');
  const list = useData((a) => a.proposals(), []);
  const selectedId = params.id ? Number(params.id) : null;

  useEffect(() => {
    if (selectedId == null && list.data) {
      const first = list.data.find((p) => OPEN.has(p.status)) ?? list.data[0];
      if (first) nav(`/approvals/${first.id}`, { replace: true });
    }
  }, [selectedId, list.data, nav]);

  return (
    <>
      <PageHeader title="Approvals" sub="Nothing leaves the system until a human approves the exact payload shown here. The approval is bound to the payload hash and consumed once." />
      <div className="split">
        <Card title="Queue" id="queue" className="queue-card" actions={
          <div role="group" aria-label="Filter queue" className="seg">
            <button type="button" aria-pressed={filter === 'open'} onClick={() => setFilter('open')}>Open</button>
            <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All</button>
          </div>}>
          <Async state={list} what="proposals">
            {(all) => {
              const shown = all.filter((p) => filter === 'all' || OPEN.has(p.status));
              if (shown.length === 0) return <Empty title="Queue is empty">{filter === 'open' ? 'No open proposals. Submit the enquiry from Demo control.' : 'No proposals.'}</Empty>;
              return (
                <ul className="queue">
                  {shown.map((p) => (
                    <li key={p.id}>
                      <Link to={`/approvals/${p.id}`} className={p.id === selectedId ? 'sel' : ''} aria-current={p.id === selectedId ? 'true' : undefined}>
                        <span className="q-title">#{p.id} {titleCase(p.type)} <span className="muted">({p.gate_id})</span></span>
                        <span className="q-sub">{p.account_name ?? 'no account'}</span>
                        <span className="q-status"><StatusBadge status={p.status} />{p.depends_on && <span className="muted"> needs #{p.depends_on}</span>}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              );
            }}
          </Async>
        </Card>
        <div className="detail">
          {selectedId == null ? <Empty title="Select a proposal" /> : <ProposalDetail key={selectedId} id={selectedId} />}
        </div>
      </div>
    </>
  );
}

export function ProposalDetail({ id }: { id: number }) {
  const q = useData((a) => a.proposal(id), [id]);
  return (
    <Async state={q} what="proposal">
      {(p) => <ProposalView p={p} reload={q.reload} />}
    </Async>
  );
}

function ProposalView({ p, reload }: { p: ProposalOut; reload: () => void }) {
  const dep = useData((a) => (p.depends_on ? a.proposal(p.depends_on) : Promise.resolve(null)), [p.depends_on, p.status]);
  return (
    <>
      <Card id="prop" title={<>Proposal #{p.id}: {titleCase(p.type)}</>} actions={<StatusBadge status={p.status} />}>
        <dl className="meta">
          <div><dt>Gate</dt><dd>{p.gate_id}</dd></div>
          <div><dt>Account</dt><dd>{p.account_id ? <Link to={`/accounts/${p.account_id}`}>{p.account_name ?? `#${p.account_id}`}</Link> : '-'}</dd></div>
          <div><dt>Required role</dt><dd>{p.required_role ?? '-'}</dd></div>
          <div><dt>Created</dt><dd>{fmtTime(p.created_at)}</dd></div>
          <div><dt>Expires</dt><dd>{fmtTime(p.expires_at)}</dd></div>
          <div><dt>Agent confidence</dt><dd>{p.confidence != null ? <Conf value={p.confidence} /> : '-'}</dd></div>
          <div><dt>Origin</dt><dd><Origins list={p.data_origins} /></dd></div>
        </dl>
        {p.rationale && <p><strong>Why:</strong> {p.rationale} <span className="muted">(AI-written, mock model)</span></p>}
        {p.depends_on && (
          <div className={`callout ${p.status === 'blocked' && p.block_reason ? 'warn' : 'info'}`} role="note">
            <strong>Linked proposal.</strong> This depends on <Link to={`/approvals/${p.depends_on}`}>#{p.depends_on}</Link>
            {dep.data && <> (currently <StatusBadge status={dep.data.status} />)</>}.
            {p.block_reason && <> {p.block_reason}</>}
          </div>
        )}
        {p.status === 'superseded' && p.block_reason && <div className="callout warn" role="note">{p.block_reason}</div>}
      </Card>

      <Card id="payload" title="Exact payload to be executed">
        <PayloadView p={p} />
        <div className="hashbox">
          <div><strong>Payload hash (SHA-256)</strong></div>
          <div className="hash-full"><Hash value={p.payload_hash} n={64} /></div>
          <p className="muted">Covers proposal id, type, the full payload (recipient, sender, subject, body, links, claims) and the screen-policy version. The gateway recomputes it at execution; any change after approval blocks the send.</p>
        </div>
      </Card>

      <Card id="evidence" title="Evidence">
        {p.evidence.length === 0 ? <p className="muted">No evidence attached.</p> : (
          <ul className="evidence">
            {p.evidence.map((e, i) => (
              <li key={i}><span className="badge tone-muted">{titleCase(e.kind)}</span> {e.text || <span className="muted">(no excerpt; see reference)</span>}<br />
                <code className="ref">{e.ref}</code>{e.source && <span className="muted"> via {e.source}</span>} {e.data_origin && <Origins list={[e.data_origin]} />}</li>
            ))}
          </ul>
        )}
      </Card>

      {isDecidable(p) ? <DecisionForm p={p} onDone={reload} /> : null}

      {p.decisions.length > 0 && (
        <Card id="history" title="Decision record">
          <ul className="plain">
            {p.decisions.map((d, i) => (
              <li key={i}>
                <strong>{d.decision.replace(/_/g, ' ')}</strong> by <code>{d.decided_by}</code> at {fmtTime(d.at)}
                {d.reason_code && <> / reason: <code>{d.reason_code}</code></>}
                {d.comment && <p className="quote">{d.comment}</p>}
                {d.edited && <EditDiff d={d} current={p.payload} cached={editCache.get(`${p.id}:${i}`)} />}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {p.execution && <ExecutionView ex={p.execution} />}
    </>
  );
}

function PayloadView({ p }: { p: ProposalOut }) {
  const pl = p.payload;
  if (p.type === 'message') {
    return (
      <div className="email" aria-label="Email preview">
        <dl className="email-head">
          <div><dt>To</dt><dd><strong>{pl.resolved_recipient}</strong> <span className="muted">(contact #{pl.contact_id}, resolved at proposal time)</span></dd></div>
          <div><dt>From</dt><dd>{pl.sender_identity}</dd></div>
          <div><dt>Channel</dt><dd>{pl.channel}{pl.thread_id && <span className="muted"> / thread {pl.thread_id}</span>}</dd></div>
          <div><dt>Subject</dt><dd><strong>{pl.subject}</strong></dd></div>
        </dl>
        <pre className="email-body">{pl.body}</pre>
        <h3>Claims and sources</h3>
        {(pl.claims ?? []).length === 0 ? <p className="muted">No factual claims.</p> : (
          <ul className="claims">
            {(pl.claims as { text: string; source_ref: string | null }[]).map((c, i) => (
              <li key={i}>{c.text} {c.source_ref ? <code className="ref">{c.source_ref}</code> : <span className="badge tone-bad"><span aria-hidden="true">!</span> unsupported claim</span>}</li>
            ))}
          </ul>
        )}
        <p className="muted">Links: {(pl.links ?? []).length ? pl.links.join(', ') : 'none'} / Attachments: {(pl.attachments ?? []).length ? pl.attachments.join(', ') : 'none'}</p>
      </div>
    );
  }
  if (p.type === 'crm_write') {
    const ops = (pl.operations ?? []) as { object: string; action: string; local_ref: { type: string; id: number }; properties: Record<string, unknown> }[];
    return (
      <div className="table-wrap">
        <table>
          <caption className="sr-only">CRM operations</caption>
          <thead><tr><th>Operation</th><th>Local ref</th><th>Properties</th></tr></thead>
          <tbody>
            {ops.map((o, i) => (
              <tr key={i}>
                <td data-label="Operation"><strong>{o.action} {o.object}</strong></td>
                <td data-label="Local ref"><code>{o.local_ref.type}:{o.local_ref.id}</code></td>
                <td data-label="Properties"><dl className="props">{Object.entries(o.properties).map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>))}</dl></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <dl className="props">
      {Object.entries(pl).map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{typeof v === 'object' ? JSON.stringify(v) : String(v ?? '-')}</dd></div>))}
    </dl>
  );
}

function DecisionForm({ p, onDone }: { p: ProposalOut; onDone: () => void }) {
  const { api, bump } = useApp();
  const [mode, setMode] = useState<DecisionKind>('approve');
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [subject, setSubject] = useState(String(p.payload.subject ?? ''));
  const [body, setBody] = useState(String(p.payload.body ?? ''));
  const [json, setJson] = useState(JSON.stringify(p.payload, null, 2));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isMsg = p.type === 'message';
  const reasons = mode === 'reject' ? REJECT_REASONS : EDIT_REASONS;
  const needReason = mode === 'reject';

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    if (needReason && !reason) { setErr('Choose a reason code to reject.'); return; }
    let edited: Record<string, unknown> | null = null;
    if (mode === 'approve_with_edits') {
      if (isMsg) edited = { ...p.payload, subject, body };
      else {
        try { edited = JSON.parse(json); } catch { setErr('Edited payload is not valid JSON.'); return; }
      }
    }
    setBusy(true);
    try {
      if (edited) editCache.set(`${p.id}:${p.decisions.length}`, p.payload);
      await api.decide(p.id, { decision: mode, decided_by: DECIDER, edited_payload: edited, reason_code: reason || null, comment: comment || null });
      bump(); onDone();
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card id="decide" title="Your decision">
      {p.status === 'blocked' && p.execution && (
        <div className="callout warn" role="alert"><strong>Execution was blocked at the gateway.</strong> {p.execution.outcome} You can edit and re-approve (new hash) or reject.</div>
      )}
      <form onSubmit={submit} aria-describedby="decide-help">
        <p id="decide-help" className="muted">Deciding as <code>{DECIDER}</code> (simulated reviewer identity). Approve sends the payload above exactly as shown.</p>
        <fieldset>
          <legend>Decision</legend>
          <div className="radios">
            <label><input type="radio" name="decision" value="approve" checked={mode === 'approve'} onChange={() => setMode('approve')} /> Approve</label>
            <label><input type="radio" name="decision" value="approve_with_edits" checked={mode === 'approve_with_edits'} onChange={() => setMode('approve_with_edits')} /> Edit and approve</label>
            <label><input type="radio" name="decision" value="reject" checked={mode === 'reject'} onChange={() => setMode('reject')} /> Reject</label>
          </div>
        </fieldset>

        {mode === 'approve_with_edits' && (
          <div className="edit-box">
            <p className="muted">Editing creates a new payload hash. Content screens re-run at the gateway on the final hash (a price or discount in the text will block execution).</p>
            {isMsg ? (
              <>
                <label className="field">Subject<input value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
                <label className="field">Body<textarea rows={9} value={body} onChange={(e) => setBody(e.target.value)} /></label>
              </>
            ) : (
              <label className="field">Payload (JSON)<textarea rows={10} className="mono" value={json} onChange={(e) => setJson(e.target.value)} /></label>
            )}
          </div>
        )}

        {mode !== 'approve' && (
          <label className="field"><span>Reason code {needReason ? <span className="req">(required)</span> : <span className="muted">(optional)</span>}</span>
            <select value={reason} onChange={(e) => setReason(e.target.value)} required={needReason}>
              <option value="">Select a reason...</option>
              {reasons.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        )}
        <label className="field"><span>Comment <span className="muted">(optional; kept as feedback)</span></span>
          <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why this decision?" />
        </label>
        {err && (/content screen|price|commercial/i.test(err)
          ? <div className="callout bad" role="alert"><strong>Blocked by the commercial-content screen.</strong> Nothing was approved or sent. {err} Remove the price, fee or discount wording and try again.</div>
          : <p className="form-error" role="alert">{err}</p>)}
        <div className="row-wrap">
          <button type="submit" className={`btn ${mode === 'reject' ? 'danger' : 'primary'}`} disabled={busy}>
            {busy ? 'Submitting...' : mode === 'approve' ? 'Approve' : mode === 'reject' ? 'Reject' : 'Edit and approve'}
          </button>
        </div>
      </form>
    </Card>
  );
}

function EditDiff({ d, current, cached }: { d: DecisionRecord; current: Record<string, unknown>; cached?: Record<string, unknown> }) {
  const before = d.old_payload ?? cached;
  const lines = before ? lineDiff(payloadLines(before), payloadLines(current)) : null;
  return (
    <div className="diff" data-testid="edit-diff">
      <p><strong>Reviewer edit.</strong> The approval binds to the new hash.</p>
      <div className="hash-compare">
        <div><span className="muted">Original hash</span><br /><code>{d.old_hash ?? 'unknown'}</code></div>
        <div><span className="muted">Edited hash</span><br /><code>{d.new_hash ?? 'unknown'}</code></div>
      </div>
      {lines ? (
        <pre className="difflines" aria-label="Payload diff, original versus edited">
          {lines.map((l, i) => (
            <span key={i} className={`dl dl-${l.kind}`}><span aria-hidden="true">{l.kind === 'add' ? '+ ' : l.kind === 'del' ? '- ' : '  '}</span><span className="sr-only">{l.kind === 'add' ? 'added: ' : l.kind === 'del' ? 'removed: ' : ''}</span>{l.text}</span>
          ))}
        </pre>
      ) : <p className="muted">The backend did not return the original payload, so no text diff is available.</p>}
    </div>
  );
}

export function ExecutionView({ ex }: { ex: ExecutionOut }) {
  return (
    <Card id="exec" title="Gateway and execution outcome" actions={<StatusBadge status={ex.status} />}>
      <div className={`callout ${ex.status === 'executed' ? 'ok' : 'warn'}`} role="status">{ex.outcome}</div>
      {ex.status === 'parked' && <div className="callout info"><strong>Parked, not failed.</strong> The gateway is waiting for a precondition (for example the CRM contact becoming visible). The approval is not consumed yet. Advance simulated time from Demo control and it will retry.</div>}
      <dl className="meta">
        <div><dt>Adapter</dt><dd><code>{ex.adapter}</code> <span className="muted">(simulator)</span></dd></div>
        <div><dt>Idempotency key</dt><dd><code>{ex.idempotency_key}</code></dd></div>
        <div><dt>Hash verified</dt><dd>{ex.hash_verified ? 'yes' : 'no'}</dd></div>
        <div><dt>Approval consumed</dt><dd>{ex.approval_consumed ? 'yes (single use)' : 'no'}</dd></div>
        <div><dt>Executed at</dt><dd>{fmtTime(ex.executed_at)}</dd></div>
        {ex.external_ref && <div><dt>External ref</dt><dd><code>{ex.external_ref}</code></dd></div>}
      </dl>
      <h3>Gateway checks</h3>
      <ol className="checks">
        {ex.checks.map((c) => (
          <li key={c.step} className={`chk chk-${c.status}`}>
            <span className="chk-n">{c.step}</span>
            <span className="chk-main"><strong>{c.name}</strong><br /><span className="muted">{c.detail}</span></span>
            <StatusBadge status={c.status} />
          </li>
        ))}
      </ol>
    </Card>
  );
}
