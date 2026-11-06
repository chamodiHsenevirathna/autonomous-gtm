/**
 * In-memory mock backend. Tells the golden-thread story end to end and reacts to the demo buttons.
 * Everything here is a frontend fixture; the audit chain uses real SHA-256 so "Verify chain" is genuine
 * for the mock data. Nothing here is evidence about the real backend.
 */
import { ApiError, type Api } from '../client';
import { canonicalJson, payloadHash, sha256 } from '../sha256';
import type {
  AccountDetail, AccountRow, AgentState, AuditRow, DataOrigin, DecisionIn, DecisionRecord, DemoResultOut,
  EvalSummaryOut, EventRow, ExecutionOut, FeedbackRow, GatewayCheck, InteractionOut, LeadOut, LostDealReviewIn,
  OpportunityRow, PipelineAlert, ProposalOut, ResolvedField, RunDetail, RunRow, RunStep, FieldAlternative,
  FieldOwner, StepStatus, NodeType, FitBand,
} from '../types';
import { NOTICE, evalFixture, seedFeedback } from './seed';

const START = Date.parse('2026-03-09T09:00:00Z');
const DAY = 86400_000;
const GENESIS = '0'.repeat(64);
const iso = (ms: number) => new Date(ms).toISOString().replace('.000Z', 'Z');

interface RawField extends Omit<ResolvedField, 'freshness' | 'freshness_days'> {}
interface AccountFull extends AccountRow {
  fields: RawField[];
  agent_state: AgentState | null;
  interactions: InteractionOut[];
}
interface Flags { enquiry: boolean; p1: boolean; p2: boolean; reply: boolean; noReplyAlert: boolean }

interface State {
  now: number;
  ids: Record<string, number>;
  leads: LeadOut[];
  accounts: AccountFull[];
  proposals: ProposalOut[];
  runs: RunDetail[];
  audit: AuditRow[];
  events: EventRow[];
  feedback: FeedbackRow[];
  opps: OpportunityRow[];
  alerts: PipelineAlert[];
  evalRuns: number;
  flags: Flags;
}

const GATE: Record<string, string> = { crm_write: 'G4', message: 'G5', task: 'G7', field_change: 'G6', lead_disposition: 'G3' };

function fresh(ms: number, now: number): { freshness_days: number; freshness: 'fresh' | 'aging' | 'stale' } {
  const d = Math.max(0, Math.floor((now - ms) / DAY));
  return { freshness_days: d, freshness: d <= 30 ? 'fresh' : d <= 120 ? 'aging' : 'stale' };
}

export interface MockOptions { latencyMs?: number }

export function createMockApi(opts: MockOptions = {}): Api {
  const latency = opts.latencyMs ?? 120;
  let s: State = undefined as unknown as State;

  // ---------- helpers ----------
  function nextId(kind: string, start: number): number {
    s.ids[kind] = (s.ids[kind] ?? start - 1) + 1;
    return s.ids[kind];
  }

  function audit(actor_type: string, actor_id: string, event_type: string, entity_ref: string | null,
    proposal_id: number | null, run_id: number | null, data: Record<string, any> = {}) {
    const seq = s.audit.length + 1;
    const prev_hash = s.audit.length ? s.audit[s.audit.length - 1].hash : GENESIS;
    const at = iso(s.now);
    const body = { seq, at, actor_type, actor_id, event_type, entity_ref, proposal_id, run_id, data, prev_hash };
    s.audit.push({ ...body, hash: sha256(canonicalJson(body)) });
    s.events.push({ id: seq, at, event_type, entity_ref, source: actor_type, dedupe_key: `${event_type}:${entity_ref ?? ''}:${seq}` });
  }

  function mkField(key: string, label: string, value: string | number | null, owner: FieldOwner, source: string,
    confidence: number, ageDays: number, origin: DataOrigin, alts: FieldAlternative[] = []): RawField {
    return {
      key, label, value, owner, source, confidence, as_of: iso(s.now - ageDays * DAY), conflict: alts.length > 0,
      alternatives: alts, data_origin: origin,
    };
  }

  function step(seq: number, node: string, node_type: NodeType, status: StepStatus, o: Partial<RunStep> = {}): RunStep {
    return {
      id: nextId('step', 9000), seq, node, node_type, status, attempts: status === 'waiting' ? 0 : 1,
      started_at: iso(s.now), finished_at: status === 'succeeded' ? iso(s.now) : null, error: null, parked_until: null,
      waiting_for: null, cost_usd: 0, sim_units: 0, model_mode: node_type === 'llm' || node_type === 'agent' ? 'mock' : null,
      note: null, ...o,
    };
  }

  function mkRun(workflow: string, trigger: string, account: AccountFull | null, steps: RunStep[], status: RunRow['status']): RunDetail {
    const run: RunDetail = {
      id: nextId('run', 401), workflow, status, trigger, account_id: account?.id ?? null, account_name: account?.name ?? null,
      started_at: iso(s.now), finished_at: status === 'succeeded' ? iso(s.now) : null, steps_total: steps.length,
      steps_done: steps.filter((x) => x.status === 'succeeded' || x.status === 'skipped').length,
      cost_usd: steps.reduce((a, b) => a + b.cost_usd, 0), steps,
    };
    s.runs.push(run);
    return run;
  }

  function refreshRun(run: RunDetail) {
    run.steps_done = run.steps.filter((x) => x.status === 'succeeded' || x.status === 'skipped').length;
    const open = run.steps.some((x) => x.status === 'waiting');
    run.status = run.steps.some((x) => x.status === 'failed') ? 'failed' : open ? 'waiting' : 'succeeded';
    run.finished_at = open ? null : iso(s.now);
  }

  function proposal(p: Omit<ProposalOut, 'id' | 'gate_id' | 'payload_hash' | 'decisions' | 'execution' | 'created_at'> & { id?: number }): ProposalOut {
    const id = p.id ?? nextId('proposal', 301);
    const full: ProposalOut = {
      ...p, id, gate_id: GATE[p.type] ?? 'G?', created_at: iso(s.now), decisions: [], execution: null,
      payload_hash: payloadHash(id, p.type, p.payload),
    };
    s.proposals.push(full);
    audit('agent', 'agent:account', 'proposal.created', `proposal:${id}`, id, null, { type: p.type, hash: full.payload_hash });
    return full;
  }

  function accountOf(id: number | null): AccountFull | undefined {
    return s.accounts.find((a) => a.id === id);
  }
  function openCount(accountId: number) {
    return s.proposals.filter((p) => p.account_id === accountId && ['pending', 'blocked', 'parked'].includes(p.status)).length;
  }
  function row(a: AccountFull): AccountRow {
    const { fields: _f, agent_state: _a, interactions: _i, ...r } = a;
    void _f; void _a; void _i;
    return { ...r, open_proposals: openCount(a.id) };
  }
  function addInteraction(a: AccountFull, kind: InteractionOut['kind'], summary: string, detail: string | null, ref: string | null, origin: DataOrigin) {
    a.interactions.unshift({ id: nextId('inter', 7001), at: iso(s.now), kind, summary, detail, ref, data_origin: origin });
    a.last_interaction_at = iso(s.now);
  }

  // ---------- gateway simulation (docs/execution-architecture.md 13.2) ----------
  const STEP_NAMES = [
    'Approval valid (role, expiry, hash match, unconsumed)', 'Experiment state and holdout', 'Content screens on final hash (commercial, links, claims)',
    'Recipient resolution and data quality', 'Suppression / do-not-contact pre-check', 'Outreach claims and priority',
    'Frequency caps and duplicate-outreach key', 'Human-touch lock and recent-interaction re-read', 'Domain breaker and throttle',
    'Sync precondition (contact visible in target)', 'Transaction: suppression re-read, consume approval, write execution row',
    'Adapter call with execution token', 'Audit event and domain event',
  ];

  function runGateway(p: ProposalOut): ExecutionOut {
    const isMsg = p.type === 'message';
    const applies = isMsg ? new Set([1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]) : new Set([1, 3, 7, 10, 11, 12, 13]);
    const adapter = isMsg ? 'outreach.send' : p.type === 'crm_write' ? 'crm.write' : 'tasks.create';
    const checks: GatewayCheck[] = [];
    let failed: { step: number; detail: string; kind: 'soft' | 'hard' } | null = null;
    const body = String(p.payload.body ?? '');
    if (isMsg && /[€$£]\s?\d|\b(?:EUR|USD|GBP)\s?\d|\d\s?(?:EUR|USD|GBP)\b|\b\d+\s?%\s*(off|discount)|\bdiscount\b/i.test(body)) {
      failed = { step: 3, kind: 'soft', detail: 'Commercial-content screen: price or discount text detected in the final body. Remove it (discount terms are human-only) and re-approve.' };
    }
    const unsupported = (p.payload.claims ?? []).filter((c: { source_ref: string | null }) => !c.source_ref);
    if (!failed && unsupported.length) {
      failed = { step: 3, kind: 'soft', detail: `Claim-source check: ${unsupported.length} claim(s) have no source reference.` };
    }
    const detailOk: Record<number, string> = {
      1: `Role ${p.required_role ?? 'n/a'} satisfied; hash ${p.payload_hash.slice(0, 12)} matches stored content; approval unconsumed.`,
      3: 'Commercial-content screen clean; links on allow-list; every claim has a source.',
      4: `Recipient re-resolved to ${p.payload.resolved_recipient ?? 'n/a'}; matches approved address; confidence ok.`,
      5: 'No suppression or do-not-contact entry for recipient or domain.',
      6: 'No competing outreach claim on this contact.',
      7: 'Caps ok; duplicate-outreach key reserved atomically.',
      8: 'No human touch in the last 7 simulated days.',
      9: 'Domain breaker closed; within throttle.',
      10: p.type === 'message' ? 'Contact visible in simulated CRM (created by proposal #' + (p.depends_on ?? '?') + ').' : 'Target CRM sandbox reachable.',
      11: 'Authoritative suppression re-read (row lock), approval consumed, execution row written (single transaction).',
      12: isMsg ? 'Sent through the SIMULATED outreach adapter. No real email leaves this system.' : 'Written to the SIMULATED CRM adapter.',
      13: 'Audit event appended; domain event emitted.',
    };
    for (let n = 1; n <= 13; n++) {
      if (!applies.has(n)) checks.push({ step: n, name: STEP_NAMES[n - 1], status: 'skipped', detail: 'Not applicable to this proposal type.' });
      else if (failed && n === failed.step) checks.push({ step: n, name: STEP_NAMES[n - 1], status: 'failed', detail: failed.detail });
      else if (failed && n > failed.step) checks.push({ step: n, name: STEP_NAMES[n - 1], status: 'skipped', detail: 'Not reached: an earlier check blocked execution.' });
      else checks.push({ step: n, name: STEP_NAMES[n - 1], status: 'passed', detail: detailOk[n] });
    }
    const key = `exec:${p.id}:${p.payload_hash.slice(0, 16)}`;
    if (failed) {
      return { status: 'blocked', adapter, idempotency_key: key, executed_at: null, hash_verified: true, approval_consumed: false,
        block_kind: failed.kind, outcome: `BLOCKED (${failed.kind}) at check ${failed.step}. Nothing was sent. ${failed.detail}`, checks };
    }
    return {
      status: 'executed', adapter, idempotency_key: key, executed_at: iso(s.now), hash_verified: true, approval_consumed: true, block_kind: null,
      external_ref: isMsg ? `sim-msg-${p.id}` : p.type === 'crm_write' ? 'CRM-HL-0001' : `task-${p.id}`,
      outcome: isMsg ? 'Message handed to the simulated outreach provider. Approval consumed (single use).'
        : p.type === 'crm_write' ? 'Company, contact and deal created in the simulated CRM. Approval consumed (single use).' : 'Task created for the owner.',
      checks,
    };
  }

  function afterExecuted(p: ProposalOut) {
    const a = accountOf(p.account_id);
    if (p.type === 'crm_write' && a) {
      s.flags.p1 = true;
      const crm = a.fields.find((f) => f.key === 'crm_id');
      if (crm) { crm.value = 'CRM-HL-0001'; crm.as_of = iso(s.now); }
      s.opps.push({ id: 501, account_id: a.id, account_name: a.name, name: 'Harbourline - data platform scoping', stage: 'Qualified',
        amount: null, currency: 'EUR', owner: 'Maya Okafor', days_in_stage: 0, status: 'open', data_origin: 'SIM' });
      const lead = s.leads.find((l) => l.account_id === a.id);
      if (lead) lead.status = 'converted';
      addInteraction(a, 'crm', 'CRM records created in the simulated CRM', 'Company, contact and deal (stage Qualified, amount not set).', `proposal:${p.id}`, 'SIM');
      const dep = s.proposals.find((x) => x.depends_on === p.id && x.status === 'blocked');
      if (dep) {
        dep.status = 'pending'; dep.block_reason = null;
        audit('system', 'system:orchestrator', 'proposal.unblocked', `proposal:${dep.id}`, dep.id, null, { dependency: p.id });
      }
    }
    if (p.type === 'message' && a) {
      s.flags.p2 = true;
      addInteraction(a, 'email_out', `Intro reply sent: "${p.payload.subject}"`, String(p.payload.body), `proposal:${p.id}`, 'SIM');
    }
    // advance the inbound run's approval steps
    const run = s.runs.find((r) => r.workflow === 'inbound_enquiry' && r.account_id === p.account_id);
    if (run) {
      const st = run.steps.find((x) => x.waiting_for === `approval:${p.id}`);
      if (st) { st.status = 'succeeded'; st.finished_at = iso(s.now); st.attempts = 1; st.note = `Approved by a human; executed via ${p.execution?.adapter}.`; }
      refreshRun(run);
    }
  }

  // ---------- init ----------
  function init(): State {
    const st: State = {
      now: START, ids: {}, leads: [], accounts: [], proposals: [], runs: [], audit: [], events: [], feedback: [], opps: [], alerts: [],
      evalRuns: 1, flags: { enquiry: false, p1: false, p2: false, reply: false, noReplyAlert: false },
    };
    s = st;
    const f = mkField;
    const mk = (id: number, name: string, domain: string, industry: string, employees: number, lifecycle: AccountRow['lifecycle'],
      owner: string, fit: FitBand, lastDaysAgo: number, summary: string): AccountFull => ({
      id, name, domain, industry, employees, lifecycle, owner, open_proposals: 0, fit_band: fit, data_origins: ['GT', 'SIM'],
      last_interaction_at: iso(START - lastDaysAgo * DAY),
      fields: [
        f('name', 'Company name', name, 'provider', 'orgdata (simulated)', 0.98, 40, 'SIM'),
        f('domain', 'Domain', domain, 'provider', 'orgdata (simulated)', 0.97, 40, 'SIM'),
        f('industry', 'Industry', industry, 'provider', 'orgdata (simulated)', 0.9, 40, 'SIM'),
        f('employees', 'Employees', employees, 'provider', 'orgdata (simulated)', 0.72, 75, 'SIM'),
        f('owner', 'Account owner', owner, 'human', 'CRM (human-owned)', 1, 30, 'GT'),
      ],
      agent_state: {
        lifecycle, version: 3, updated_at: iso(START - 2 * DAY), mode: 'mock', summary, summary_refs: ['interaction:seed'],
        stakeholders: [], risks: [], commitments: [], open_questions: [], next_actions: [], last_decision: { action: 'no_action', confidence: 0.8, would_change_mind: 'A reply or a new signal at the account.' },
      },
      interactions: [{ id: nextId('inter', 7001), at: iso(START - lastDaysAgo * DAY), kind: 'email_in', summary: 'Last contact (seed data)', detail: null, ref: null, data_origin: 'GT' }],
    });
    const a1 = mk(1, 'Meridian Biologics', 'meridianbio.example', 'Life sciences', 640, 'active', 'Maya Okafor', 'high', 31,
      'Open data-platform assessment proposal. No reply for 31 days after the CFO changed role; deal is stalled in the Proposal stage.');
    a1.agent_state!.risks = [{ text: 'Champion (CFO) changed role; new owner of the budget is unknown.', severity: 'high', refs: ['signal:job-change-77'] }];
    a1.agent_state!.next_actions = [{ id: 1, action: 'recommend_task', text: 'Ask the AE to call the new finance lead', status: 'pending_approval', proposal_id: 290, rationale: 'Stall threshold (45 days) exceeded.' }];
    const a2 = mk(2, 'Aldous & Pryce LLP', 'aldouspryce.example', 'Legal services', 210, 'dormant', 'Ravi Menon', 'medium', 130,
      'Lost to an incumbent firm. Dormant for 130 simulated days; reactivates only on a trigger event.');
    const a3 = mk(3, 'Tidewater Energy Partners', 'tidewater.example', 'Energy', 1900, 'active', 'Maya Okafor', 'high', 4,
      'AI readiness sprint in discovery. Two stakeholders engaged; kickoff scheduled.');
    s.accounts.push(a1, a2, a3);
    s.leads.push(
      { id: 98, received_at: iso(START - 3 * DAY), name: 'Growth Hacks Ltd', email: 'sales@rankboost.example', company: 'RankBoost', message: 'We can 10x your SEO ranking in 7 days. Reply for a free audit!', triage_class: 'vendor', fit_score: 0.04, fit_band: 'low', status: 'held', held: true, held_reason: 'Vendor solicitation. Held (reversible), listed in the daily digest with one-click release.', account_id: null, service_line: null, data_origins: ['SCR', 'MOD'] },
      { id: 99, received_at: iso(START - 2 * DAY), name: 'Sam Doyle', email: 'sam.doyle@talentbridge.example', company: 'TalentBridge', message: 'We have senior data engineers available for placement.', triage_class: 'recruiter', fit_score: 0.06, fit_band: 'low', status: 'held', held: true, held_reason: 'Recruiter. Held (reversible).', account_id: null, service_line: null, data_origins: ['SCR', 'MOD'] },
      { id: 100, received_at: iso(START - 6 * DAY), name: 'Elin Marsh', email: 'elin.marsh@tidewater.example', company: 'Tidewater Energy Partners', message: 'Interested in an AI readiness sprint for our trading analytics team.', triage_class: 'real_lead', fit_score: 0.81, fit_band: 'high', status: 'converted', held: false, held_reason: null, account_id: 3, service_line: 'AI readiness', data_origins: ['SCR', 'MOD'] },
    );
    s.opps.push(
      { id: 11, account_id: 1, account_name: a1.name, name: 'Data platform assessment', stage: 'Proposal', amount: 85000, currency: 'EUR', owner: 'Maya Okafor', days_in_stage: 52, status: 'open', data_origin: 'GT' },
      { id: 12, account_id: 3, account_name: a3.name, name: 'AI readiness sprint', stage: 'Discovery', amount: 42000, currency: 'EUR', owner: 'Maya Okafor', days_in_stage: 9, status: 'open', data_origin: 'GT' },
    );
    s.alerts.push({
      id: 1, opportunity_id: 11, opportunity_name: 'Data platform assessment', account_id: 1, account_name: a1.name, severity: 'high', kind: 'stalled', days_stalled: 52,
      reasons: ['52 days in Proposal; the stall threshold is 45 days.', 'No customer reply for 31 days.', 'Champion (CFO) changed role per a job-change signal.'],
      recommendation: 'Call the new finance lead and re-confirm the budget owner before sending anything further.', raised_at: iso(START - 7 * DAY), data_origin: 'PLT',
    });
    for (const [t, ref] of [['system.reset', null], ['world.seeded', 'world:42'], ['lead.received', 'lead:100'], ['proposal.decided', 'proposal:280']] as const) {
      audit('system', 'system:seed', t, ref, null, null, { note: 'seed data' });
    }
    // proposal 290 predates the golden thread, so reserve its id explicitly
    proposal({
      id: 290, type: 'task', status: 'pending', account_id: 1, account_name: a1.name,
      payload: { owner: 'user:maya', title: 'Call the new finance lead at Meridian Biologics', detail: 'Champion changed role; confirm budget owner.', due_at: iso(START + 2 * DAY) },
      evidence: [{ kind: 'signal', ref: 'signal:job-change-77', text: 'CFO moved to a different role (planted job-change signal).', source: 'signals feed (simulated)', data_origin: 'PLT' }],
      rationale: 'Deal stalled 52 days; champion left the budget role.', confidence: 0.74, required_role: 'AE', expires_at: iso(START + 5 * DAY),
      depends_on: null, block_reason: null, data_origins: ['PLT', 'MOD']
    });
    const run = mkRun('daily_heartbeat', 'schedule:daily', null, [
      step(1, 'select_active_accounts', 'code', 'succeeded', { note: '3 accounts due' }),
      step(2, 'wake_account_agents', 'map', 'succeeded', { note: '2 no_action, 1 task recommended' }),
    ], 'succeeded');
    run.started_at = iso(START - DAY);
    const parked = mkRun('enrichment_refresh', 'schedule:weekly', a2, [
      step(1, 'select_stale_fields', 'code', 'succeeded'),
      step(2, 'refresh_headcount', 'tool', 'parked', { attempts: 3, error: { class: 'RetryableError', message: 'Provider orgdata (simulated) rate limited: 429, retry-after 600s' }, parked_until: iso(START + 3600_000), sim_units: 1 }),
      step(3, 'resolve_fields', 'code', 'waiting', { waiting_for: 'step:2' }),
    ], 'parked');
    parked.started_at = iso(START - 3600_000);
    s.feedback = seedFeedback(iso(START - 10 * DAY));
    s.evalRuns = 1;
    return st;
  }

  // ---------- golden thread ----------
  function submitEnquiry(): DemoResultOut {
    if (s.flags.enquiry) return { ok: false, message: 'The scripted enquiry was already submitted (idempotent). Reset to replay the story.', clock: iso(s.now), created: {} };
    s.flags.enquiry = true;
    const lead: LeadOut = {
      id: 101, received_at: iso(s.now), name: 'Priya Raman', email: 'priya.raman@harbourline.example', company: 'Harbourline Freight Group',
      message: 'We run 14 regional freight hubs and our planning data lives in five systems. We would like help scoping a data platform and some AI-assisted demand forecasting. Budget is approved for this half. Could someone speak this week?',
      triage_class: 'real_lead', fit_score: 0.86, fit_band: 'high', status: 'qualified', held: false, held_reason: null, account_id: 201,
      service_line: 'Data platform', data_origins: ['SCR', 'MOD'],
    };
    s.leads.unshift(lead);
    const when = (d: number) => iso(s.now - d * DAY);
    void when;
    const acct: AccountFull = {
      id: 201, name: 'Harbourline Freight Group', domain: 'harbourline.example', industry: 'Freight and logistics', employees: 1150,
      lifecycle: 'active', owner: 'Maya Okafor', open_proposals: 0, fit_band: 'high', data_origins: ['SCR', 'SIM', 'MOD'], last_interaction_at: iso(s.now),
      fields: [
        mkField('name', 'Company name', 'Harbourline Freight Group', 'provider', 'orgdata (simulated)', 0.98, 12, 'SIM'),
        mkField('domain', 'Domain', 'harbourline.example', 'provider', 'orgdata (simulated)', 0.97, 12, 'SIM'),
        mkField('industry', 'Industry', 'Freight and logistics', 'provider', 'orgdata (simulated)', 0.9, 12, 'SIM'),
        mkField('employees', 'Employees', 1150, 'provider', 'orgdata (simulated)', 0.7, 62, 'SIM', [
          { source: 'firmo (simulated)', value: 840, confidence: 0.55, as_of: iso(s.now - 190 * DAY) },
        ]),
        mkField('hq', 'Headquarters', 'Rotterdam, NL', 'provider', 'firmo (simulated)', 0.88, 20, 'SIM'),
        mkField('revenue_band', 'Revenue band', 'EUR 200-500M', 'provider', 'firmo (simulated)', 0.6, 95, 'SIM'),
        mkField('tech_hint', 'Tech stack hint', 'SAP; Snowflake (partial)', 'provider', 'web scrape (simulated)', 0.4, 210, 'SIM'),
        mkField('owner', 'Account owner', 'Maya Okafor', 'human', 'Routing rule (human-owned field)', 1, 0, 'GT'),
        mkField('crm_id', 'CRM id', null, 'system', 'Simulated CRM (set after approval)', 1, 0, 'SIM'),
        mkField('ai_fit_rationale', 'AI fit rationale', 'Multi-system data, stated budget and a near-term timeline fit the Data platform service line.', 'agent', 'account agent (mock model)', 0.78, 0, 'MOD'),
        mkField('ai_next_step', 'AI suggested next step', 'Reply within one business day offering a discovery call.', 'agent', 'account agent (mock model)', 0.81, 0, 'MOD'),
        mkField('ai_risk_flags', 'AI risk flags', 'Decision-maker not yet identified; headcount sources disagree.', 'agent', 'account agent (mock model)', 0.66, 0, 'MOD'),
      ],
      agent_state: {
        lifecycle: 'active', version: 1, updated_at: iso(s.now), mode: 'mock',
        summary: 'New inbound enquiry from Priya Raman (VP Operations) at Harbourline Freight Group: 14 hubs, data spread across five systems, budget approved this half. Fit is high. Two proposals are drafted: create CRM records, then send an intro reply. No customer reply yet.',
        summary_refs: ['lead:101', 'enrich:orgdata', 'enrich:firmo'],
        stakeholders: [{ name: 'Priya Raman', role: 'VP Operations', stance: 'champion', source_ref: 'lead:101' }],
        risks: [{ text: 'Only one stakeholder known; the economic buyer is not identified.', severity: 'medium', refs: ['lead:101'] }],
        commitments: [],
        open_questions: ['Who owns the budget?', 'Which of the five systems is the system of record?'],
        next_actions: [
          { id: 1, action: 'propose_crm_create', text: 'Create company, contact and deal in the CRM', status: 'pending_approval', proposal_id: 301, rationale: 'New account with a qualified lead.' },
          { id: 2, action: 'draft_message', text: 'Send intro reply offering a discovery call', status: 'pending_approval', proposal_id: 302, rationale: 'Lead asked for a conversation this week.' },
        ],
        last_decision: { action: 'draft_message', confidence: 0.81, would_change_mind: 'Evidence the sender is a vendor, a suppression entry, or an existing human thread.' },
      },
      interactions: [],
    };
    s.accounts.push(acct);
    addInteraction(acct, 'enquiry', 'Inbound enquiry received via website form', lead.message, 'lead:101', 'SCR');
    acct.interactions.unshift({ id: nextId('inter', 7001), at: iso(s.now), kind: 'agent', summary: 'Account agent provisioned; state v1 written (mock model)', detail: null, ref: 'agent_state:201', data_origin: 'MOD' });

    const evid = [
      { kind: 'enquiry', ref: 'lead:101', text: 'Enquiry: 14 hubs, five systems, budget approved this half, wants to talk this week.', source: 'website form', data_origin: 'SCR' as DataOrigin },
      { kind: 'enrichment', ref: 'enrich:orgdata', text: 'Headcount 1,150 (orgdata, conf 0.70) vs 840 (firmo, conf 0.55): conflict flagged, higher-confidence value used.', source: 'providers (simulated)', data_origin: 'SIM' as DataOrigin },
    ];
    const p1 = proposal({
      type: 'crm_write', status: 'pending', account_id: 201, account_name: acct.name,
      payload: { operations: [
        { object: 'company', action: 'create', local_ref: { type: 'account', id: 201 }, properties: { name: 'Harbourline Freight Group', domain: 'harbourline.example', industry: 'Freight and logistics', employee_count: 1150 } },
        { object: 'contact', action: 'create', local_ref: { type: 'contact', id: 601 }, properties: { name: 'Priya Raman', email: 'priya.raman@harbourline.example', title: 'VP Operations' } },
        { object: 'deal', action: 'create', local_ref: { type: 'opportunity', id: 501 }, properties: { name: 'Harbourline - data platform scoping', stage: 'Qualified', owner: 'maya@corvane.example' } },
      ] },
      evidence: evid, rationale: 'Qualified inbound lead with no existing CRM account (match score below 0.6).', confidence: 0.88, required_role: 'BDR',
      expires_at: iso(s.now + 7 * DAY), depends_on: null, block_reason: null, data_origins: ['SCR', 'SIM', 'MOD'],
    });
    const p2 = proposal({
      type: 'message', status: 'blocked', account_id: 201, account_name: acct.name,
      payload: {
        channel: 'email', contact_id: 601, resolved_recipient: 'priya.raman@harbourline.example', sender_identity: 'maya@corvane.example',
        subject: 'Re: Scoping a data platform for Harbourline',
        body: 'Hi Priya,\n\nThanks for getting in touch. Consolidating planning data from five systems is something we have helped other freight and logistics operators with, and a two-week discovery is usually enough to agree a scope.\n\nWould a 30 minute call this week work? I can do Thursday morning.\n\nBest,\nMaya Okafor\nCorvane Digital',
        links: [], attachments: [],
        claims: [
          { text: 'We have helped other freight and logistics operators consolidate planning data.', source_ref: 'case:corvane-cs-014' },
          { text: 'A two-week discovery is usually enough to agree a scope.', source_ref: 'playbook:discovery-v3' },
          { text: 'Thursday morning is available.', source_ref: 'calendar:maya-slots' },
        ],
        thread_id: 'thr-101', experiment_id: null, variant_id: null, design_hash: null,
      },
      evidence: [...evid, { kind: 'case_study', ref: 'case:corvane-cs-014', text: 'Case study: planning-data consolidation for a regional logistics operator (fictional).', source: 'case library', data_origin: 'GT' }],
      rationale: 'Lead asked to speak this week; reply offers a discovery call. Every claim is source-linked.', confidence: 0.81, required_role: 'AE',
      expires_at: iso(s.now + 3 * DAY), depends_on: p1.id, block_reason: `Waiting for proposal #${p1.id} (create CRM records): the contact must exist in the CRM before sending.`,
      data_origins: ['MOD', 'SCR', 'GT'],
    });
    void p2;
    mkRun('inbound_enquiry', 'event:lead.received', acct, [
      step(1, 'receive_enquiry', 'trigger', 'succeeded'),
      step(2, 'normalise_and_dedupe', 'code', 'succeeded', { note: 'No exact email match; free-mail and role mailbox rules not triggered.' }),
      step(3, 'triage_enquiry', 'llm', 'succeeded', { note: 'real_lead (0.93). Mock model: deterministic rule-based function.' }),
      step(4, 'match_account', 'code', 'succeeded', { note: 'Best candidate score 0.31, below 0.6: treat as a new account.' }),
      step(5, 'enrich_orgdata', 'tool', 'succeeded', { attempts: 2, sim_units: 3, error: { class: 'RetryableError', message: 'orgdata (simulated) 429 rate limit on attempt 1; retried after backoff.' } }),
      step(6, 'enrich_firmo', 'tool', 'succeeded', { sim_units: 2, note: 'Headcount differs 37% from orgdata: conflict recorded.' }),
      step(7, 'resolve_fields', 'code', 'succeeded', { note: 'Winner: orgdata 1,150 (higher confidence). Conflict flag set.' }),
      step(8, 'qualify_lead', 'llm', 'succeeded', { note: 'Fit 0.86 (high). Service line: Data platform.' }),
      step(9, 'account_agent_wake', 'agent', 'succeeded', { note: 'State v1 written. Actions: propose_crm_create, draft_message.' }),
      step(10, 'approval: create CRM records', 'approval', 'waiting', { waiting_for: `approval:${p1.id}` }),
      step(11, 'approval: send intro reply', 'approval', 'waiting', { waiting_for: `approval:${p2.id}` }),
    ], 'waiting');
    audit('system', 'system:demo', 'lead.received', 'lead:101', null, null, { enquiry_id: 'S01-golden-enquiry', origin: 'SCR' });
    audit('agent', 'agent:triage', 'lead.triaged', 'lead:101', null, null, { class: 'real_lead', fit: 0.86, mode: 'mock' });
    audit('system', 'system:enrichment', 'account.enriched', 'account:201', null, null, { conflicts: ['employees'] });
    return { ok: true, message: 'Enquiry submitted. A lead, an enriched account, an agent state and two linked proposals were created. Nothing external has happened yet.', clock: iso(s.now), created: { lead_id: 101, account_id: 201, proposal_ids: [p1.id, p2.id] } };
  }

  function deliverReply(): DemoResultOut {
    if (!s.flags.enquiry) return { ok: false, message: 'Submit the enquiry first.', clock: iso(s.now), created: {} };
    if (!s.flags.p2) return { ok: false, message: 'The intro reply has not been sent. Approve proposals #301 then #302 first.', clock: iso(s.now), created: {} };
    if (s.flags.reply) return { ok: false, message: 'The scripted reply was already delivered (idempotent).', clock: iso(s.now), created: {} };
    s.now += 6 * 3600_000;
    s.flags.reply = true;
    const a = accountOf(201)!;
    const text = 'Hi Maya, thanks. Thursday 10:00 CET works. We are consolidating five systems and would like a rough scope by the end of the month. I will bring in our CIO, Jonas Weber.';
    addInteraction(a, 'email_in', 'Customer reply received (scripted)', text, 'reply:S01-golden-reply', 'SCR');
    const st = a.agent_state!;
    st.version = 2; st.updated_at = iso(s.now);
    st.summary = 'Priya replied and accepted a discovery call on Thursday 10:00 CET. She will bring in the CIO (Jonas Weber), who is likely the economic buyer. She asked for a rough scope by month end. Intro reply was sent; CRM records exist. One task is proposed for the owner.';
    st.summary_refs = ['lead:101', 'reply:S01-golden-reply', `proposal:302`];
    st.stakeholders.push({ name: 'Jonas Weber', role: 'CIO (named by Priya)', stance: 'unknown', source_ref: 'reply:S01-golden-reply' });
    st.risks = [{ text: 'Rough scope requested by month end before discovery: risk of pricing or commitments being implied. Humans only.', severity: 'medium', refs: ['reply:S01-golden-reply'] }];
    st.commitments = [
      { party: 'Priya Raman', text: 'Attend a call Thursday 10:00 CET and bring the CIO', due: '2026-03-12', status: 'open', refs: ['reply:S01-golden-reply'] },
      { party: 'Corvane (proposed, not agreed)', text: 'Share a rough scope by end of March. Needs human confirmation; the agent cannot make commitments.', due: '2026-03-31', status: 'proposed', refs: ['reply:S01-golden-reply'] },
    ];
    st.open_questions = ['Who owns the budget (Jonas Weber?)', 'Which of the five systems is the system of record?'];
    const task = proposal({
      type: 'task', status: 'pending', account_id: 201, account_name: a.name,
      payload: { owner: 'user:maya', title: 'Book Thursday 10:00 CET discovery call and invite Jonas Weber', detail: 'Confirm calendar slot; do not promise a scope or price before discovery.', due_at: iso(s.now + DAY) },
      evidence: [{ kind: 'interaction', ref: 'reply:S01-golden-reply', text: '"Thursday 10:00 CET works ... I will bring in our CIO, Jonas Weber."', source: 'inbound email (scripted)', data_origin: 'SCR' }],
      rationale: 'Customer accepted a call and named a new stakeholder.', confidence: 0.84, required_role: 'AE', expires_at: iso(s.now + 5 * DAY), depends_on: null, block_reason: null, data_origins: ['SCR', 'MOD'],
    });
    st.next_actions = [
      { id: 3, action: 'recommend_task', text: task.payload.title, status: 'pending_approval', proposal_id: task.id, rationale: task.rationale },
      { id: 4, action: 'propose_field_change', text: 'Move deal to Discovery (human-owned field: not changed automatically)', status: 'proposed', proposal_id: null, rationale: 'Stage is human-owned; agent can only suggest.' },
    ];
    st.last_decision = { action: 'recommend_task', confidence: 0.84, would_change_mind: 'An out-of-office, bounce or unsubscribe on the thread.' };
    for (const f of a.fields) {
      if (f.key === 'ai_next_step') { f.value = 'Book the Thursday call and invite the CIO; keep scope and pricing out of writing until discovery.'; f.as_of = iso(s.now); }
      if (f.key === 'ai_risk_flags') { f.value = 'Economic buyer (CIO) not yet engaged; month-end scope request may imply commitments.'; f.as_of = iso(s.now); }
    }
    a.interactions.unshift({ id: nextId('inter', 7001), at: iso(s.now), kind: 'agent', summary: 'Account agent woke on reply: state v2, 1 task proposed (mock model)', detail: null, ref: `proposal:${task.id}`, data_origin: 'MOD' });
    mkRun('reply_routing', 'event:email.received', a, [
      step(1, 'receive_reply', 'trigger', 'succeeded'),
      step(2, 'match_thread', 'tool', 'succeeded', { note: 'Thread thr-101 matched by Message-Id.' }),
      step(3, 'hard_signal_check', 'code', 'succeeded', { note: 'Not a bounce, unsubscribe or out-of-office (deterministic rules run before the model).' }),
      step(4, 'classify_intent', 'llm', 'succeeded', { note: 'positive_interest (0.92). Mock model.' }),
      step(5, 'account_agent_wake', 'agent', 'succeeded', { note: 'State v2. Action: recommend_task.' }),
      step(6, 'approval: owner task', 'approval', 'waiting', { waiting_for: `approval:${task.id}` }),
    ], 'waiting');
    audit('system', 'system:demo', 'email.received', 'reply:S01-golden-reply', null, null, { thread: 'thr-101', origin: 'SCR' });
    audit('agent', 'agent:account', 'agent_state.updated', 'account:201', null, null, { version: 2, mode: 'mock' });
    return { ok: true, message: 'Scripted customer reply delivered (+6h). Account intelligence updated and one task proposed.', clock: iso(s.now), created: { account_id: 201, proposal_id: task.id } };
  }

  function advance(seconds: number): DemoResultOut {
    const before = s.now;
    s.now += Math.max(0, seconds) * 1000;
    const notes: string[] = [];
    for (const p of s.proposals) {
      if (['pending', 'blocked'].includes(p.status) && p.expires_at && Date.parse(p.expires_at) < s.now) {
        p.status = 'expired';
        notes.push(`proposal #${p.id} expired`);
        audit('system', 'system:orchestrator', 'proposal.expired', `proposal:${p.id}`, p.id, null, {});
      }
    }
    const run = s.runs.find((r) => r.status === 'parked');
    if (run) {
      const st = run.steps.find((x) => x.status === 'parked');
      if (st?.parked_until && Date.parse(st.parked_until) <= s.now) {
        st.status = 'succeeded'; st.finished_at = iso(s.now); st.attempts += 1;
        const nxt = run.steps.find((x) => x.status === 'waiting');
        if (nxt) { nxt.status = 'succeeded'; nxt.attempts = 1; nxt.waiting_for = null; nxt.finished_at = iso(s.now); }
        refreshRun(run); notes.push('parked enrichment run resumed and finished');
      }
    }
    if (s.flags.p2 && !s.flags.reply && !s.flags.noReplyAlert && s.now - Date.parse(s.proposals.find((p) => p.id === 302)!.execution!.executed_at!) >= 3 * DAY) {
      s.flags.noReplyAlert = true;
      const a = accountOf(201)!;
      s.alerts.unshift({ id: 2, opportunity_id: 501, opportunity_name: 'Harbourline - data platform scoping', account_id: 201, account_name: a.name, severity: 'medium', kind: 'no_reply', days_stalled: 3,
        reasons: ['Intro reply sent 3+ simulated days ago with no customer response.', 'Deal is still in Qualified with no next step booked.'], recommendation: 'Owner to follow up by phone; the agent will not send a second email without approval.', raised_at: iso(s.now), data_origin: 'SIM' });
      notes.push('pipeline alert raised for Harbourline');
    }
    const acct = accountOf(201) ?? s.accounts[0];
    mkRun('account_heartbeat', 'schedule:advance', acct, [
      step(1, 'check_material_change', 'code', 'succeeded', { note: 'Cheap check; the model is only called on a material change.' }),
      step(2, 'decide', 'conditional', 'succeeded', { note: 'no_action (expected most of the time, and measured).' }),
    ], 'succeeded');
    audit('system', 'system:demo', 'clock.advanced', null, null, null, { from: iso(before), to: iso(s.now), seconds });
    return { ok: true, message: `Simulated clock advanced ${Math.round(seconds / 3600 * 10) / 10}h.${notes.length ? ' ' + notes.join('; ') + '.' : ''}`, clock: iso(s.now), created: {} };
  }

  // ---------- decisions ----------
  function decide(id: number, body: DecisionIn): ProposalOut {
    const p = s.proposals.find((x) => x.id === id);
    if (!p) throw new ApiError(404, `Proposal ${id} not found`);
    if (p.depends_on) {
      const dep = s.proposals.find((x) => x.id === p.depends_on);
      if (dep && dep.status !== 'executed') throw new ApiError(409, `Blocked by proposal #${dep.id} (${dep.status})`);
    }
    const decidable = p.status === 'pending' || (p.status === 'blocked' && p.execution?.block_kind === 'soft');
    if (!decidable) throw new ApiError(409, `Proposal ${id} is ${p.status} and cannot be decided`);
    if (body.decision === 'reject' && !body.reason_code) throw new ApiError(422, 'A reason code is required to reject');
    const rec: DecisionRecord = { decision: body.decision, decided_by: body.decided_by, at: iso(s.now), reason_code: body.reason_code ?? null, comment: body.comment ?? null, edited: false };
    if (body.decision === 'reject') {
      p.decisions.push(rec); p.status = 'rejected';
      audit('human', body.decided_by, 'proposal.rejected', `proposal:${id}`, id, null, { reason_code: body.reason_code, comment: body.comment ?? null });
      for (const d of s.proposals.filter((x) => x.depends_on === id && x.status === 'blocked')) {
        d.status = 'superseded'; d.block_reason = `Dependency #${id} was rejected.`;
        audit('system', 'system:orchestrator', 'proposal.superseded', `proposal:${d.id}`, d.id, null, { dependency: id });
      }
      feedbackFromReject(p, body);
      return clone(p);
    }
    if (body.decision === 'approve_with_edits') {
      if (!body.edited_payload) throw new ApiError(422, 'edited_payload is required for approve_with_edits');
      const oldHash = p.payload_hash;
      rec.old_payload = p.payload;
      p.payload = body.edited_payload;
      p.payload_hash = payloadHash(p.id, p.type, p.payload);
      rec.edited = true; rec.old_hash = oldHash; rec.new_hash = p.payload_hash;
      audit('human', body.decided_by, 'proposal.edited', `proposal:${id}`, id, null, { old_hash: oldHash, new_hash: p.payload_hash });
    }
    p.decisions.push(rec);
    audit('human', body.decided_by, 'proposal.approved', `proposal:${id}`, id, null, { hash: p.payload_hash, edited: rec.edited, reason_code: body.reason_code ?? null });
    p.status = rec.edited ? 'approved_edited' : 'approved';
    p.execution = runGateway(p);
    if (p.execution.status === 'executed') {
      p.status = 'executed';
      audit('system', 'system:gateway', 'execution.completed', `proposal:${id}`, id, null, { adapter: p.execution.adapter, idempotency_key: p.execution.idempotency_key, hash: p.payload_hash });
      afterExecuted(p);
    } else {
      p.status = 'blocked';
      audit('system', 'system:gateway', 'execution.blocked', `proposal:${id}`, id, null, { kind: p.execution.block_kind, failed_step: p.execution.checks.find((c) => c.status === 'failed')?.step ?? null });
    }
    return clone(p);
  }

  function feedbackFromReject(p: ProposalOut, body: DecisionIn) {
    if (!body.comment) return;
    s.feedback.unshift({ id: nextId('fb', 3), kind: 'reviewer_edit', created_at: iso(s.now), account_id: p.account_id, account_name: p.account_name ?? null,
      summary: `Rejected proposal #${p.id} (${body.reason_code}).`, quotes: [{ text: body.comment, speaker: body.decided_by, source_ref: `proposal:${p.id}` }],
      tags_human: [body.reason_code ?? 'rejected'], tags_ai_suggested: [], reason_code: body.reason_code ?? null, created_by: body.decided_by, data_origin: 'HUM-real' });
  }

  // ---------- reads ----------
  const clone = <T,>(x: T): T => (x === undefined ? x : (JSON.parse(JSON.stringify(x)) as T));
  const wait = <T,>(v: () => T): Promise<T> =>
    new Promise((res, rej) => {
      const go = () => { try { res(clone(v())); } catch (e) { rej(e); } };
      latency > 0 ? setTimeout(go, latency) : go();
    });

  function detail(id: number): AccountDetail {
    const a = accountOf(id);
    if (!a) throw new ApiError(404, `Account ${id} not found`);
    const fields: ResolvedField[] = a.fields.map((f) => ({ ...f, ...fresh(Date.parse(f.as_of), s.now) }));
    return {
      ...row(a), fields, agent_state: a.agent_state, interactions: a.interactions,
      proposals: s.proposals.filter((p) => p.account_id === id), opportunities: s.opps.filter((o) => o.account_id === id),
    };
  }

  function overview() {
    const g = s.flags;
    const done = (b: boolean, d: string) => ({ done: b, detail: b ? d : null });
    return {
      clock: iso(s.now),
      counts: { leads: s.leads.length, accounts: s.accounts.length, open_proposals: s.proposals.filter((p) => ['pending', 'blocked', 'parked'].includes(p.status)).length,
        runs: s.runs.length, alerts: s.alerts.length, audit_events: s.audit.length },
      golden_thread: [
        { key: 'enquiry', label: 'Enquiry received', ...done(g.enquiry, 'Lead #101 (scripted enquiry)') },
        { key: 'triage', label: 'Triaged and scored', ...done(g.enquiry, 'real_lead, fit 0.86 (mock model)') },
        { key: 'account', label: 'Account enriched with provenance', ...done(g.enquiry, 'Account #201, headcount conflict flagged') },
        { key: 'agent', label: 'Account agent state built', ...done(g.enquiry, 'State v1, two proposals drafted') },
        { key: 'crm', label: 'CRM proposal approved and executed', ...done(g.p1, 'Proposal #301 via gateway') },
        { key: 'send', label: 'Intro reply approved and sent', ...done(g.p2, 'Proposal #302 via simulated outreach') },
        { key: 'reply', label: 'Customer reply delivered', ...done(g.reply, 'Scripted reply (SCR)') },
        { key: 'intel', label: 'Account intelligence updated', ...done(g.reply, 'State v2, new stakeholder, task proposed') },
      ],
      recent_activity: s.audit.slice(-6).reverse().map((r) => ({ at: r.at, text: `${r.event_type} (${r.actor_id})`, ref: r.entity_ref })),
    };
  }

  function verify() {
    let prev = GENESIS;
    for (const r of s.audit) {
      const { hash, ...rest } = r;
      if (r.prev_hash !== prev || sha256(canonicalJson(rest)) !== hash) return { ok: false, checked: r.seq - 1, first_bad_seq: r.seq };
      prev = hash;
    }
    return { ok: true, checked: s.audit.length, first_bad_seq: null };
  }

  function evals(): EvalSummaryOut { return evalFixture(s.evalRuns, iso(s.now)); }

  init();

  return {
    mode: 'mock',
    health: () => wait(() => ({ ok: true, db: true, clock: iso(s.now) })),
    config: () => wait(() => ({ llm_mode: 'mock', live_enabled: false, data_notice: NOTICE })),
    overview: () => wait(overview),
    leads: () => wait(() => [...s.leads].sort((a, b) => b.id - a.id)),
    accounts: () => wait(() => s.accounts.map(row)),
    account: (id) => wait(() => detail(id)),
    opportunities: () => wait(() => s.opps),
    alerts: () => wait(() => s.alerts),
    proposals: (status) => wait(() => s.proposals.filter((p) => !status || p.status === status).sort((a, b) => b.id - a.id)),
    proposal: (id) => wait(() => { const p = s.proposals.find((x) => x.id === id); if (!p) throw new ApiError(404, `Proposal ${id} not found`); return p; }),
    decide: (id, body) => wait(() => decide(id, body)),
    runs: () => wait(() => s.runs.map(({ steps: _s, ...r }) => { void _s; return r; }).sort((a, b) => b.id - a.id)),
    run: (id) => wait(() => { const r = s.runs.find((x) => x.id === id); if (!r) throw new ApiError(404, `Run ${id} not found`); return r; }),
    audit: (limit = 200) => wait(() => s.audit.slice(-limit).reverse()),
    verifyAudit: () => wait(verify),
    events: (limit = 100) => wait(() => s.events.slice(-limit).reverse()),
    evals: () => wait(evals),
    runEvals: () => wait(() => { s.evalRuns += 1; audit('system', 'system:eval', 'eval.run', `eval:${s.evalRuns}`, null, null, { mode: 'mock' }); return evals(); }),
    feedback: () => wait(() => s.feedback),
    submitLostDealReview: (b: LostDealReviewIn) => wait(() => {
      const a = accountOf(b.account_id);
      const id = nextId('fb', 3);
      s.feedback.unshift({ id, kind: 'lost_deal_review', created_at: iso(s.now), account_id: b.account_id, account_name: a?.name ?? null,
        summary: b.primary_reason, quotes: b.verbatim_quotes.filter(Boolean).map((t) => ({ text: t, speaker: null, source_ref: null })),
        tags_human: [b.reason_code, ...(b.competitor ? [`competitor:${b.competitor}`] : [])], tags_ai_suggested: [], reason_code: b.reason_code, created_by: b.reviewer, data_origin: 'HUM-real' });
      audit('human', b.reviewer, 'feedback.lost_deal_review', `feedback:${id}`, null, null, { reason_code: b.reason_code });
      return { id, feedback_id: id, created_at: iso(s.now), ok: true };
    }),
    demoEnquiry: () => wait(submitEnquiry),
    demoReply: () => wait(deliverReply),
    demoAdvance: (seconds) => wait(() => advance(seconds)),
    demoReset: () => wait(() => { init(); return { ok: true, message: 'Mock state reset to the seed data.', clock: iso(s.now), created: {} }; }),
    mockTamper: () => wait(() => { const r = s.audit[Math.min(2, s.audit.length - 1)]; r.data = { ...r.data, note: 'TAMPERED (mock demonstration)' }; }),
  };
}

export type { AccountDetail };
