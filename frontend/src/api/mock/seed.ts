import type { EvalSummaryOut, FeedbackRow } from '../types';

export const NOTICE =
  'All data is synthetic (fictional consultancy Corvane Digital). Model outputs are produced by a deterministic mock unless live mode is enabled.';

export const EVAL_NOTICE =
  'These results were produced on a synthetic world with a deterministic mock model. They show that the machinery behaves as designed and how accurate it is on simulated data. They are NOT evidence of real-world conversion, revenue or lead-quality improvement.';

/** Static evaluation fixture used in mock mode only (the real numbers come from gtm.eval). */
export function evalFixture(runId: number, ranAt: string): EvalSummaryOut {
  const scenarios: EvalSummaryOut['scenarios'] = [
    {
      id: 'S01', title: 'Golden thread: enquiry to sent reply',
      description: 'Inbound enquiry becomes a lead, an enriched account and two linked proposals; nothing is sent before approval; the scripted reply updates the account agent state.',
      passed: true, evidence_basis: 'machinery_check', data_origins: ['SCR', 'SIM', 'MOD'],
      metrics: [
        { name: 'External sends before approval', value: 0, target: 0, unit: 'count', passed: true, evidence_basis: 'machinery_check' },
        { name: 'Reply reflected in agent state within one wake', value: 'yes', target: 'yes', unit: null, passed: true, evidence_basis: 'machinery_check' },
      ],
      detail: 'The expected outcome is scripted (SCR), so this checks the plumbing, not model skill.',
    },
    {
      id: 'S06', title: 'Spam / vendor / recruiter hold',
      description: 'Vendor, recruiter and spam enquiries are held (reversible), never auto-archived; real leads are not held.',
      passed: true, evidence_basis: 'measured_on_simulation', data_origins: ['GT', 'MOD'],
      metrics: [
        { name: 'Held-item precision', value: 0.97, target: '>= 0.95', unit: 'ratio', passed: true, evidence_basis: 'measured_on_simulation' },
        { name: 'Real leads held without digest entry', value: 0, target: 0, unit: 'count', passed: true, evidence_basis: 'measured_on_simulation' },
        { name: 'Labelled enquiries (N)', value: 48, target: '>= 40', unit: 'count', passed: true, evidence_basis: 'measured_on_simulation' },
      ],
      detail: 'Labels derive from generator ground truth by rules separate from the rubric prompt. Accuracy applies to the simulated world only.',
    },
    {
      id: 'S09', title: 'Provider conflict resolution',
      description: 'Where two simulated providers disagree on headcount, the winner is within 10% of ground truth and conflicts over 20% are flagged.',
      passed: true, evidence_basis: 'measured_on_simulation', data_origins: ['GT', 'SIM'],
      metrics: [
        { name: 'Winner within +-10% of truth', value: 0.92, target: '>= 0.90', unit: 'ratio', passed: true, evidence_basis: 'measured_on_simulation' },
        { name: 'Conflicts flagged when providers differ >20%', value: 1.0, target: 1.0, unit: 'ratio', passed: true, evidence_basis: 'measured_on_simulation' },
      ],
      detail: null,
    },
    {
      id: 'S21', title: 'Human email supersedes pending proposal',
      description: 'A scripted human email on the thread marks the pending draft superseded within one wake cycle.',
      passed: true, evidence_basis: 'machinery_check', data_origins: ['SCR'],
      metrics: [{ name: 'Sends from superseded proposal', value: 0, target: 0, unit: 'count', passed: true, evidence_basis: 'machinery_check' }],
      detail: null,
    },
    {
      id: 'S22', title: 'Stalled deal flagged',
      description: 'A seeded deal stalled at day 45 is flagged within one heartbeat with a recommendation; the flag clears after human action.',
      passed: true, evidence_basis: 'machinery_check', data_origins: ['PLT'],
      metrics: [{ name: 'Heartbeats to flag after threshold', value: 1, target: '<= 1', unit: 'count', passed: true, evidence_basis: 'machinery_check' }],
      detail: 'The stall was planted (PLT), so this shows the detector fires, not how often real deals stall.',
    },
    {
      id: 'S43', title: 'Commercial-content screen blocks price in draft',
      description: 'A human edit that inserts a price is blocked at the gateway on the final hash; discount terms cannot be released.',
      passed: true, evidence_basis: 'machinery_check', data_origins: ['SCR'],
      metrics: [{ name: 'Executions with price/discount text', value: 0, target: 0, unit: 'count', passed: true, evidence_basis: 'machinery_check' }],
      detail: null,
    },
    {
      id: 'S49', title: 'Unsubscribe race window',
      description: 'An unsubscribe arriving after the approval-consumption step may still produce one in-flight message; everything after is blocked. The window is measured, not hidden.',
      passed: false, evidence_basis: 'measured_on_simulation', data_origins: ['SCR', 'SIM'],
      metrics: [
        { name: 'Messages after suppression (beyond in-flight)', value: 0, target: 0, unit: 'count', passed: true, evidence_basis: 'measured_on_simulation' },
        { name: 'In-flight window', value: 1.4, target: '<= 1.0', unit: 'sim seconds', passed: false, evidence_basis: 'measured_on_simulation' },
      ],
      detail: 'Known gap: the residual window exceeds the target in the simulator. Reported as a failure on purpose rather than tuned away.',
    },
    {
      id: 'M01', title: 'Illustrative hours saved on enquiry triage',
      description: 'Back-of-envelope: minutes saved per enquiry times assumed volume. Assumptions are stated in the report.',
      passed: true, evidence_basis: 'modelled_impact', data_origins: ['MOD'],
      metrics: [
        { name: 'Assumed minutes saved per enquiry', value: 6, target: null, unit: 'min (assumption)', passed: null, evidence_basis: 'modelled_impact' },
        { name: 'Illustrative hours / month at 120 enquiries', value: 12, target: null, unit: 'h (modelled)', passed: null, evidence_basis: 'modelled_impact' },
      ],
      detail: 'Modelled from stated assumptions. Not measured. No claim is made about real time saved.',
    },
  ];
  const invariants = [
    'no_execution_without_consumed_approval', 'approval_hash_matches_execution_hash', 'no_effect_after_suppression',
    'audit_chain_verifies', 'no_duplicate_side_effects_per_idempotency_key', 'human_field_changes_trace_to_approved_proposal',
    'no_tool_call_outside_principal_profile',
  ].map((name) => ({ name, passed: true, violations: [] }));
  const failed = scenarios.filter((s) => !s.passed).length;
  return {
    run_id: runId, ran_at: ranAt, mode: 'mock', notice: EVAL_NOTICE,
    totals: { passed: scenarios.length - failed, failed, total: scenarios.length },
    invariants, scenarios, baseline: { compared: true, regressions: 0 },
  };
}

export const seedFeedback = (at: string): FeedbackRow[] => [
  {
    id: 1, kind: 'lost_deal_review', created_at: at, account_id: 2, account_name: 'Aldous & Pryce LLP',
    summary: 'Lost to an incumbent advisory firm after a long procurement cycle.',
    quotes: [{ text: 'We liked the approach, but the partners wanted a firm they already had a panel agreement with.', speaker: 'Managing partner (scripted)', source_ref: 'interaction:9001' }],
    tags_human: ['incumbent', 'procurement'], tags_ai_suggested: ['panel-agreement', 'long-sales-cycle'], reason_code: 'lost_to_incumbent',
    created_by: 'user:maya', data_origin: 'SCR',
  },
  {
    id: 2, kind: 'reviewer_edit', created_at: at, account_id: 3, account_name: 'Tidewater Energy Partners',
    summary: 'Reviewer shortened a draft and removed a claim without a source.',
    quotes: [{ text: 'Cut the sentence about regulator experience, we cannot back it.', speaker: 'Maya Okafor (simulated reviewer)', source_ref: 'proposal:290' }],
    tags_human: ['unsupported-claim'], tags_ai_suggested: [], reason_code: 'inaccurate_claim', created_by: 'user:maya', data_origin: 'HUM-sim',
  },
];
