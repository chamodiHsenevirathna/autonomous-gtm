"""Ground-truth world schema (contract C10). Generated deterministically from a seed by gtm.world."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class TrueCompany(BaseModel):
    id: str                            # 'co_001'
    name: str
    domain: str
    alias_domains: list[str] = []
    legal_name: str | None = None
    industry: str
    employee_count: int
    revenue_band: Literal["<10M", "10-50M", "50-250M", "250M-1B", ">1B"]
    region: str                        # e.g. 'EMEA', 'NA', 'APAC'
    hq_country: str
    tech_stack: list[str] = []
    parent_id: str | None = None
    icp_fit: bool                      # ground-truth label: would Corvane want this account?
    service_need: str | None = None    # which Corvane service line the company really needs
    hiring_signals: list[str] = []
    description: str = ""


class TrueContact(BaseModel):
    id: str
    company_id: str
    full_name: str
    email: str
    title: str
    seniority: Literal["c_level", "vp", "director", "manager", "ic"]
    persona: str = ""


class Enquiry(BaseModel):
    """A scripted inbound enquiry with ground-truth labels."""
    id: str                            # 'enq_001'
    kind: Literal["genuine", "vendor", "recruiter", "spam"]
    expected_band: Literal["high", "medium", "low", "none"]
    at_offset_s: int = 0               # seconds after scenario start
    full_name: str
    email: str
    company_name: str
    message: str
    service_interest: str | None = None
    truth_company_id: str | None = None
    truth_contact_id: str | None = None
    duplicate_of: str | None = None    # another enquiry/contact id this one duplicates
    injection: bool = False            # message contains instructions aimed at the model


class WebPage(BaseModel):
    url: str
    title: str
    text: str
    company_id: str | None = None
    contains_injection: bool = False   # untrusted-source test page


class ScriptedReply(BaseModel):
    id: str
    to_enquiry_id: str
    at_offset_s: int                   # offset AFTER the outbound message is sent
    kind: Literal["interested", "not_now", "not_interested", "ooo", "bounce", "unsubscribe", "referral", "question", "meeting_booked"]
    subject: str = ""
    body: str = ""


class ProviderParams(BaseModel):
    name: str                          # provider_a | provider_b | provider_c
    coverage: float                    # probability the provider knows an entity
    accuracy: float                    # per-field probability of a correct value
    staleness_days: int                # typical as_of age
    cost_per_call: float
    latency_ms: int
    fields: list[str]                  # fields it can supply


class World(BaseModel):
    seed: int
    companies: list[TrueCompany]
    contacts: list[TrueContact]
    enquiries: list[Enquiry]
    web_pages: list[WebPage] = []
    replies: list[ScriptedReply] = []
    duplicate_company_pairs: list[tuple[str, str]] = []
    providers: list[ProviderParams] = []
    data_origin: str = "GT"
