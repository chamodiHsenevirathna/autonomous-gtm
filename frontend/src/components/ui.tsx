import { useState, type ReactNode } from 'react';
import type { DataOrigin, EvidenceBasis } from '../api/types';
import { short } from '../format';

type Tone = 'ok' | 'bad' | 'warn' | 'info' | 'wait' | 'muted';

// Every status has a glyph AND text, so meaning never depends on colour alone.
const STATUS: Record<string, [Tone, string]> = {
  pending: ['warn', '○'], approved: ['ok', '✓'], approved_edited: ['ok', '✎'], rejected: ['bad', '✕'], expired: ['muted', '◷'],
  superseded: ['muted', '↻'], executing: ['info', '▶'], parked: ['wait', '⏸'], blocked: ['bad', '⛔'], executed: ['ok', '✓'], failed: ['bad', '✕'],
  succeeded: ['ok', '✓'], running: ['info', '▶'], waiting: ['wait', '⏳'], dead_letter: ['bad', '☠'], skipped: ['muted', '→'],
  passed: ['ok', '✓'], open: ['info', '●'], won: ['ok', '✓'], lost: ['bad', '✕'],
  new: ['info', '●'], triaged: ['info', '●'], held: ['warn', '⏸'], qualified: ['ok', '✓'], disqualified: ['bad', '✕'], nurture: ['info', '●'], converted: ['ok', '✓'],
  active: ['ok', '●'], quiet: ['muted', '○'], dormant: ['muted', '○'], needs_attention: ['bad', '!'], archived: ['muted', '○'], unprovisioned: ['muted', '○'],
  high: ['bad', '▲'], medium: ['warn', '◆'], low: ['info', '▼'],
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const [tone, glyph] = STATUS[status] ?? ['muted', '●'];
  return (
    <span className={`badge tone-${tone}`} data-status={status}>
      <span aria-hidden="true">{glyph}</span> {label ?? status.replace(/_/g, ' ')}
    </span>
  );
}

export function FitBadge({ band, score }: { band: string | null; score?: number | null }) {
  if (!band) return <span className="muted">-</span>;
  // Contract says 0..1; the real backend currently sends 0..100. Normalise defensively.
  if (score != null && score > 1) score = score / 100;
  const tone: Tone = band === 'high' ? 'ok' : band === 'medium' ? 'warn' : 'muted';
  return <span className={`badge tone-${tone}`}>fit {band}{score != null ? ` ${score.toFixed(2)}` : ''}</span>;
}

export const ORIGIN_TEXT: Record<DataOrigin, string> = {
  GT: 'Generated ground truth',
  SIM: 'Simulated provider output (degraded truth)',
  SCR: 'Scripted prospect/customer response or scenario data',
  MOD: 'Model-generated (deterministic mock unless live mode)',
  'HUM-sim': 'Simulated reviewer decision',
  'HUM-real': 'Real human decision (the person using the demo)',
  PLT: 'Planted effect or theme',
};

export function OriginBadge({ origin }: { origin: DataOrigin }) {
  return (
    <abbr className={`badge origin origin-${origin.replace('-', '')}`} title={ORIGIN_TEXT[origin]}>
      {origin}
    </abbr>
  );
}
export function Origins({ list }: { list: DataOrigin[] }) {
  if (!list?.length) return null;
  return <span className="origins">{list.map((o) => <OriginBadge key={o} origin={o} />)}</span>;
}

export const BASIS_TEXT: Record<EvidenceBasis, [string, string]> = {
  measured_on_simulation: ['Measured on simulation', 'Model or provider output compared with generated ground truth. Valid for the simulated world only.'],
  machinery_check: ['Machinery check', 'The correct answer was planted or scripted. Shows the mechanism works, not accuracy or effect size.'],
  modelled_impact: ['Modelled impact', 'Computed from stated assumptions. Illustrative, not measured.'],
};
export function BasisBadge({ basis }: { basis: EvidenceBasis }) {
  const [label, title] = BASIS_TEXT[basis];
  return <span className={`badge basis basis-${basis}`} title={title}>{label}</span>;
}

export function Hash({ value, n = 12 }: { value: string; n?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="hash">
      <code title={value}>{short(value, n)}</code>
      <button
        type="button" className="link-btn" aria-label={`Copy hash ${value}`}
        onClick={() => { navigator.clipboard?.writeText(value).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); }).catch(() => undefined); }}
      >
        {copied ? 'copied' : 'copy'}
      </button>
    </span>
  );
}

export function Card({ title, actions, children, id, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; id?: string; className?: string }) {
  return (
    <section className={`card ${className ?? ''}`} aria-labelledby={id ? `${id}-h` : undefined}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2 id={id ? `${id}-h` : undefined}>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </div>
  );
}

export function Loading({ what = 'data' }: { what?: string }) {
  return <p className="state" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /> Loading {what}...</p>;
}
export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="state error" role="alert">
      <strong>{(error as { status?: number }).status === 0 ? 'Backend unreachable.' : 'Something went wrong.'}</strong> {error.message}
      {(error as { status?: number }).status === 0 && <> Start the API on 127.0.0.1:8000, or run the UI in mock mode (<code>npm run dev</code> without VITE_API_MODE).</>}
      {onRetry && <> <button type="button" className="btn small" onClick={onRetry}>Retry</button></>}
    </div>
  );
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="state empty"><strong>{title}</strong>{children && <p>{children}</p>}</div>;
}

export function Conf({ value }: { value: number }) {
  return (
    <span className="conf" title={`confidence ${value.toFixed(2)}`}>
      <span className="conf-bar" aria-hidden="true"><span style={{ width: `${Math.round(value * 100)}%` }} /></span>
      <span>{value.toFixed(2)}</span>
    </span>
  );
}

export function Async<T>({ state, children, what, empty }: {
  state: { data: T | null; error: Error | null; loading: boolean; reload: () => void }; children: (d: T) => ReactNode; what?: string; empty?: (d: T) => ReactNode | null;
}) {
  if (state.error && !state.data) return <ErrorBox error={state.error} onRetry={state.reload} />;
  if (!state.data) return <Loading what={what} />;
  const e = empty?.(state.data);
  return <>{state.error && <ErrorBox error={state.error} onRetry={state.reload} />}{e ?? children(state.data)}</>;
}
