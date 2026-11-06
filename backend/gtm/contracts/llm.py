"""LLM wrapper interface (contract C8) and structured outputs. Live calls are disabled by default (budget $0)."""
from __future__ import annotations
from enum import StrEnum
from typing import Literal, Protocol
from pydantic import BaseModel, Field
from .proposals import Claim


class Task(StrEnum):
    TRIAGE = "triage"
    QUALIFY = "qualify"
    RESEARCH_BRIEF = "research_brief"
    ACCOUNT_DECIDE = "account_decide"
    DRAFT_MESSAGE = "draft_message"
    REPLY_INTENT = "reply_intent"
    FEEDBACK_EXTRACT = "feedback_extract"


class LLMRequest(BaseModel):
    task: Task
    prompt_version: str = "v1"
    input: dict                        # structured, JSON-serialisable; untrusted text lives under input["untrusted"]
    max_cost_usd: float = 0.0


class LLMResponse(BaseModel):
    output: dict                       # validated against the task's output model before return
    model_id: str                      # e.g. "mock-heuristic-v1", "replay:mock-heuristic-v1", "claude-..." (live)
    mode: Literal["replay", "mock", "live"]
    input_hash: str
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    data_origin: str = "MOD"           # always MOD; `mode` + `model_id` say how it was produced


class LLMClient(Protocol):
    def complete(self, req: LLMRequest, *, run_id: int | None = None) -> LLMResponse: ...


# ---- structured outputs (one per task) ----
class TriageOut(BaseModel):
    label: Literal["genuine", "vendor", "recruiter", "spam", "unclear"]
    confidence: float
    reason: str
    injection_suspected: bool = False


class Criterion(BaseModel):
    name: str
    met: bool | None = None
    evidence_ref: str | None = None
    note: str | None = None


class QualifyOut(BaseModel):
    score: int = Field(ge=0, le=100)
    band: Literal["high", "medium", "low", "none"]
    criteria: list[Criterion] = []
    rationale: str
    service_line: str | None = None
    owner_hint: str | None = None
    next_action: str
    unknowns: list[str] = []


class ResearchOut(BaseModel):
    claims: list[Claim] = []
    unknowns: list[str] = []
    injection_flags: list[str] = []


ActionType = Literal["no_action", "update_agent_fields", "recommend_task", "draft_message", "propose_field_change",
                     "propose_crm_create", "request_enrichment", "flag_risk", "recommend_human_touch"]


class ActionItem(BaseModel):
    type: ActionType
    params: dict = {}
    rationale: str = ""
    evidence_refs: list[str] = []


class AccountDecisionOut(BaseModel):
    actions: list[ActionItem]
    summary: str
    risks: list[str] = []
    confidence: float
    what_would_change: str = ""


class DraftOut(BaseModel):
    subject: str
    body: str
    claims: list[Claim] = []


class ReplyIntentOut(BaseModel):
    intent: Literal["interested", "not_now", "not_interested", "referral", "question", "unclear"]
    confidence: float
    rationale: str


class FeedbackItemOut(BaseModel):
    kind: Literal["objection", "pain_point", "request", "competitor_mention", "lost_reason", "praise", "risk"]
    topic: str | None = None
    label: str
    quote: str                          # MUST appear verbatim in the source text (checked in code)
    speaker_role: str | None = None
    sentiment: str | None = None
    confidence: float = 0.5


class FeedbackExtractOut(BaseModel):
    items: list[FeedbackItemOut] = []


OUTPUT_MODELS: dict[Task, type[BaseModel]] = {
    Task.TRIAGE: TriageOut, Task.QUALIFY: QualifyOut, Task.RESEARCH_BRIEF: ResearchOut,
    Task.ACCOUNT_DECIDE: AccountDecisionOut, Task.DRAFT_MESSAGE: DraftOut, Task.REPLY_INTENT: ReplyIntentOut,
    Task.FEEDBACK_EXTRACT: FeedbackExtractOut,
}
