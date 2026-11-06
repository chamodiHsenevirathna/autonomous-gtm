"""Response/request models for the dashboard API, transcribed from frontend/API_SPEC.md and frontend/src/api/types.ts.
Strict on purpose: tests validate every endpoint against these. Timestamps are ISO strings on the simulated clock."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

DataOrigin = Literal["GT", "SIM", "SCR", "MOD", "HUM-sim", "HUM-real", "PLT"]
EvidenceBasis = Literal["measured_on_simulation", "machinery_check", "modelled_impact"]
Lifecycle = Literal["unprovisioned", "active", "quiet", "dormant", "needs_attention", "archived"]
ProposalStatus = Literal["pending", "approved", "approved_edited", "rejected", "expired", "superseded", "executing", "parked", "blocked", "executed", "failed"]


class S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthOut(S):
    ok: bool
    db: bool
    clock: str


class ConfigOut(S):
    llm_mode: str
    live_enabled: bool
    data_notice: str


class GoldenStep(S):
    key: Literal["enquiry", "triage", "account", "agent", "crm", "send", "reply", "intel"]
    label: str
    done: bool
    detail: str | None


class Activity(S):
    at: str
    text: str
    ref: str | None


class Counts(S):
    leads: int
    accounts: int
    open_proposals: int
    runs: int
    alerts: int
    audit_events: int


class OverviewOut(S):
    clock: str
    counts: Counts
    golden_thread: list[GoldenStep]
    recent_activity: list[Activity]


class LeadOut(S):
    id: int
    received_at: str
    name: str
    email: str
    company: str | None
    message: str
    triage_class: Literal["real_lead", "existing_customer", "vendor", "recruiter", "spam", "unclear"] | None
    fit_score: float | None
    fit_band: Literal["high", "medium", "low"] | None
    status: Literal["new", "triaged", "held", "qualified", "disqualified", "nurture", "converted"]
    held: bool
    held_reason: str | None
    account_id: int | None
    service_line: str | None
    data_origins: list[DataOrigin]


class AccountRow(S):
    id: int
    name: str
    domain: str | None
    industry: str | None
    employees: int | None
    lifecycle: Lifecycle
    owner: str | None
    open_proposals: int
    last_interaction_at: str | None
    fit_band: Literal["high", "medium", "low"] | None
    data_origins: list[DataOrigin]


class Alternative(S):
    source: str
    value: str | int | float | None
    confidence: float
    as_of: str


class ResolvedFieldOut(S):
    key: str
    label: str
    value: str | int | float | None
    owner: Literal["provider", "human", "agent", "system"]
    source: str
    confidence: float
    as_of: str
    freshness_days: int
    freshness: Literal["fresh", "aging", "stale"]
    conflict: bool
    alternatives: list[Alternative]
    data_origin: DataOrigin


class Stakeholder(S):
    name: str
    role: str
    stance: Literal["champion", "neutral", "unknown", "blocker"]
    source_ref: str


class Risk(S):
    text: str
    severity: Literal["low", "medium", "high"]
    refs: list[str]


class Commitment(S):
    party: str
    text: str
    due: str | None
    status: Literal["open", "proposed", "done"]
    refs: list[str]


class NextAction(S):
    id: int
    action: str
    text: str
    status: Literal["proposed", "pending_approval", "done", "dismissed"]
    proposal_id: int | None
    rationale: str | None


class LastDecision(S):
    action: str
    confidence: float
    would_change_mind: str


class AgentStateOut(S):
    lifecycle: Lifecycle
    version: int
    updated_at: str
    mode: str
    summary: str
    summary_refs: list[str]
    stakeholders: list[Stakeholder]
    risks: list[Risk]
    commitments: list[Commitment]
    open_questions: list[str]
    next_actions: list[NextAction]
    last_decision: LastDecision | None


class Interaction(S):
    id: int
    at: str
    kind: Literal["enquiry", "email_out", "email_in", "crm", "agent", "system", "human"]
    summary: str
    detail: str | None
    ref: str | None
    data_origin: DataOrigin


class Evidence(S):
    kind: str
    ref: str
    text: str
    source: str | None
    data_origin: DataOrigin | None


class DecisionRec(S):
    decision: Literal["approve", "approve_with_edits", "reject"]
    decided_by: str
    at: str
    reason_code: str | None
    comment: str | None
    edited: bool
    old_hash: str | None
    new_hash: str | None


class Check(S):
    step: int
    name: str
    status: Literal["passed", "failed", "skipped"]
    detail: str


class ExecutionOut(S):
    status: Literal["executed", "blocked", "failed", "parked", "executing"]
    adapter: str
    idempotency_key: str
    executed_at: str | None
    outcome: str
    hash_verified: bool
    approval_consumed: bool
    block_kind: Literal["soft", "hard"] | None
    external_ref: str | None
    checks: list[Check]


class ProposalOut(S):
    id: int
    type: str
    gate_id: str
    status: ProposalStatus
    account_id: int | None
    account_name: str | None
    payload: dict[str, Any]
    payload_hash: str
    evidence: list[Evidence]
    rationale: str | None
    confidence: float | None
    required_role: str | None
    created_at: str
    expires_at: str | None
    depends_on: int | None
    block_reason: str | None
    decisions: list[DecisionRec]
    execution: ExecutionOut | None
    data_origins: list[DataOrigin]


class OpportunityRow(S):
    id: int
    account_id: int
    account_name: str
    name: str
    stage: str
    amount: float | None
    currency: str
    owner: str | None
    days_in_stage: int
    status: Literal["open", "won", "lost"]
    data_origin: DataOrigin


class AccountDetail(AccountRow):
    fields: list[ResolvedFieldOut]
    agent_state: AgentStateOut | None
    interactions: list[Interaction]
    proposals: list[ProposalOut]
    opportunities: list[OpportunityRow]


class PipelineAlert(S):
    id: int
    opportunity_id: int
    opportunity_name: str
    account_id: int
    account_name: str
    severity: Literal["low", "medium", "high"]
    kind: Literal["stalled", "no_reply", "no_next_step", "champion_change"]
    days_stalled: int
    reasons: list[str]
    recommendation: str
    raised_at: str
    data_origin: DataOrigin


class RunRow(S):
    id: int
    workflow: str
    status: Literal["running", "succeeded", "failed", "parked", "waiting", "dead_letter"]
    trigger: str
    account_id: int | None
    account_name: str | None
    started_at: str
    finished_at: str | None
    steps_total: int
    steps_done: int
    cost_usd: float


class StepError(S):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    class_: str
    message: str


class RunStep(S):
    id: int
    seq: int
    node: str
    node_type: Literal["trigger", "code", "tool", "llm", "agent", "conditional", "map", "reduce", "wait", "approval"]
    status: Literal["succeeded", "failed", "parked", "waiting", "running", "skipped", "dead_letter"]
    attempts: int
    started_at: str | None
    finished_at: str | None
    error: dict[str, str] | None          # {"class": ..., "message": ...}
    parked_until: str | None
    waiting_for: str | None
    cost_usd: float
    sim_units: float
    model_mode: str | None
    note: str | None


class RunDetail(RunRow):
    steps: list[RunStep]


class AuditRow(S):
    seq: int
    at: str
    actor_type: str
    actor_id: str
    event_type: str
    entity_ref: str | None
    proposal_id: int | None
    run_id: int | None
    data: dict[str, Any]
    hash: str
    prev_hash: str


class AuditVerifyOut(S):
    ok: bool
    checked: int
    first_bad_seq: int | None


class EventRow(S):
    id: int
    at: str
    event_type: str
    entity_ref: str | None
    source: str
    dedupe_key: str | None


class EvalMetric(S):
    name: str
    value: float | int | str
    target: float | int | str | None
    unit: str | None
    passed: bool | None
    evidence_basis: EvidenceBasis


class EvalScenario(S):
    id: str
    title: str
    description: str
    passed: bool
    evidence_basis: EvidenceBasis
    data_origins: list[DataOrigin]
    metrics: list[EvalMetric]
    detail: str | None


class InvariantOut(S):
    name: str
    passed: bool
    violations: list[dict[str, Any]]


class EvalSummaryOut(S):
    run_id: int
    ran_at: str | None
    mode: str
    notice: str
    totals: dict[str, int]
    invariants: list[InvariantOut]
    scenarios: list[EvalScenario]
    baseline: dict[str, Any]


class Quote(S):
    text: str
    speaker: str | None
    source_ref: str | None


class FeedbackRow(S):
    id: int
    kind: Literal["lost_deal_review", "reviewer_edit", "customer_reply", "win_note"]
    created_at: str
    account_id: int | None
    account_name: str | None
    summary: str
    quotes: list[Quote]
    tags_human: list[str]
    tags_ai_suggested: list[str]
    reason_code: str | None
    created_by: str
    data_origin: DataOrigin


class LostDealReviewIn(BaseModel):
    account_id: int | None = None
    opportunity_id: int | None = None
    reason_code: str
    primary_reason: str
    competitor: str | None = None
    could_we_have_won: Literal["yes", "maybe", "no"]
    what_would_change_it: str = ""
    verbatim_quotes: list[str] = []
    reviewer: str


class LostDealReviewOut(S):
    id: int
    feedback_id: int
    created_at: str
    ok: bool


class DemoResultOut(S):
    ok: bool
    message: str
    clock: str
    created: dict[str, Any]
