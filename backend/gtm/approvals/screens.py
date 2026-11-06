"""Content screens run at draft creation, on every edit, and again at the gateway on the final payload.
Deterministic code; no model calls. (docs/execution-architecture.md 13.3, 13.5)"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

ALLOWED_LINK_SUFFIXES = (".example", "corvane.example")

# price / discount / date / scope commitments (conservative: false positives go to a human, never auto-sent)
_PATTERNS = [
    ("price", re.compile(r"(?:[$€£]\s?\d[\d,\.]*\s?(?:k|m|million|thousand)?)|(?:\b\d[\d,\.]*\s?(?:usd|eur|gbp|dollars|euros|pounds)\b)", re.I)),
    ("discount", re.compile(r"\b(?:discount|\d+\s?%\s?off|rebate|special rate|waive[sd]?\s+(?:the\s+)?fee)\b", re.I)),
    ("price_word", re.compile(r"\b(?:our (?:price|rate|fee)s?|quote[ds]?|fixed[- ]price|per day rate|day rate)\b", re.I)),
    ("date_commitment", re.compile(r"\b(?:we (?:will|can) (?:deliver|start|begin|complete|finish)|go[- ]live|kick[- ]?off)\b[^.]{0,60}\b(?:by|on|within|before|in)\b[^.]{0,30}(?:\d|week|month|quarter|january|february|march|april|may|june|july|august|september|october|november|december|monday|tuesday|wednesday|thursday|friday)", re.I)),
    ("guarantee", re.compile(r"\b(?:guarantee[sd]?|we promise|commit(?:s|ted)? to deliver|binding)\b", re.I)),
]
_URL = re.compile(r"https?://([A-Za-z0-9.\-]+)[^\s)>\]]*", re.I)


@dataclass
class ScreenResult:
    blocked: bool = False
    flags: list[dict] = field(default_factory=list)

    def add(self, kind: str, detail: str, blocking: bool):
        self.flags.append({"kind": kind, "detail": detail, "blocking": blocking})
        self.blocked = self.blocked or blocking


def screen_message(payload: dict, *, acknowledged_not_commitment: bool = False) -> ScreenResult:
    """Screen a MessagePayload dict. Commercial-commitment patterns BLOCK execution unless a human with AE+ role has
    acknowledged 'reviewed: not a commitment' (price/discount terms are never releasable by acknowledgement)."""
    res = ScreenResult()
    text = f"{payload.get('subject','')}\n{payload.get('body','')}"
    for kind, rx in _PATTERNS:
        m = rx.search(text)
        if m:
            releasable = kind in ("date_commitment", "guarantee", "price_word") and acknowledged_not_commitment
            res.add("commercial", f"{kind}: '{m.group(0)[:60]}'", blocking=not releasable)
    for url in list(payload.get("links") or []) + [m.group(0) for m in _URL.finditer(text)]:
        host = (_URL.match(url).group(1) if _URL.match(url) else url).lower()
        if not host.endswith(ALLOWED_LINK_SUFFIXES):
            res.add("link", f"link host not allow-listed: {host}", blocking=True)
    for c in payload.get("claims") or []:
        if not c.get("source_ref"):
            res.add("claim", f"unsupported claim: '{c.get('text','')[:60]}'", blocking=True)
    return res
