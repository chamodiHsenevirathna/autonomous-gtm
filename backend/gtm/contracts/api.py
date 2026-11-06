"""Dashboard API contract (summary). Endpoint list is authoritative; response bodies are pydantic models implemented by
gtm.api (JSON, camelCase NOT used; snake_case). Frontend builds against these shapes."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel

ENDPOINTS = {
    "GET /api/health": "HealthOut",
    "GET /api/config": "ConfigOut",
    "GET /api/overview": "OverviewOut",
    "GET /api/leads": "list[LeadOut]",
    "GET /api/accounts": "list[AccountRow]",
    "GET /api/accounts/{id}": "AccountDetail",
    "GET /api/opportunities": "list[OpportunityRow]",
    "GET /api/pipeline/alerts": "list[PipelineAlert]",
    "GET /api/proposals?status=": "list[ProposalOut]",
    "GET /api/proposals/{id}": "ProposalOut",
    "POST /api/proposals/{id}/decision": "ProposalOut  (body: DecisionIn)",
    "GET /api/runs": "list[RunRow]",
    "GET /api/runs/{id}": "RunDetail",
    "GET /api/audit?limit=": "list[AuditRow]",
    "GET /api/audit/verify": "AuditVerifyOut",
    "GET /api/events?limit=": "list[EventRow]",
    "GET /api/evals": "EvalSummaryOut",
    "POST /api/evals/run": "EvalSummaryOut",
    "GET /api/feedback": "list[FeedbackRow]",
    "POST /api/lost-deal-reviews": "LostDealReviewOut (body: LostDealReviewIn)",
    "POST /api/demo/enquiry": "DemoResultOut (body: {enquiry_id})",
    "POST /api/demo/reply": "DemoResultOut (body: {reply_id})",
    "POST /api/demo/advance": "DemoResultOut (body: {seconds})",
    "POST /api/demo/reset": "DemoResultOut",
}


class HealthOut(BaseModel):
    ok: bool
    db: bool
    clock: datetime


class ConfigOut(BaseModel):
    llm_mode: str
    live_enabled: bool                 # always False in this build unless explicitly enabled
    data_notice: str = "All data is synthetic. Model outputs are produced by a deterministic mock unless live mode is enabled."


class DecisionIn(BaseModel):
    decision: Literal["approve", "approve_with_edits", "reject"]
    decided_by: str                    # principal id, e.g. 'user:maya'
    edited_payload: dict | None = None
    reason_code: str | None = None
    comment: str | None = None


class ProposalOut(BaseModel):
    id: int
    type: str
    gate_id: str
    status: str
    account_id: int | None
    account_name: str | None = None
    payload: dict
    payload_hash: str
    evidence: list[dict]
    rationale: str | None
    confidence: float | None
    required_role: str | None
    created_at: datetime
    expires_at: datetime | None
    depends_on: int | None = None
    block_reason: str | None = None
    decisions: list[dict] = []
    execution: dict | None = None
    data_origins: list[str] = []


class AuditRow(BaseModel):
    seq: int
    at: datetime
    actor_type: str
    actor_id: str
    event_type: str
    entity_ref: str | None
    proposal_id: int | None
    run_id: int | None
    data: dict
    hash: str
    prev_hash: str


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None = None


class DemoResultOut(BaseModel):
    ok: bool
    message: str
    clock: datetime
    created: dict[str, Any] = {}
