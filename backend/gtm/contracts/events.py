"""Event envelope and canonical event catalogue (contract C4; docs/orchestration.md section 11)."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class EventType:
    LEAD_RECEIVED = "lead.received"
    LEAD_QUALIFIED = "lead.qualified"
    INTERACTION_STORED = "interaction.stored"
    REPLY_RECEIVED = "reply.received"
    MEETING_BOOKED = "meeting.booked"
    SIGNAL_DETECTED = "signal.detected"
    OPPORTUNITY_CREATED = "opportunity.created"
    OPPORTUNITY_STAGE_CHANGED = "opportunity.stage_changed"
    OPPORTUNITY_CLOSED_LOST = "opportunity.closed_lost"
    DEAL_FLAGGED = "deal.flagged"
    LOST_DEAL_REVIEW_SAVED = "lost_deal_review.saved"
    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_APPROVED = "proposal.approved"
    PROPOSAL_REJECTED = "proposal.rejected"
    PROPOSAL_EXPIRED = "proposal.expired"
    PROPOSAL_SUPERSEDED = "proposal.superseded"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    SYNC_CONTACT_VISIBLE = "sync.contact_visible"
    SUPPRESSION_ADDED = "suppression.added"
    SEQUENCE_STOPPED = "sequence.stopped"
    BREAKER_OPENED = "breaker.opened"
    ENRICHMENT_REQUESTED = "enrichment.requested"
    ENRICHMENT_COMPLETED = "enrichment.completed"
    FEEDBACK_CAPTURED = "feedback.captured"
    HEARTBEAT_DUE = "heartbeat.due"
    JOB_DEAD = "job.dead"


class EventEnvelope(BaseModel):
    type: str
    account_id: int | None = None
    entity_ref: str | None = None            # e.g. "lead:12"
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime
    source: str                              # 'webhook', 'sim:outreach', 'gateway', 'router', ...
    source_version: int | None = None        # monotonic per entity from the source; used for stale-event rule
    schema_version: int = 1
    dedupe_key: str                          # unique; duplicates are dropped
    ordering_key: str | None = None          # usually entity_ref
