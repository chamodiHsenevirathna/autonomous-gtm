import { describe, expect, it } from 'vitest';
import { createMockApi } from '../api/mock/mockApi';

const DECIDER = 'user:maya';

describe('mock API golden thread', () => {
  it('starts with seed data and no golden-thread progress', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const ov = await api.overview();
    expect(ov.golden_thread.every((s) => !s.done)).toBe(true);
    expect((await api.verifyAudit()).ok).toBe(true);
  });

  it('runs the story end to end', async () => {
    const api = createMockApi({ latencyMs: 0 });
    const auditBefore = (await api.audit(1000)).length;
    const r = await api.demoEnquiry();
    expect(r.ok).toBe(true);
    const acct = await api.account(201);
    expect(acct.fields.find((f) => f.key === 'employees')?.conflict).toBe(true);
    expect(acct.fields.some((f) => f.key.startsWith('ai_') && f.owner === 'agent')).toBe(true);
    const [p1, p2] = [await api.proposal(301), await api.proposal(302)];
    expect(p1.status).toBe('pending');
    expect(p2.status).toBe('blocked');
    expect(p2.depends_on).toBe(301);

    // dependent cannot be decided first
    await expect(api.decide(302, { decision: 'approve', decided_by: DECIDER })).rejects.toThrow(/Blocked/);
    // reply cannot arrive before the send
    expect((await api.demoReply()).ok).toBe(false);

    const d1 = await api.decide(301, { decision: 'approve', decided_by: DECIDER });
    expect(d1.status).toBe('executed');
    expect(d1.execution?.checks).toHaveLength(13);
    expect((await api.proposal(302)).status).toBe('pending');

    const d2 = await api.decide(302, { decision: 'approve', decided_by: DECIDER });
    expect(d2.status).toBe('executed');
    expect(d2.execution?.adapter).toBe('outreach.send');

    expect((await api.demoReply()).ok).toBe(true);
    const after = await api.account(201);
    expect(after.agent_state?.version).toBe(2);
    expect(after.agent_state?.stakeholders.map((s) => s.name)).toContain('Jonas Weber');
    expect((await api.overview()).golden_thread.every((s) => s.done)).toBe(true);
    expect((await api.audit(1000)).length).toBeGreaterThan(auditBefore + 8);
    expect((await api.verifyAudit()).ok).toBe(true);
  });

  it('blocks an edited message that contains a price and changes the hash', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    await api.decide(301, { decision: 'approve', decided_by: DECIDER });
    const p = await api.proposal(302);
    const out = await api.decide(302, { decision: 'approve_with_edits', decided_by: DECIDER, edited_payload: { ...p.payload, body: p.payload.body + '\nOur fee is EUR 20 per hour... or $5000 total.' } });
    expect(out.status).toBe('blocked');
    expect(out.payload_hash).not.toBe(p.payload_hash);
    expect(out.execution?.checks.find((c) => c.status === 'failed')?.step).toBe(3);
    expect(out.execution?.approval_consumed).toBe(false);
  });

  it('requires a reason to reject and supersedes the dependent proposal', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    await expect(api.decide(301, { decision: 'reject', decided_by: DECIDER })).rejects.toThrow(/reason/i);
    await api.decide(301, { decision: 'reject', decided_by: DECIDER, reason_code: 'duplicate' });
    expect((await api.proposal(302)).status).toBe('superseded');
  });

  it('detects tampering with the audit chain, and reset restores it', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.mockTamper?.();
    const v = await api.verifyAudit();
    expect(v.ok).toBe(false);
    expect(v.first_bad_seq).toBeGreaterThan(0);
    await api.demoReset();
    expect((await api.verifyAudit()).ok).toBe(true);
  });

  it('advancing time expires proposals and moves the clock', async () => {
    const api = createMockApi({ latencyMs: 0 });
    await api.demoEnquiry();
    const before = (await api.health()).clock;
    await api.demoAdvance(4 * 86400);
    expect(Date.parse((await api.health()).clock)).toBeGreaterThan(Date.parse(before));
    expect((await api.proposal(302)).status).toBe('expired');
  });
});
