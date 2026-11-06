import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useApp, useData } from '../context';
import { fmtTime } from '../format';

const NAV: [string, string][] = [
  ['/', 'Overview'], ['/leads', 'Leads'], ['/accounts', 'Accounts'], ['/approvals', 'Approvals'], ['/runs', 'Runs'],
  ['/alerts', 'Pipeline alerts'], ['/audit', 'Audit'], ['/evaluation', 'Evaluation'], ['/feedback', 'Feedback'], ['/demo', 'Demo control'],
];

type Theme = 'light' | 'dark';
function initialTheme(): Theme {
  try {
    const t = localStorage.getItem('gtm-theme');
    if (t === 'light' || t === 'dark') return t;
  } catch { /* storage unavailable */ }
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function Layout() {
  const { api } = useApp();
  const health = useData((a) => a.health());
  const config = useData((a) => a.config());
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('gtm-theme', theme); } catch { /* ignore */ }
  }, [theme]);

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="topbar-row">
          <div className="brand"><span className="logo" aria-hidden="true">G</span><span>Autonomous GTM <span className="muted">/ Corvane Digital</span></span></div>
          <div className="topbar-right">
            <span className="clock" title="Simulated clock. Not wall-clock time.">
              <span className="muted">Sim clock</span> <time dateTime={health.data?.clock}>{health.data ? fmtTime(health.data.clock) : '...'}</time>
            </span>
            {health.error && <span className="badge tone-bad" role="status"><span aria-hidden="true">!</span> Backend unreachable</span>}
            {api.mode === 'mock' && <span className="badge tone-info" title="No backend is connected; fixtures run in the browser.">Mock API (browser fixtures)</span>}
            <button type="button" className="btn small" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
              {theme === 'dark' ? 'Light' : 'Dark'} theme
            </button>
          </div>
        </div>
        <div className="notice" role="note">
          <strong>SYNTHETIC DATA</strong> <span aria-hidden="true">/</span> <strong>SIMULATED MODEL</strong>
          <span className="notice-text"> Fictional company and people. Providers, CRM and email are simulators. AI output comes from a deterministic mock{config.data ? ` (llm_mode: ${config.data.llm_mode}, live: ${config.data.live_enabled ? 'ON' : 'off'})` : ''}. No real message is ever sent.</span>
        </div>
      </header>
      <div className="body">
        <nav className="nav" aria-label="Main">
          <ul>
            {NAV.map(([to, label]) => (
              <li key={to}><NavLink to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>{label}</NavLink></li>
            ))}
          </ul>
        </nav>
        <main id="main" tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  );
}
