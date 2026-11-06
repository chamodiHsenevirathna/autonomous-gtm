"""Scenario file schema (contract C13). Files live in backend/scenarios/*.yaml. Used by gtm.eval."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field
from .provenance import EvidenceBasis


class ScriptEvent(BaseModel):
    at_offset_s: int = 0
    kind: Literal["enquiry", "reply", "advance_clock", "inject_fault", "clear_faults", "human_decision", "gateway_attempt", "tamper", "custom"]
    ref: str | None = None             # world id (enq_001 / reply id) or proposal selector
    params: dict[str, Any] = {}


class Expectation(BaseModel):
    kind: Literal["invariant", "state", "metric", "event", "audit", "no_effect"]
    name: str
    spec: dict[str, Any] = {}


class Scenario(BaseModel):
    id: str                            # 'S01'
    title: str
    seed: int = 42
    llm_mode: Literal["replay", "mock"] = "mock"
    world_overrides: dict[str, Any] = {}
    script: list[ScriptEvent] = []
    expectations: list[Expectation] = []
    pass_criterion: str
    truth_source: str                  # what the answer is checked against
    evidence_basis: EvidenceBasis
    data_origins: list[str] = []       # provenance labels involved (GT, SIM, SCR, MOD, HUM-sim, PLT)
    covers: list[str] = []             # requirement ids
    milestone: str = "M?"
