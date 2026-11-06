"""Lost-deal review capture, feedback extraction with in-code evidence checks, distinct-account summary.
No themes, backlog or experiments (deferred)."""
from __future__ import annotations
import re
from psycopg import Connection
from psycopg.types.json import Jsonb
from .. import audit
from ..clock import Clock
from ..contracts.errors import PermanentError, PolicyDenied
from ..contracts.events import EventEnvelope, EventType
from ..contracts.llm import LLMRequest, Task

LOST_REASONS = ("price", "competitor_chosen", "no_decision", "timing", "product_fit", "relationship", "delivery_capacity",
                "scope_mismatch", "champion_left", "other")

INJECTION_RX = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above)|disregard|system prompt|\byou are (?:now )?an?\b|^\s*system\s*:|\bassistant\s*:|"
    r"output the following|emit_result|</?\s*(?:system|instructions)\s*>|record that|new instructions", re.I | re.M)


# ---------------------------------------------------------------- lost-deal review (human-entered)

def save_lost_deal_review(conn: Connection, clock: Clock, *, opportunity_id: int, primary_reason: str, secondary_reasons: list[str] | None = None,
                          competitor: str | None = None, debrief_held: bool = False, notes: str | None = None, captured_by: str,
                          ai_suggested_tags: list[str] | None = None) -> int:
    from ..orchestration.events import emit
    secondary = list(secondary_reasons or [])
    for r in [primary_reason, *secondary]:
        if r not in LOST_REASONS:
            raise PermanentError(f"reason {r!r} is not in the taxonomy {list(LOST_REASONS)}", detail={"reason": "invalid_reason"})
    pr = conn.execute("SELECT type FROM ops.principal WHERE id=%s", (captured_by,)).fetchone()
    if not pr or pr["type"] != "human":
        raise PolicyDenied("lost-deal reasons are human-owned: captured_by must be a human principal")
    opp = conn.execute("SELECT id, account_id FROM gtm.opportunity WHERE id=%s", (opportunity_id,)).fetchone()
    if not opp:
        raise PermanentError(f"opportunity {opportunity_id} not found")
    if conn.execute("SELECT 1 FROM gtm.lost_deal_review WHERE opportunity_id=%s", (opportunity_id,)).fetchone():
        raise PermanentError("a lost-deal review already exists for this opportunity", detail={"reason": "duplicate_review"})
    ai = {"label": "AI-suggested (unreviewed, not part of the human record)", "data_origin": "MOD", "tags": list(ai_suggested_tags)} if ai_suggested_tags else None
    rid = conn.execute(
        "INSERT INTO gtm.lost_deal_review(opportunity_id, primary_reason, secondary_reasons, competitor, debrief_held, notes, captured_by, ai_suggested_tags, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (opportunity_id, primary_reason, secondary, competitor, bool(debrief_held), notes, captured_by, Jsonb(ai) if ai else None, clock.now())).fetchone()["id"]
    audit.append(conn, clock, actor_type="human", actor_id=captured_by, event_type="lost_deal_review.saved", entity_ref=f"lost_deal_review:{rid}",
                 data={"opportunity_id": opportunity_id, "primary_reason": primary_reason, "secondary_reasons": secondary, "competitor": competitor})
    emit(conn, clock, EventEnvelope(type=EventType.LOST_DEAL_REVIEW_SAVED, account_id=opp["account_id"], entity_ref=f"lost_deal_review:{rid}",
                                    payload={"review_id": rid, "opportunity_id": opportunity_id, "primary_reason": primary_reason},
                                    occurred_at=clock.now(), source="feedback", dedupe_key=f"lost_deal_review.saved:{rid}"))
    return rid


# ---------------------------------------------------------------- mock model (deterministic keyword rules)

_RULES = [
    ("risk", "retention", "Churn or escalation risk", re.compile(r"\b(cancel|churn|leaving|at risk|escalat)\w*", re.I)),
    ("competitor_mention", "competitor", "Competitor mentioned", re.compile(r"\b(?:went with|chose|evaluating|compared to|switch(?:ing)? to|looking at|cheaper at)\s+[A-Z][\w-]+")),
    ("objection", "pricing", "Pricing objection", re.compile(r"\b(too expensive|expensive|pricing|price|budget|costly|cost)\b", re.I)),
    ("pain_point", "delivery", "Pain point", re.compile(r"\b(struggl\w*|frustrat\w*|manual|too slow|slow|takes too long|pain)\b", re.I)),
    ("request", "product", "Request", re.compile(r"\b(would like|we need|we wish|i wish|wish we|feature|can you add)\b", re.I)),
    ("praise", "service", "Praise", re.compile(r"\b(love|great|excellent|impressed|fantastic)\b", re.I)),
]
_LOST = re.compile(r"\b(lost|decided not to|did not proceed|went with|chose)\b", re.I)


def mock_feedback_extract(inp: dict) -> dict:
    """Deterministic stand-in for the model (MOD, mode=mock). Keyword rules over sentences; quotes are exact substrings.
    Instruction-like sentences are skipped: the text is data."""
    text = (inp.get("untrusted") or {}).get("text") or ""
    lost = inp.get("source_type") == "lost_deal_review"
    items = []
    for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
        s = m.group(0).strip()
        if len(s) < 8 or INJECTION_RX.search(s):
            continue
        rule = None
        if lost and _LOST.search(s):
            rule = ("lost_reason", "lost_deal", "Lost-deal reason")
        else:
            rule = next(((k, t, l) for k, t, l, rx in _RULES if rx.search(s)), None)
        if rule:
            items.append({"kind": rule[0], "topic": rule[1], "label": rule[2], "quote": s, "speaker_role": "prospect" if not lost else "seller",
                          "sentiment": "positive" if rule[0] == "praise" else "negative", "confidence": 0.6})
    return {"items": items}


def register_mocks() -> None:
    from ..llm import register_mock
    register_mock(Task.FEEDBACK_EXTRACT, mock_feedback_extract)


register_mocks()


# ---------------------------------------------------------------- extraction with verification

def _size_band(n) -> str | None:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return "1-49" if n < 50 else "50-249" if n < 250 else "250-999" if n < 1000 else "1000+"


def _snapshot(conn, account_id, opportunity_id=None) -> dict:
    rf = {r["field"]: r["value"] for r in conn.execute(
        "SELECT field, value FROM gtm.resolved_field WHERE entity_type='account' AND entity_id=%s AND field IN ('industry','employee_count','revenue_band')", (account_id,))}
    o = conn.execute("SELECT service_line, amount FROM gtm.opportunity WHERE " + ("id=%s" if opportunity_id else "account_id=%s ORDER BY id DESC LIMIT 1"),
                     (opportunity_id or account_id,)).fetchone()
    snap = {"service_line": o and o["service_line"], "industry": rf.get("industry"), "size_band": _size_band(rf.get("employee_count")) or rf.get("revenue_band"),
            "deal_size": float(o["amount"]) if o and o["amount"] is not None else None}
    return {k: v for k, v in snap.items() if v is not None}


def extract_feedback(conn: Connection, clock: Clock, llm, *, interaction_id: int | None = None, lost_deal_review_id: int | None = None,
                     run_id: int | None = None) -> dict:
    from ..orchestration.events import emit
    if (interaction_id is None) == (lost_deal_review_id is None):
        raise PermanentError("give exactly one of interaction_id / lost_deal_review_id")
    opp_id = None
    if interaction_id is not None:
        r = conn.execute("SELECT account_id, subject, body FROM gtm.interaction WHERE id=%s", (interaction_id,)).fetchone()
        if not r:
            raise PermanentError(f"interaction {interaction_id} not found")
        text, account_id, stype, ref = (f"{r['subject']}\n{r['body'] or ''}" if r["subject"] else (r["body"] or "")), r["account_id"], "interaction", f"interaction:{interaction_id}"
        where, wid = "interaction_id", interaction_id
    else:
        r = conn.execute("SELECT l.notes, l.opportunity_id, o.account_id FROM gtm.lost_deal_review l JOIN gtm.opportunity o ON o.id=l.opportunity_id WHERE l.id=%s",
                         (lost_deal_review_id,)).fetchone()
        if not r:
            raise PermanentError(f"lost_deal_review {lost_deal_review_id} not found")
        text, account_id, stype, opp_id, ref = r["notes"] or "", r["account_id"], "lost_deal_review", r["opportunity_id"], f"lost_deal_review:{lost_deal_review_id}"
        where, wid = "lost_deal_review_id", lost_deal_review_id
    prior = conn.execute(f"SELECT count(*) AS n FROM gtm.feedback_item WHERE {where}=%s", (wid,)).fetchone()["n"]
    if prior:
        return {"skipped": True, "existing": prior, "accepted": 0, "rejected_hallucinated": 0, "rejected_injection": 0, "item_ids": []}
    resp = llm.complete(LLMRequest(task=Task.FEEDBACK_EXTRACT, input={"source_type": stype, "source_ref": ref, "untrusted": {"text": text}}), run_id=run_id)
    snap, ids, hallu, inj, seen = _snapshot(conn, account_id, opp_id), [], 0, 0, set()
    for it in resp.output.get("items", []):
        q = it["quote"]
        start = text.find(q) if q and q.strip() and len(q.strip()) >= 5 else -1
        if start < 0:
            hallu += 1                                   # evidence rule: quote must be a verbatim substring of the source
            continue
        if INJECTION_RX.search(q):
            inj += 1
            continue
        if (q, it["kind"]) in seen:
            continue
        seen.add((q, it["kind"]))
        ids.append(conn.execute(
            "INSERT INTO gtm.feedback_item(interaction_id, lost_deal_review_id, account_id, source_type, kind, topic, label, quote, quote_start, quote_end, "
            "speaker_role, sentiment, segment_snapshot, confidence, review_status, extracted_by_run_id, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'suggested',%s,%s) RETURNING id",
            (interaction_id, lost_deal_review_id, account_id, stype, it["kind"], it.get("topic"), it.get("label"), q, start, start + len(q),
             it.get("speaker_role"), it.get("sentiment"), Jsonb(snap), it.get("confidence"), run_id, clock.now())).fetchone()["id"])
    out = {"skipped": False, "accepted": len(ids), "rejected_hallucinated": hallu, "rejected_injection": inj, "item_ids": ids,
           "model_id": resp.model_id, "mode": resp.mode, "data_origin": "MOD"}
    audit.append(conn, clock, actor_type="agent", actor_id="svc:insight", event_type="feedback.extracted", entity_ref=ref, run_id=run_id,
                 data={k: out[k] for k in ("accepted", "rejected_hallucinated", "rejected_injection", "model_id", "mode")})
    if ids:
        emit(conn, clock, EventEnvelope(type=EventType.FEEDBACK_CAPTURED, account_id=account_id, entity_ref=ref,
                                        payload={"item_ids": ids, "source": ref}, occurred_at=clock.now(), source="feedback",
                                        dedupe_key=f"feedback.captured:{ref}"))
    return out


def feedback_summary(conn: Connection) -> list[dict]:
    """Per-topic counts by DISTINCT accounts (mentions reported alongside, never used for ranking). Rejected items excluded."""
    rows = conn.execute("SELECT COALESCE(topic,'untagged') AS topic, count(DISTINCT account_id) AS distinct_accounts, count(*) AS mentions "
                        "FROM gtm.feedback_item WHERE review_status <> 'rejected' AND account_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()
    return [dict(r) for r in rows]


def build_graphs():
    from ..orchestration import Graph

    def run(ctx):
        t = ctx.trigger
        if t.type == EventType.LOST_DEAL_REVIEW_SAVED:
            kw = {"lost_deal_review_id": int(t.payload["review_id"])}
        else:
            iid = t.payload.get("interaction_id") or str(t.entity_ref or "").split(":")[-1]
            kw = {"interaction_id": int(iid)}
        return extract_feedback(ctx.conn, ctx.clock, ctx.services.llm, run_id=ctx.run_id, **kw)

    g = Graph("feedback_extract", version="1")
    g.trigger("on_feedback_source", [EventType.LOST_DEAL_REVIEW_SAVED, EventType.INTERACTION_STORED])
    g.code("extract", run)
    return [g]
