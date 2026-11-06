"""Fault injection shared by all simulators. Deterministic: no randomness, no real sleeping, no wall-clock."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from fastapi import HTTPException, Request, Response
from gtm.contracts.sims import FaultSpec

ERROR_KINDS = ("http_429", "http_500", "http_503", "timeout")


@dataclass
class Outcome:
    latency_ms: int = 0
    partial: bool = False
    delay_s: float | None = None
    duplicate_events: bool = False
    out_of_order_events: bool = False
    drop_sync: bool = False


class FaultStore:
    """Holds active faults. `count` is the number of requests the fault still applies to (None = until cleared)."""

    def __init__(self) -> None:
        self._faults: list[dict] = []
        self.requests: Counter = Counter()      # per sim
        self.fired: Counter = Counter()         # per fault kind
        self.latency_ms: Counter = Counter()    # simulated latency per sim (metadata only)

    def inject(self, spec: FaultSpec) -> None:
        self._faults.append({"spec": spec, "remaining": spec.count})

    def clear(self) -> None:
        self._faults.clear()

    def active(self) -> list[dict]:
        return [{**f["spec"].model_dump(), "remaining": f["remaining"]} for f in self._faults]

    def apply(self, sim: str, keys: list[str], relevant: tuple[str, ...] = ()) -> Outcome:
        """Evaluate faults for one request. Raises HTTPException for error faults; otherwise returns the soft effects."""
        self.requests[sim] += 1
        out, error, err_params = Outcome(), None, {}
        for f in list(self._faults):
            spec: FaultSpec = f["spec"]
            if spec.sim not in (sim, "*") or (spec.kind not in ("latency", *ERROR_KINDS, "partial_data", *relevant)):
                continue
            if spec.scope is not None and not any(spec.scope in k for k in keys):
                continue
            if f["remaining"] is not None:
                f["remaining"] -= 1
                if f["remaining"] <= 0:
                    self._faults.remove(f)
            self.fired[spec.kind] += 1
            p, k = spec.params, spec.kind
            if k == "latency":
                out.latency_ms += int(p.get("latency_ms", 2000))
            elif k == "partial_data":
                out.partial = True
            elif k == "eventual_consistency":
                out.delay_s = float(p.get("delay_s", 600))
            elif k == "duplicate_events":
                out.duplicate_events = True
            elif k == "out_of_order_events":
                out.out_of_order_events = True
            elif k == "drop_sync":
                out.drop_sync = True
            elif error is None:
                error = k
                if k == "timeout":
                    out.latency_ms += int(p.get("timeout_ms", 30000))
                err_params = p
        if error:
            self.latency_ms[sim] += out.latency_ms
            raise _http_error(error, err_params, out.latency_ms)
        return out


def _http_error(kind: str, params: dict, latency_ms: int) -> HTTPException:
    headers = {"X-Sim-Latency-Ms": str(latency_ms)} if latency_ms else {}
    if kind == "http_429":
        headers["Retry-After"] = str(params.get("retry_after", 2))
        return HTTPException(429, {"message": "rate limited"}, headers)
    if kind == "http_500":
        return HTTPException(500, {"message": "simulated server error"}, headers)
    if kind == "http_503":
        if "retry_after" in params:
            headers["Retry-After"] = str(params["retry_after"])
        return HTTPException(503, {"message": "simulated unavailable"}, headers)
    return HTTPException(504, {"message": "simulated timeout"}, headers)


def gate(faults: FaultStore, sim: str, response: Response, keys: list[str], base_latency_ms: int = 20,
         relevant: tuple[str, ...] = ()) -> Outcome:
    out = faults.apply(sim, keys, relevant)
    total = base_latency_ms + out.latency_ms
    faults.latency_ms[sim] += total
    response.headers["X-Sim-Latency-Ms"] = str(total)
    return out
