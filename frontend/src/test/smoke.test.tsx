import { createHash } from 'node:crypto';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { createMockApi } from '../api/mock/mockApi';
import { sha256 } from '../api/sha256';
import { AppProvider } from '../context';
import Overview from '../pages/Overview';
import Leads from '../pages/Leads';
import { AccountList, AccountPage } from '../pages/Accounts';
import { RunList, RunPage } from '../pages/Runs';
import Alerts from '../pages/Alerts';
import Feedback from '../pages/Feedback';
import Demo from '../pages/Demo';
import Approvals from '../pages/Approvals';

describe('sha256', () => {
  it('matches node crypto', () => {
    for (const s of ['', 'abc', 'x'.repeat(55), 'x'.repeat(56), 'x'.repeat(64), 'café €', 'a'.repeat(1000)]) {
      expect(sha256(s)).toBe(createHash('sha256').update(s).digest('hex'));
    }
  });
});

describe('pages render the finished story without runtime errors', () => {
  it('renders every page', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    await api.decide(301, { decision: 'approve', decided_by: 'user:maya' });
    await api.decide(302, { decision: 'approve', decided_by: 'user:maya' });
    await api.demoReply();
    await api.demoAdvance(5 * 86400);
    const cases: [string, string, React.ReactNode, RegExp][] = [
      ['/', '/', <Overview />, /Golden thread/],
      ['/leads', '/leads', <Leads />, /Priya Raman/],
      ['/accounts', '/accounts', <AccountList />, /Harbourline/],
      ['/accounts/:id', '/accounts/201', <AccountPage />, /Account agent state/],
      ['/runs', '/runs', <RunList />, /inbound_enquiry/],
      ['/runs/:id', '/runs/403', <RunPage />, /Step trace/],
      ['/alerts', '/alerts', <Alerts />, /Why this fired/],
      ['/feedback', '/feedback', <Feedback />, /Lost-deal review/],
      ['/demo', '/demo', <Demo />, /Golden thread complete/],
      ['/approvals/:id', '/approvals/302', <Approvals />, /Gateway checks/],
    ];
    for (const [path, url, el, text] of cases) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[url]}><AppProvider api={api}><Routes><Route path={path} element={el} /></Routes></AppProvider></MemoryRouter>,
      );
      expect((await screen.findAllByText(text)).length).toBeGreaterThan(0);
      unmount();
    }
    expect(err).not.toHaveBeenCalled();
  });
});
