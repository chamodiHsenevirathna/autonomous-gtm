"""Error taxonomy (contract C3)."""
from enum import StrEnum


class ErrorClass(StrEnum):
    RETRYABLE = "retryable"      # timeouts, 429, 5xx, connection errors
    PERMANENT = "permanent"      # 4xx validation/auth, schema errors
    POLICY = "policy"            # denied by a safety/policy rule; never retried
    NOT_READY = "not_ready"      # dependency not ready (e.g. sync lag): park, do not fail


class GTMError(Exception):
    error_class = ErrorClass.PERMANENT

    def __init__(self, message: str, *, retry_after: float | None = None, detail: dict | None = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.detail = detail or {}


class RetryableError(GTMError):
    error_class = ErrorClass.RETRYABLE


class PermanentError(GTMError):
    error_class = ErrorClass.PERMANENT


class PolicyDenied(GTMError):
    error_class = ErrorClass.POLICY


class NotReady(GTMError):
    error_class = ErrorClass.NOT_READY


def classify_http(status: int) -> ErrorClass | None:
    """None means success."""
    if status < 400:
        return None
    if status in (408, 425, 429) or status >= 500:
        return ErrorClass.RETRYABLE
    return ErrorClass.PERMANENT
