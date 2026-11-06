"""Gateway result API and execution tokens (contract C11; docs/orchestration.md section 13, execution-architecture 13)."""
from __future__ import annotations
import hashlib, hmac, json
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel


class GatewayStatus(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"      # park and call again (retry_after)
    BLOCKED = "BLOCKED"          # soft: return to review; hard: terminal (suppression/DNC)
    EXECUTED = "EXECUTED"


class GatewayResult(BaseModel):
    status: GatewayStatus
    reason: str | None = None
    block_class: str | None = None       # 'soft' | 'hard'
    retry_after_s: float | None = None
    execution_id: int | None = None
    external_ref: str | None = None
    checks: list[dict] = []              # [{"name":..., "passed":bool, "detail":...}] in order


class ExecutionToken(BaseModel):
    proposal_id: int
    payload_hash: str
    adapter: str
    expires_at: datetime
    signature: str


def _msg(proposal_id: int, payload_hash: str, adapter: str, expires_at: datetime) -> bytes:
    return json.dumps([proposal_id, payload_hash, adapter, expires_at.isoformat()]).encode()


def mint_token(secret: bytes, *, proposal_id: int, payload_hash: str, adapter: str, expires_at: datetime) -> ExecutionToken:
    sig = hmac.new(secret, _msg(proposal_id, payload_hash, adapter, expires_at), hashlib.sha256).hexdigest()
    return ExecutionToken(proposal_id=proposal_id, payload_hash=payload_hash, adapter=adapter, expires_at=expires_at, signature=sig)


def verify_token(secret: bytes, token: ExecutionToken | None, *, adapter: str, now: datetime, payload_hash: str | None = None) -> bool:
    """Side-effecting adapters call this before acting. Missing/forged/expired/wrong-adapter/wrong-hash -> False."""
    if token is None or token.adapter != adapter or token.expires_at <= now:
        return False
    if payload_hash is not None and token.payload_hash != payload_hash:
        return False
    good = hmac.new(secret, _msg(token.proposal_id, token.payload_hash, token.adapter, token.expires_at), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, token.signature)


class TokenVerifier:
    """Held by side-effecting adapters. Only the gateway holds the minting secret; adapters verify."""

    def __init__(self, secret: bytes, clock):
        self._secret = secret
        self._clock = clock

    def verify(self, token: ExecutionToken | None, adapter: str, payload_hash: str | None = None) -> bool:
        return verify_token(self._secret, token, adapter=adapter, now=self._clock.now(), payload_hash=payload_hash)
