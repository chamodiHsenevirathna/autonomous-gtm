"""Observations, freshness and survivorship (docs/data-model.md 7.1-7.3).

Observations are immutable (only `superseded_by` is ever set). `resolve_fields` derives gtm.resolved_field from them.
Functions use the caller's transaction and never commit.
"""
from __future__ import annotations
import json
from datetime import datetime
from psycopg import Connection
from psycopg.types.json import Jsonb
from gtm.clock import Clock

# days; field group TTLs from docs 7.3 ([A] assumptions)
TTL_DAYS = {"domain": 365, "legal_name": 365, "name": 365, "employee_count": 120, "revenue_band": 120, "industry": 120,
            "tech_stack": 60, "hiring_signals": 14, "title": 90, "seniority": 90, "full_name": 365, "region": 365,
            "hq_country": 365, "parent_domain": 365, "email": 365}
DEFAULT_TTL = 180
CONFLICT_MARGIN = 0.15        # runner-up within 15% of the winner => conflict
CONFLICT_CONF_CAP = 0.5       # confidence cap when conflicted


def ttl_days(field: str) -> int:
    return TTL_DAYS.get(field, DEFAULT_TTL)


def freshness(age_days: float, ttl: int) -> tuple[str, float]:
    """(state, factor). fresh <= ttl/2 (factor 1); stale <= ttl (factor falls 1 -> 0.5); expired > ttl (factor 0, excluded from scoring)."""
    age_days = max(age_days, 0.0)
    if age_days <= ttl / 2:
        return "fresh", 1.0
    if age_days <= ttl:
        return "stale", 1.0 - 0.5 * ((age_days - ttl / 2) / (ttl / 2))
    return "expired", 0.0


def normalise_value(field: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(sorted(str(x).strip().lower() for x in value))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = str(value).strip().lower()
    if field in ("domain", "parent_domain"):
        s = s.removeprefix("www.")
    return s


def load_sources(conn: Connection) -> dict[str, dict]:
    return {r["name"]: r for r in conn.execute("SELECT * FROM gtm.data_source")}


def prior_reliability(source: dict, field: str) -> float:
    """Per-field prior; falls back to the source's '*' prior, else the mean of its listed priors, else 0.5."""
    rel = source["field_reliability"] or {}
    if field in rel:
        return float(rel[field])
    if "*" in rel:
        return float(rel["*"])
    return sum(map(float, rel.values())) / len(rel) if rel else 0.5


def record_observation(conn: Connection, clock: Clock, *, entity_type: str, entity_id: int, field: str, value, source: str,
                       observed_at: datetime | None = None, confidence: float | None = None, raw_ref: str | None = None,
                       run_id: int | None = None, data_origin: str = "SIM") -> int:
    """Insert an immutable observation; the previous active one from the same source/field is superseded (retained)."""
    src = load_sources(conn)[source]
    now = clock.now()
    conf = confidence if confidence is not None else prior_reliability(src, field)
    oid = conn.execute(
        "INSERT INTO gtm.observation(entity_type, entity_id, field, value, value_normalised, data_source_id, observed_at, fetched_at, "
        "confidence, raw_ref, run_id, data_origin) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (entity_type, entity_id, field, Jsonb(value), normalise_value(field, value), src["id"], observed_at or now, now, conf, raw_ref,
         run_id, data_origin)).fetchone()["id"]
    conn.execute("UPDATE gtm.observation SET superseded_by=%s WHERE entity_type=%s AND entity_id=%s AND field=%s AND data_source_id=%s "
                 "AND superseded_by IS NULL AND id<>%s", (oid, entity_type, entity_id, field, src["id"], oid))
    return oid


def active_observations(conn: Connection, entity_type: str, entity_id: int, field: str | None = None) -> list[dict]:
    q = ("SELECT o.*, s.name AS source, s.kind AS source_kind, s.field_reliability FROM gtm.observation o "
         "JOIN gtm.data_source s ON s.id=o.data_source_id WHERE o.entity_type=%s AND o.entity_id=%s AND o.superseded_by IS NULL")
    args: list = [entity_type, entity_id]
    if field:
        q += " AND o.field=%s"
        args.append(field)
    return conn.execute(q + " ORDER BY o.id", args).fetchall()


def _score_group(obs: list[dict], now: datetime, field: str) -> dict:
    """Per source take its best contribution; independent sources combine as 1-(1-c1)(1-c2)."""
    best: dict[int, tuple[float, dict]] = {}
    for o in obs:
        age = (now - o["observed_at"]).total_seconds() / 86400
        state, factor = freshness(age, ttl_days(field))
        c = float(o["confidence"]) * factor
        if o["data_source_id"] not in best or c > best[o["data_source_id"]][0]:
            best[o["data_source_id"]] = (c, {**o, "state": state})
    miss = 1.0
    for c, _ in best.values():
        miss *= 1 - c
    top = max(best.values(), key=lambda t: (t[0], -t[1]["id"]))[1]
    return {"score": 1 - miss, "obs": top, "sources": len(best)}


def resolve_field(conn: Connection, clock: Clock, entity_type: str, entity_id: int, field: str) -> dict | None:
    now = clock.now()
    obs = active_observations(conn, entity_type, entity_id, field)
    if not obs:
        return None
    ttl = ttl_days(field)
    ages = {o["id"]: (now - o["observed_at"]).total_seconds() / 86400 for o in obs}
    state_of = {i: freshness(a, ttl)[0] for i, a in ages.items()}
    human = [o for o in obs if o["source_kind"] == "human_entered"]
    machine = [o for o in obs if o["source_kind"] != "human_entered"]
    live = [o for o in machine if state_of[o["id"]] != "expired"]
    needs_review = False
    win = None
    if human:
        h = max(human, key=lambda o: (o["observed_at"], o["id"]))
        contradicting = {}
        if state_of[h["id"]] == "expired":
            for o in live:
                if o["value_normalised"] != h["value_normalised"]:
                    contradicting.setdefault(o["value_normalised"], set()).add(o["data_source_id"])
        if state_of[h["id"]] == "expired" and any(len(s) >= 2 for s in contradicting.values()):
            needs_review = True      # expired human value contradicted by two independent sources: machine value used, caller proposes
        else:
            win = dict(value=h["value"], conf=float(h["confidence"]), state=state_of[h["id"]], oid=h["id"], conflict=False)
    if win is None:
        if live:
            groups: dict[str, list[dict]] = {}
            for o in live:
                groups.setdefault(o["value_normalised"], []).append(o)
            scored = sorted(((_score_group(g, now, field), k) for k, g in groups.items()), key=lambda t: (-t[0]["score"], t[1]))
            top, runner = scored[0][0], (scored[1][0] if len(scored) > 1 else None)
            conf = top["score"]
            conflict = False
            if runner:
                conf *= 1 - 0.5 * runner["score"]
                if runner["score"] >= (1 - CONFLICT_MARGIN) * top["score"]:
                    conflict, conf = True, min(conf, CONFLICT_CONF_CAP)
            agree = groups[scored[0][1]]
            state = min((state_of[o["id"]] for o in agree), key=["fresh", "stale"].index)
            win = dict(value=top["obs"]["value"], conf=conf, state=state, oid=top["obs"]["id"], conflict=conflict or needs_review)
        else:  # everything is expired: show the latest value, do not trust it
            o = max(obs, key=lambda o: (o["observed_at"], o["id"]))
            win = dict(value=o["value"], conf=round(float(o["confidence"]) * 0.25, 3), state="expired", oid=o["id"], conflict=needs_review)
    conn.execute(
        "INSERT INTO gtm.resolved_field(entity_type, entity_id, field, value, confidence, freshness_state, winning_observation_id, conflict_flag, resolved_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (entity_type, entity_id, field) DO UPDATE SET value=EXCLUDED.value, "
        "confidence=EXCLUDED.confidence, freshness_state=EXCLUDED.freshness_state, winning_observation_id=EXCLUDED.winning_observation_id, "
        "conflict_flag=EXCLUDED.conflict_flag, resolved_at=EXCLUDED.resolved_at",
        (entity_type, entity_id, field, Jsonb(win["value"]), round(win["conf"], 4), win["state"], win["oid"], win["conflict"], now))
    return {"value": win["value"], "confidence": round(win["conf"], 4), "freshness_state": win["state"], "conflict_flag": win["conflict"],
            "winning_observation_id": win["oid"], "needs_human_review": needs_review}


def resolve_fields(conn: Connection, clock: Clock, entity_type: str, entity_id: int, fields: list[str] | None = None) -> dict[str, dict]:
    if fields is None:
        fields = [r["field"] for r in conn.execute("SELECT DISTINCT field FROM gtm.observation WHERE entity_type=%s AND entity_id=%s ORDER BY field",
                                                    (entity_type, entity_id))]
    out = {}
    for f in fields:
        r = resolve_field(conn, clock, entity_type, entity_id, f)
        if r is not None:
            out[f] = r
    return out


def get_resolved(conn: Connection, entity_type: str, entity_id: int) -> dict[str, dict]:
    """Resolved fields with provenance for the UI: value, confidence, freshness_state, conflict_flag, sources[]."""
    out: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM gtm.resolved_field WHERE entity_type=%s AND entity_id=%s ORDER BY field", (entity_type, entity_id)):
        srcs = []
        for o in active_observations(conn, entity_type, entity_id, r["field"]):
            srcs.append({"observation_id": o["id"], "source": o["source"], "value": o["value"], "confidence": float(o["confidence"]),
                         "observed_at": o["observed_at"].isoformat(), "agrees": json.dumps(o["value"], sort_keys=True) == json.dumps(r["value"], sort_keys=True),
                         "winner": o["id"] == r["winning_observation_id"]})
        out[r["field"]] = {"value": r["value"], "confidence": float(r["confidence"]), "freshness_state": r["freshness_state"],
                           "conflict_flag": r["conflict_flag"], "sources": srcs}
    return out
