"""Proposals, payloads and the approval hash specification (docs/execution-architecture.md 13.1)."""
from __future__ import annotations
import hashlib, json
from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, Field

SCREEN_POLICY_VERSION = "screen-v1"


class ProposalType(StrEnum):
    MATCH_CONFIRMATION = "match_confirmation"   # G1
    MERGE = "merge"                             # G2
    LEAD_DISPOSITION = "lead_disposition"       # G3
    CRM_WRITE = "crm_write"                     # G4
    MESSAGE = "message"                         # G5
    FIELD_CHANGE = "field_change"               # G6
    TASK = "task"                               # G7
    OPPORTUNITY_FROM_SIGNAL = "opportunity_from_signal"  # G8
    SEQUENCE_STEP = "sequence_step"             # G10


GATE_FOR_TYPE = {
    ProposalType.MATCH_CONFIRMATION: "G1", ProposalType.MERGE: "G2", ProposalType.LEAD_DISPOSITION: "G3",
    ProposalType.CRM_WRITE: "G4", ProposalType.MESSAGE: "G5", ProposalType.FIELD_CHANGE: "G6",
    ProposalType.TASK: "G7", ProposalType.OPPORTUNITY_FROM_SIGNAL: "G8", ProposalType.SEQUENCE_STEP: "G10",
}


class ProposalStatus(StrEnum):
    PENDING = "pending"; APPROVED = "approved"; APPROVED_EDITED = "approved_edited"; REJECTED = "rejected"
    EXPIRED = "expired"; SUPERSEDED = "superseded"; EXECUTING = "executing"; PARKED = "parked"
    BLOCKED = "blocked"; EXECUTED = "executed"; FAILED = "failed"


class Claim(BaseModel):
    text: str
    source_ref: str | None = None      # None = unsupported claim (must be flagged by the claim checker)


class MessagePayload(BaseModel):
    channel: Literal["email"] = "email"
    contact_id: int
    resolved_recipient: str            # canonical address at proposal time; gateway re-resolves and compares
    sender_identity: str               # the human owner, e.g. "maya@corvane.example"
    subject: str
    body: str
    links: list[str] = []
    attachments: list[str] = []        # content hashes
    claims: list[Claim] = []
    thread_id: str | None = None
    experiment_id: int | None = None   # reserved (experiments are Later); part of the hash
    variant_id: int | None = None
    design_hash: str | None = None


class CrmOp(BaseModel):
    object: Literal["company", "contact", "deal"]
    action: Literal["create", "update"]
    local_ref: dict                    # {"type": "account|contact|opportunity", "id": int}
    properties: dict[str, Any]


class CrmWritePayload(BaseModel):
    operations: list[CrmOp]


class FieldChangePayload(BaseModel):
    entity: Literal["opportunity", "account", "contact"]
    entity_id: int
    field: str
    old_value: Any = None
    new_value: Any = None


class TaskPayload(BaseModel):
    owner: str
    title: str
    detail: str | None = None
    due_at: str | None = None


class LeadDispositionPayload(BaseModel):
    lead_id: int
    disposition: Literal["qualified", "disqualified", "nurture"]
    score: float | None = None
    route_owner: str | None = None
    service_line: str | None = None


class MatchPayload(BaseModel):
    entity_type: Literal["account", "contact"]
    left_id: int
    right_id: int
    score: float


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def payload_hash(proposal_id: int, ptype: str, payload: dict, *, screen_policy_version: str = SCREEN_POLICY_VERSION) -> str:
    """SHA-256 over the canonical form of {proposal id, type, full payload, screen-policy version}.
    For MESSAGE the payload includes the resolved recipient, channel, sender, subject, body, links, attachments and
    experiment ids, so any change to any of them changes the hash. At execution the gateway RECOMPUTES this from stored
    content and the *currently resolved* recipient; a mismatch is BLOCKED(soft: recipient_changed)."""
    doc = {"proposal_id": proposal_id, "type": str(ptype), "payload": payload, "screen_policy_version": screen_policy_version}
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()
