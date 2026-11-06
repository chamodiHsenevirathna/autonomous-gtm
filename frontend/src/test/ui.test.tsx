import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { createMockApi } from '../api/mock/mockApi';
import { AppProvider } from '../context';
import { ProposalDetail } from '../pages/Approvals';
import Audit from '../pages/Audit';
import Evaluation from '../pages/Evaluation';
import type { Api } from '../api/client';

function wrap(api: Api, ui: React.ReactNode) {
  return render(<MemoryRouter><AppProvider api={api}>{ui}</AppProvider></MemoryRouter>);
}

describe('approval decision flow', () => {
  it('shows payload and hash, then the gateway outcome after approval', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    const p = await api.proposal(301);
    wrap(api, <ProposalDetail id={301} />);
    expect(await screen.findByText(p.payload_hash)).toBeInTheDocument();
    expect(screen.getByText(/create company/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText(/Gateway and execution outcome/)).toBeInTheDocument();
    expect(screen.getAllByText(/Approval valid/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('requires a reason code to reject', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    wrap(api, <ProposalDetail id={301} />);
    fireEvent.click(await screen.findByLabelText('Reject'));
    const select = screen.getByLabelText(/Reason code/);
    expect(select).toBeRequired();
    fireEvent.change(select, { target: { value: 'duplicate' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    expect(await screen.findByText('Decision record')).toBeInTheDocument();
    expect(screen.getByText('duplicate')).toBeInTheDocument();
    expect((await api.proposal(301)).status).toBe('rejected');
  });

  it('shows a blocked dependent proposal with its reason', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    wrap(api, <ProposalDetail id={302} />);
    expect(await screen.findByText(/Linked proposal/)).toBeInTheDocument();
    expect(screen.getByText(/Waiting for proposal #301/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });
});

describe('audit verify display', () => {
  it('shows OK, then BROKEN after tampering', async () => {
    const api = createMockApi({ latencyMs: 0 });
    wrap(api, <Audit />);
    fireEvent.click(await screen.findByRole('button', { name: 'Verify chain' }));
    expect(await screen.findByTestId('verify-ok')).toHaveTextContent(/Chain OK/);
    fireEvent.click(screen.getByRole('button', { name: /Tamper/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Verify chain' }));
    const broken = await screen.findByTestId('verify-broken');
    expect(within(broken).getByText(/BROKEN/)).toBeInTheDocument();
  });
});

describe('evaluation page', () => {
  it('always shows the honest statement and evidence-basis badges', async () => {
    wrap(createMockApi({ latencyMs: 0 }), <Evaluation />);
    expect(await screen.findByTestId('honest-statement')).toHaveTextContent(/not real-world evidence/i);
    expect((await screen.findAllByText('Machinery check')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Measured on simulation').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Modelled impact').length).toBeGreaterThan(0);
  });
});
