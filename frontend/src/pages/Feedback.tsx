import { useState, type FormEvent } from 'react';
import { useApp, useData } from '../context';
import { Async, Card, Empty, OriginBadge, PageHeader } from '../components/ui';
import { fmtTime, titleCase } from '../format';

const REASONS: [string, string][] = [
  ['lost_to_incumbent', 'Lost to incumbent / existing supplier'], ['lost_to_competitor', 'Lost to a named competitor'], ['price_budget', 'Price or budget'],
  ['timing', 'Timing / project deferred'], ['no_decision', 'No decision / went silent'], ['scope_fit', 'Scope or capability fit'], ['champion_left', 'Champion left'], ['other', 'Other'],
];

export default function Feedback() {
  const { api, bump } = useApp();
  const list = useData((a) => a.feedback());
  const accounts = useData((a) => a.accounts());
  const [accountId, setAccountId] = useState('');
  const [reasonCode, setReasonCode] = useState('');
  const [primary, setPrimary] = useState('');
  const [competitor, setCompetitor] = useState('');
  const [couldWin, setCouldWin] = useState<'yes' | 'maybe' | 'no'>('maybe');
  const [change, setChange] = useState('');
  const [quotes, setQuotes] = useState<string[]>(['']);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (!reasonCode || !primary.trim()) { setMsg({ ok: false, text: 'Reason code and a primary reason are required.' }); return; }
    setBusy(true);
    try {
      const r = await api.submitLostDealReview({
        account_id: accountId ? Number(accountId) : null, opportunity_id: null, reason_code: reasonCode, primary_reason: primary.trim(),
        competitor: competitor.trim() || null, could_we_have_won: couldWin, what_would_change_it: change.trim(), verbatim_quotes: quotes.map((q) => q.trim()).filter(Boolean), reviewer: 'user:maya',
      });
      setMsg({ ok: true, text: `Saved as feedback #${r.feedback_id}.` });
      setPrimary(''); setCompetitor(''); setChange(''); setQuotes(['']); setReasonCode('');
      bump();
    } catch (ex) { setMsg({ ok: false, text: (ex as Error).message }); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Feedback" sub="Structured lost-deal reviews and reviewer comments. Reasons are entered by humans; AI-suggested tags are shown separately and never merged." />
      <div className="grid-2 top">
        <Card title="Lost-deal review" id="form">
          <form onSubmit={submit}>
            <label className="field">Account
              <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">Not linked to an account</option>
                {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </label>
            <label className="field"><span>Primary reason code <span className="req">(required)</span></span>
              <select value={reasonCode} onChange={(e) => setReasonCode(e.target.value)} required>
                <option value="">Select...</option>
                {REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="field"><span>What happened, in your words <span className="req">(required)</span></span>
              <textarea rows={3} value={primary} onChange={(e) => setPrimary(e.target.value)} required />
            </label>
            <label className="field">Competitor (if any)<input value={competitor} onChange={(e) => setCompetitor(e.target.value)} /></label>
            <fieldset>
              <legend>Could we have won?</legend>
              <div className="radios">
                {(['yes', 'maybe', 'no'] as const).map((v) => (<label key={v}><input type="radio" name="win" checked={couldWin === v} onChange={() => setCouldWin(v)} /> {titleCase(v)}</label>))}
              </div>
            </fieldset>
            <label className="field">What would have changed the outcome?<textarea rows={2} value={change} onChange={(e) => setChange(e.target.value)} /></label>
            <fieldset>
              <legend>Verbatim customer quotes</legend>
              <p className="muted">Paste exact words. Quotes are stored unedited and shown before any AI summary.</p>
              {quotes.map((q, i) => (
                <label key={i} className="field">Quote {i + 1}
                  <textarea rows={2} value={q} onChange={(e) => setQuotes(quotes.map((x, j) => (j === i ? e.target.value : x)))} />
                </label>
              ))}
              <button type="button" className="btn small" onClick={() => setQuotes([...quotes, ''])}>Add another quote</button>
            </fieldset>
            {msg && <p className={msg.ok ? 'callout ok' : 'form-error'} role={msg.ok ? 'status' : 'alert'}>{msg.text}</p>}
            <button type="submit" className="btn primary" disabled={busy}>{busy ? 'Saving...' : 'Save review'}</button>
          </form>
        </Card>
        <Card title="Feedback items" id="items">
          <Async state={list} what="feedback" empty={(d) => (d.length ? null : <Empty title="No feedback yet" />)}>
            {(rows) => (
              <ul className="plain feedback">
                {rows.map((f) => (
                  <li key={f.id}>
                    <div><strong>#{f.id} {titleCase(f.kind)}</strong> {f.account_name && <span className="muted">/ {f.account_name}</span>} <OriginBadge origin={f.data_origin} /></div>
                    <div className="muted">{fmtTime(f.created_at)} by <code>{f.created_by}</code>{f.reason_code && <> / reason <code>{f.reason_code}</code></>}</div>
                    <p>{f.summary}</p>
                    {f.quotes.map((q, i) => (<blockquote key={i} className="quote">{'“'}{q.text}{'”'}{q.speaker && <footer>{q.speaker}{q.source_ref && <> <code className="ref">{q.source_ref}</code></>}</footer>}</blockquote>))}
                    <p className="row-wrap">
                      <span className="muted">Human tags:</span> {f.tags_human.length ? f.tags_human.map((t) => <span key={t} className="chip">{t}</span>) : <span className="muted">none</span>}
                    </p>
                    {f.tags_ai_suggested.length > 0 && (
                      <p className="row-wrap"><span className="badge tone-ai">AI-suggested</span> {f.tags_ai_suggested.map((t) => <span key={t} className="chip ai">{t}</span>)}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </Card>
      </div>
    </>
  );
}
