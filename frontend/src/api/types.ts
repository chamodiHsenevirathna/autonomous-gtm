/**
 * API DTOs. Snake_case, mirroring backend/gtm/contracts/api.py. DTOs that file does not define are
 * specified here and in frontend/API_SPEC.md (keep both in sync).
 * All timestamps are ISO-8601 UTC strings on the SIMULATED clock.
 */

export type DataOrigin = 'GT' | 'SIM' | 'SCR' | 'MOD' | 'HUM-sim' | 'HUM-real' | 'PLT';
export type EvidenceBasis = 'measured_on_simulation' | 'machinery_check' | 'modelled_impact';

// ---------- contracts/api.py ----------
export interface HealthOut {
  ok: boolean;
  db: boolean;
  clock: string;
}

export interface ConfigOut {
  llm_mode: string; // 'mock' | 'replay' | 'live'
  live_enabled: boolean;
  data_notice: string;
}

export type DecisionKind = 'approve' | 'approve_with_edits' | 'reject';

export interface DecisionIn {
  decision: DecisionKind;
  decided_by: string;
  edited_payload?: Record<string, unknown> | null;
  reason_code?: string | null;
  comment?: string | null;
}

export type ProposalStatus =
  | 'pending'
  | 'approved'
  | 'approved_edited'
  | 'rejected'
  | 'expired'
  | 'superseded'
  | 'executing'
  | 'parked'
  | 'blocked'
  | 'executed'
  | 'failed';

export interface EvidenceItem {
  kind: string; // 'enquiry' | 'enrichment' | 'case_study' | 'playbook' | 'interaction' ...
  ref: string; // stable source reference, e.g. 'lead:101'
  text: string;
  source?: string | null;
  data_origin?: DataOrigin | null;
}

export interface DecisionRecord {
  decision: DecisionKind;
  decided_by: string;
  at: string;
  reason_code: string | null;
  comment: string | null;
  edited: boolean;
  old_hash?: string | null; // set when the edit changed the payload hash
  new_hash?: string | null;
  old_payload?: Record<string, any> | null; // set when edited: payload before the edit (for the diff view)
}

export interface GatewayCheck {
  step: number; // 1..13 per docs/execution-architecture.md 13.2
  name: string;
  status: 'passed' | 'failed' | 'skipped';
  detail: string;
}

export interface ExecutionOut {
  status: 'executed' | 'blocked' | 'failed' | 'parked' | 'executing';
  adapter: string; // 'crm.write' | 'outreach.send' | ...
  idempotency_key: string;
  executed_at: string | null;
  outcome: string; // human-readable
  hash_verified: boolean;
  approval_consumed: boolean;
  block_kind?: 'soft' | 'hard' | null;
  external_ref?: string | null;
  checks: GatewayCheck[];
}

export interface ProposalOut {
  id: number;
  type: string; // crm_write | message | task | lead_disposition | field_change | ...
  gate_id: string;
  status: ProposalStatus;
  account_id: number | null;
  account_name?: string | null;
  payload: Record<string, any>;
  payload_hash: string;
  evidence: EvidenceItem[];
  rationale: string | null;
  confidence: number | null;
  required_role: string | null;
  created_at: string;
  expires_at: string | null;
  depends_on?: number | null;
  block_reason?: string | null;
  decisions: DecisionRecord[];
  execution: ExecutionOut | null;
  data_origins: DataOrigin[];
}

export interface AuditRow {
  seq: number;
  at: string;
  actor_type: string;
  actor_id: string;
  event_type: string;
  entity_ref: string | null;
  proposal_id: number | null;
  run_id: number | null;
  data: Record<string, any>;
  hash: string;
  prev_hash: string;
}

export interface AuditVerifyOut {
  ok: boolean;
  checked: number;
  first_bad_seq?: number | null;
}

export interface DemoResultOut {
  ok: boolean;
  message: string;
  clock: string;
  created: Record<string, any>;
}

// ---------- DTOs defined by the frontend (API_SPEC.md) ----------
export interface GoldenStep {
  key: string;
  label: string;
  done: boolean;
  detail: string | null;
}

export interface OverviewOut {
  clock: string;
  counts: {
    leads: number;
    accounts: number;
    open_proposals: number;
    runs: number;
    alerts: number;
    audit_events: number;
  };
  golden_thread: GoldenStep[];
  recent_activity: { at: string; text: string; ref: string | null }[];
}

export type TriageClass =
  | 'real_lead'
  | 'existing_customer'
  | 'vendor'
  | 'recruiter'
  | 'spam'
  | 'unclear';
export type FitBand = 'high' | 'medium' | 'low';
export type LeadStatus = 'new' | 'triaged' | 'held' | 'qualified' | 'disqualified' | 'nurture' | 'converted';

export interface LeadOut {
  id: number;
  received_at: string;
  name: string;
  email: string;
  company: string | null;
  message: string;
  triage_class: TriageClass | null;
  fit_score: number | null; // 0..1
  fit_band: FitBand | null;
  status: LeadStatus;
  held: boolean;
  held_reason: string | null;
  account_id: number | null;
  service_line: string | null;
  data_origins: DataOrigin[];
}

export type LifecycleState =
  | 'unprovisioned'
  | 'active'
  | 'quiet'
  | 'dormant'
  | 'needs_attention'
  | 'archived';

export interface AccountRow {
  id: number;
  name: string;
  domain: string | null;
  industry: string | null;
  employees: number | null;
  lifecycle: LifecycleState;
  owner: string | null;
  open_proposals: number;
  last_interaction_at: string | null;
  fit_band: FitBand | null;
  data_origins: DataOrigin[];
}

export type FieldOwner = 'provider' | 'human' | 'agent' | 'system';

export interface FieldAlternative {
  source: string;
  value: string | number | null;
  confidence: number;
  as_of: string;
}

export interface ResolvedField {
  key: string; // 'employees', 'ai_summary', ...
  label: string;
  value: string | number | null;
  owner: FieldOwner; // 'agent' => key starts with 'ai_'
  source: string; // winning source
  confidence: number; // 0..1
  as_of: string; // when the winning observation was made
  freshness_days: number; // age relative to the simulated clock
  freshness: 'fresh' | 'aging' | 'stale';
  conflict: boolean;
  alternatives: FieldAlternative[]; // losing candidates (empty when no conflict)
  data_origin: DataOrigin;
}

export interface Stakeholder {
  name: string;
  role: string;
  stance: 'champion' | 'neutral' | 'unknown' | 'blocker';
  source_ref: string;
}
export interface RiskItem {
  text: string;
  severity: 'low' | 'medium' | 'high';
  refs: string[];
}
export interface CommitmentItem {
  party: string;
  text: string;
  due: string | null;
  status: 'open' | 'proposed' | 'done';
  refs: string[];
}
export interface NextAction {
  id: number;
  action: string; // action menu value: recommend_task | draft_message | propose_crm_create | no_action ...
  text: string;
  status: 'proposed' | 'pending_approval' | 'done' | 'dismissed';
  proposal_id: number | null;
  rationale: string | null;
}

export interface AgentState {
  lifecycle: LifecycleState;
  version: number;
  updated_at: string;
  mode: string; // 'mock' | 'replay' | 'live'
  summary: string;
  summary_refs: string[];
  stakeholders: Stakeholder[];
  risks: RiskItem[];
  commitments: CommitmentItem[];
  open_questions: string[];
  next_actions: NextAction[];
  last_decision: { action: string; confidence: number; would_change_mind: string } | null;
}

export interface InteractionOut {
  id: number;
  at: string;
  kind: 'enquiry' | 'email_out' | 'email_in' | 'crm' | 'agent' | 'system' | 'human';
  summary: string;
  detail: string | null;
  ref: string | null;
  data_origin: DataOrigin;
}

export interface AccountDetail extends AccountRow {
  fields: ResolvedField[];
  agent_state: AgentState | null;
  interactions: InteractionOut[];
  proposals: ProposalOut[];
  opportunities: OpportunityRow[];
}

export interface OpportunityRow {
  id: number;
  account_id: number;
  account_name: string;
  name: string;
  stage: string;
  amount: number | null;
  currency: string;
  owner: string | null;
  days_in_stage: number;
  status: 'open' | 'won' | 'lost';
  data_origin: DataOrigin;
}

export interface PipelineAlert {
  id: number;
  opportunity_id: number;
  opportunity_name: string;
  account_id: number;
  account_name: string;
  severity: 'low' | 'medium' | 'high';
  kind: 'stalled' | 'no_reply' | 'no_next_step' | 'champion_change';
  days_stalled: number;
  reasons: string[];
  recommendation: string;
  raised_at: string;
  data_origin: DataOrigin;
}

export type RunStatus = 'running' | 'succeeded' | 'failed' | 'parked' | 'waiting' | 'dead_letter';
export type NodeType =
  | 'trigger'
  | 'code'
  | 'tool'
  | 'llm'
  | 'agent'
  | 'conditional'
  | 'map'
  | 'reduce'
  | 'wait'
  | 'approval';
export type StepStatus = 'succeeded' | 'failed' | 'parked' | 'waiting' | 'running' | 'skipped' | 'dead_letter';

export interface RunRow {
  id: number;
  workflow: string;
  status: RunStatus;
  trigger: string;
  account_id: number | null;
  account_name: string | null;
  started_at: string;
  finished_at: string | null;
  steps_total: number;
  steps_done: number;
  cost_usd: number; // model cost (mock => 0). Provider cost is in simulated units, see RunStep.sim_units
}

export interface RunStep {
  id: number;
  seq: number;
  node: string;
  node_type: NodeType;
  status: StepStatus;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  error: { class: string; message: string } | null; // last error (may exist even if the step later succeeded)
  parked_until: string | null;
  waiting_for: string | null; // e.g. 'approval:301'
  cost_usd: number;
  sim_units: number; // simulated provider units (NOT money)
  model_mode: string | null; // 'mock' for llm/agent nodes
  note: string | null;
}

export interface RunDetail extends RunRow {
  steps: RunStep[];
}

export interface EventRow {
  id: number;
  at: string;
  event_type: string;
  entity_ref: string | null;
  source: string;
  dedupe_key: string | null;
}

export interface EvalMetric {
  name: string;
  value: number | string;
  target: number | string | null;
  unit: string | null;
  passed: boolean | null;
  evidence_basis: EvidenceBasis;
}

export interface EvalScenario {
  id: string; // 'S01'
  title: string;
  description: string;
  passed: boolean;
  evidence_basis: EvidenceBasis;
  data_origins: DataOrigin[];
  metrics: EvalMetric[];
  detail: string | null;
}

export interface InvariantResult {
  name: string;
  passed: boolean;
  violations: Record<string, any>[];
}

export interface EvalSummaryOut {
  run_id?: number; // absent before the first run
  ran_at: string;
  mode: string; // llm mode used, 'mock'
  notice: string; // honest statement; frontend also renders its own
  totals: { passed: number; failed: number; total: number };
  invariants: InvariantResult[];
  scenarios: EvalScenario[];
  baseline?: { compared: boolean; regressions: number };
}

export interface FeedbackQuote {
  text: string; // verbatim
  speaker: string | null;
  source_ref: string | null;
}

export interface FeedbackRow {
  id: number;
  kind: 'lost_deal_review' | 'reviewer_edit' | 'customer_reply' | 'win_note';
  created_at: string;
  account_id: number | null;
  account_name: string | null;
  summary: string;
  quotes: FeedbackQuote[];
  tags_human: string[];
  tags_ai_suggested: string[]; // shown separately, never merged with human tags
  reason_code: string | null;
  created_by: string;
  data_origin: DataOrigin;
}

export interface LostDealReviewIn {
  account_id: number | null;
  opportunity_id: number | null;
  reason_code: string;
  primary_reason: string;
  competitor: string | null;
  could_we_have_won: 'yes' | 'maybe' | 'no';
  what_would_change_it: string;
  verbatim_quotes: string[];
  reviewer: string;
}

export interface LostDealReviewOut {
  id: number;
  feedback_id: number;
  created_at: string;
  ok: boolean;
}
