"""Shared HTTP plumbing for adapters: status mapping, token check. No retries here (the orchestrator retries)."""
from __future__ import annotations
import hashlib, json
import httpx
from gtm.contracts.errors import ErrorClass, GTMError, PermanentError, PolicyDenied, RetryableError, classify_http
from gtm.contracts.gateway import ExecutionToken, TokenVerifier
from gtm.contracts.sims import IDEMPOTENCY_HEADER


class ConflictError(PermanentError):
    """HTTP 409: the object already exists. `existing_id` is set when the server supplies it."""

    def __init__(self, message: str, *, existing_id: str | None = None, detail: dict | None = None):
        super().__init__(message, detail=detail)
        self.existing_id = existing_id


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("Retry-After")
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _body(resp: httpx.Response):
    try:
        b = resp.json()
        return b.get("detail", b) if isinstance(b, dict) else b
    except ValueError:
        return resp.text


def raise_for_status(resp: httpx.Response, what: str) -> None:
    cls = classify_http(resp.status_code)
    if cls is None:
        return
    body = _body(resp)
    msg = f"{what}: HTTP {resp.status_code} {body.get('message') if isinstance(body, dict) else body}"
    detail = {"status": resp.status_code, "body": body}
    if cls == ErrorClass.RETRYABLE:
        raise RetryableError(msg, retry_after=_retry_after(resp), detail=detail)
    if resp.status_code == 409:
        raise ConflictError(msg, existing_id=(body or {}).get("existingId") if isinstance(body, dict) else None, detail=detail)
    raise PermanentError(msg, detail=detail)


def request(http: httpx.Client, method: str, url: str, what: str, **kw) -> httpx.Response:
    try:
        resp = http.request(method, url, **kw)
    except httpx.TransportError as e:
        raise RetryableError(f"{what}: transport error {type(e).__name__}", detail={"error": str(e)}) from e
    raise_for_status(resp, what)
    return resp


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def require_token(verifier: TokenVerifier, token: ExecutionToken | None, adapter: str, payload_hash: str | None) -> None:
    """Runs BEFORE any HTTP call. `payload_hash` (optional) is checked against the token when the caller supplies it."""
    if not verifier.verify(token, adapter, payload_hash):
        raise PolicyDenied(f"{adapter}: missing, invalid, expired or mismatched execution token")


def idem_headers(key: str) -> dict:
    if not key:
        raise PermanentError("idempotency_key is required for side-effecting calls")
    return {IDEMPOTENCY_HEADER: key}
