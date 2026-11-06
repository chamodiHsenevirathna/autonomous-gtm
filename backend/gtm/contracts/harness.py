"""System harness contract (C13/C7). gtm.harness.Harness implements it; gtm.eval drives scenarios through it."""
from __future__ import annotations
from typing import Any, Protocol
from .gateway import GatewayResult
from .sims import FaultSpec


class SystemHarness(Protocol):
    conn: Any            # psycopg connection to the test DB
    clock: Any           # SimClock
    world: Any           # gtm.contracts.world.World

    def reset(self, seed: int | None = None, llm_mode: str = "mock", world_overrides: dict | None = None) -> None: ...
    def deliver_enquiry(self, enquiry_id: str) -> int: ...                       # returns lead id
    def run_until_idle(self, *, max_steps: int = 1000, advance_clock: bool = True) -> dict: ...
    def pending_proposals(self) -> list[dict]: ...                                # rows of ops.proposal with status pending
    def decide(self, proposal_id: int, decision: str, *, by: str, edited_payload: dict | None = None,
               reason_code: str | None = None) -> dict: ...                       # approve | approve_with_edits | reject
    def deliver_reply(self, reply_id: str) -> None: ...                           # schedules the scripted reply in the mail sim
    def advance(self, seconds: float) -> None: ...
    def inject_fault(self, spec: FaultSpec) -> None: ...
    def clear_faults(self) -> None: ...
    def attempt_gateway(self, proposal_id: int, *, bypass: str | None = None) -> GatewayResult: ...
    # bypass in {None,'no_token','forged_token','wrong_hash','replay','direct_adapter'}: red-team attempts that must be denied
    def tamper(self, what: str) -> None: ...                                      # 'audit_row' | 'proposal_payload' | 'recipient' (test-only)
    def snapshot(self) -> dict[str, Any]: ...                                     # counts and ids for assertions
