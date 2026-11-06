"""Simulator HTTP API contract (C1/C2/C5). Every simulator is a FastAPI app factory taking (world, clock, faults).
Adapters take an httpx.Client; tests inject starlette TestClient(app), the demo injects httpx.Client(base_url=...)."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

# ---- mount points when everything runs in one process (the demo default) ----
MOUNT_PROVIDER = {"provider_a": "/sim/providers/a", "provider_b": "/sim/providers/b", "provider_c": "/sim/providers/c"}
MOUNT_CRM = "/sim/crm"
MOUNT_OUTREACH = "/sim/outreach"
MOUNT_WEB = "/sim/web"
MOUNT_CONTROL = "/sim/control"
IDEMPOTENCY_HEADER = "Idempotency-Key"

# ---- providers: POST {mount}/company  and  POST {mount}/person ----
class ProviderCompanyRequest(BaseModel):
    domain: str | None = None
    name: str | None = None
    fields: list[str]

class ProviderPersonRequest(BaseModel):
    email: str
    fields: list[str]

class ProviderField(BaseModel):
    value: Any
    as_of: datetime

class ProviderResponse(BaseModel):
    provider: str
    found: bool
    fields: dict[str, ProviderField] = {}
    cost_units: float = 0.0
    partial: bool = False
# HTTP: 429 (+Retry-After), 500/503, or a simulated timeout (HTTP 504) when faults are injected.

# ---- CRM (HubSpot-shaped): {mount}/crm/v3/objects/{contacts|companies|deals} ----
CRM_OBJECTS = ("contacts", "companies", "deals")

class CrmCreate(BaseModel):
    properties: dict[str, Any]
    associations: list[dict] = []

class CrmObject(BaseModel):
    id: str
    properties: dict[str, Any]
    createdAt: datetime
    updatedAt: datetime

class CrmSearchFilter(BaseModel):
    propertyName: str
    operator: Literal["EQ"] = "EQ"
    value: Any

class CrmSearch(BaseModel):
    filters: list[CrmSearchFilter]
    limit: int = 10
# POST create honours Idempotency-Key (same key -> same object, 200). Duplicate contact email -> 409 {"message","existingId"}.
# GET {id}; PATCH {id} {properties}; POST /search. Unknown id -> 404.

# ---- outreach tool (eventually consistent) + mailbox ----
class OutreachImport(BaseModel):
    crm_contact_id: str
    email: str
    full_name: str | None = None
# POST {mount}/contacts/import -> 202 {"import_id", "visible_at"}  (contact becomes visible after a delay on the shared clock)
# GET  {mount}/contacts?external_key=<crm id>  or  ?email=  -> {"contacts":[{"id","email","external_key","visible_at"}]}  (empty until visible)

class OutreachSend(BaseModel):
    contact_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
# POST {mount}/messages (Idempotency-Key required) -> 201 {"message_id","status":"sent"}; 422 if contact not yet visible;
#      403 {"message":"suppressed"} if the contact unsubscribed in the sim (defence in depth, not a substitute for the gateway)

class SimEvent(BaseModel):
    seq: int
    type: Literal["reply", "bounce", "unsubscribe", "meeting_booked", "contact_visible"]
    ts: datetime
    payload: dict
# GET {mount}/events?since=<seq> -> {"events":[SimEvent...]}   (pull model; duplicates / out-of-order injectable)

# ---- synthetic web for the research agent ----
# GET {mount}/search?q=  -> {"results":[{"url","title","snippet"}]};   GET {mount}/page?url= -> {"url","title","text"}

# ---- control plane ----
FaultKind = Literal["latency", "http_429", "http_500", "http_503", "timeout", "partial_data",
                    "eventual_consistency", "duplicate_events", "out_of_order_events", "drop_sync"]

class FaultSpec(BaseModel):
    sim: str                           # 'provider_a'|'provider_b'|'provider_c'|'crm'|'outreach'|'web'|'*'
    kind: FaultKind
    scope: str | None = None           # optional entity filter (domain/email/endpoint)
    params: dict = {}                  # e.g. {"delay_s": 90}, {"retry_after": 2}
    count: int | None = None           # apply to the next N requests; None = until cleared
# POST {MOUNT_CONTROL}/faults (FaultSpec) | DELETE {MOUNT_CONTROL}/faults | GET {MOUNT_CONTROL}/state
# POST {MOUNT_CONTROL}/script  -> schedule scripted replies/bookings: {"reply_id", "to_message_id"|"to_email", "at": datetime}
