"""Provider waterfall (docs/data-model.md 6): first-party first, then providers by expected cost per correct answer.

No retries here: RetryableError/PermanentError from a provider call propagate out of `fetch_provider` unchanged.
`enrich_entity` continues past a RetryableError (records a gap) so one flaky provider does not sink the run.
"""
from __future__ import annotations
from dataclasses import dataclass, field as dc_field
from typing import Callable
from psycopg import Connection
from gtm import audit
from gtm.adapters import ProviderClient
from gtm.clock import Clock
from gtm.contracts.errors import RetryableError
from gtm.world import provider_params
from .survivorship import (active_observations, freshness, load_sources, prior_reliability, record_observation, resolve_fields, ttl_days)

# internal field -> provider field (only the parent link differs)
_TO_PROVIDER = {"parent_domain": "parent_id"}
_FROM_PROVIDER = {v: k for k, v in _TO_PROVIDER.items()}


def _default_capabilities() -> dict[str, dict[str, set[str]]]:
    caps = {}
    for p in provider_params():
        caps[p.name] = {"account": {_FROM_PROVIDER.get(f, f) for f in p.fields if not f.startswith("person.")},
                        "contact": {f[len("person."):] for f in p.fields if f.startswith("person.")}}
    return caps


CAPABILITIES = _default_capabilities()


@dataclass
class EnrichmentResult:
    request_id: int
    status: str                                   # complete | partial | budget_exhausted
    fields: dict[str, dict]                       # field -> {"status": satisfied|existing|low_confidence|unknown, "source", "confidence"}
    cost: float
    providers_tried: list[str]
    gaps: list[str]
    failures: list[dict] = dc_field(default_factory=list)
    resolved: dict[str, dict] = dc_field(default_factory=dict)


def _entity_keys(conn: Connection, entity_type: str, entity_id: int) -> dict:
    if entity_type == "account":
        r = conn.execute("SELECT name, primary_domain FROM gtm.account WHERE id=%s", (entity_id,)).fetchone()
        return {"name": r["name"], "domain": r["primary_domain"]}
    r = conn.execute("SELECT email, full_name, title FROM gtm.contact WHERE id=%s", (entity_id,)).fetchone()
    return {"email": r["email"], "full_name": r["full_name"], "title": r["title"]}


def record_first_party(conn: Connection, clock: Clock, entity_type: str, entity_id: int, run_id: int | None = None) -> list[int]:
    """Write first-party observations from the internal row (name/domain, or full_name/title) if not already present."""
    row = _entity_keys(conn, entity_type, entity_id)
    mapping = {"name": row.get("name"), "domain": row.get("domain")} if entity_type == "account" else {"full_name": row.get("full_name"), "title": row.get("title")}
    have = {o["field"] for o in active_observations(conn, entity_type, entity_id) if o["source"] == "first_party"}
    ids = []
    for f, v in mapping.items():
        if v and f not in have:
            ids.append(record_observation(conn, clock, entity_type=entity_type, entity_id=entity_id, field=f, value=v, source="first_party",
                                          raw_ref="internal_row", run_id=run_id, data_origin="SCR"))
    return ids


def fetch_provider(conn: Connection, clock: Clock, client: ProviderClient, provider_name: str, entity_type: str, entity_id: int,
                   fields: list[str], *, run_id: int | None = None, parent_resolver: Callable[[str], str | None] | None = None) -> dict:
    """One provider call; writes one immutable observation per returned field. `parent_resolver` maps a provider's parent
    reference to a domain (stored as `parent_domain`); without it the raw reference is stored as `parent_ref`."""
    keys = _entity_keys(conn, entity_type, entity_id)
    pfields = [_TO_PROVIDER.get(f, f) for f in fields]
    if entity_type == "account":
        resp = client.company(domain=keys["domain"], name=None if keys["domain"] else keys["name"], fields=pfields)
        raw = f"{provider_name}:company:{keys['domain'] or keys['name']}"
    else:
        resp = client.person(email=keys["email"], fields=pfields)
        raw = f"{provider_name}:person:{keys['email']}"
    obs: dict[str, int] = {}
    for pf, pv in resp.fields.items():
        f, value = _FROM_PROVIDER.get(pf, pf), pv.value
        if f == "parent_domain":
            if value is None:
                pass
            elif parent_resolver is not None:
                value = parent_resolver(value)
            else:
                f = "parent_ref"
            if value is None:
                continue
        obs[f] = record_observation(conn, clock, entity_type=entity_type, entity_id=entity_id, field=f, value=value, source=provider_name,
                                    observed_at=pv.as_of, raw_ref=raw, run_id=run_id, data_origin="SIM")
    return {"provider": provider_name, "found": resp.found, "observation_ids": obs, "cost_units": float(resp.cost_units), "partial": resp.partial}


def _status(conn, clock, sources, entity_type, entity_id, f, min_conf) -> dict:
    """Best usable observation for f: not expired, confidence >= bar."""
    now = clock.now()
    best, any_obs = None, False
    for o in active_observations(conn, entity_type, entity_id, f):
        any_obs = True
        state, _ = freshness((now - o["observed_at"]).total_seconds() / 86400, ttl_days(f))
        if state != "expired" and (best is None or float(o["confidence"]) > best["confidence"]):
            best = {"source": o["source"], "confidence": float(o["confidence"]), "state": state}
    if best and best["confidence"] >= min_conf:
        return {"status": "satisfied", "source": best["source"], "confidence": best["confidence"]}
    if best or any_obs:
        return {"status": "low_confidence", "source": best["source"] if best else None, "confidence": best["confidence"] if best else None}
    return {"status": "unknown", "source": None, "confidence": None}


def enrich_entity(conn: Connection, clock: Clock, providers: dict[str, ProviderClient], *, entity_type: str, entity_id: int,
                  fields: list[str], cost_cap: float, mode: str = "sequential", run_id: int | None = None, min_confidence: float = 0.75,
                  parent_resolver: Callable[[str], str | None] | None = None, resolve: bool = True,
                  capabilities: dict | None = None) -> EnrichmentResult:
    """sequential: ask providers one at a time, cheapest-per-correct-answer first, stopping per field once the bar is met.
    parallel: ask every capable provider for every field not already satisfied by existing data (no early stop; cost cap still applies)."""
    if mode not in ("sequential", "parallel"):
        raise ValueError("mode must be 'sequential' or 'parallel'")
    caps = capabilities or CAPABILITIES
    sources = load_sources(conn)
    now = clock.now()
    req = conn.execute("INSERT INTO gtm.enrichment_request(entity_type, entity_id, fields_wanted, status, cost_cap, run_id, created_at) "
                       "VALUES (%s,%s,%s,'running',%s,%s,%s) RETURNING id", (entity_type, entity_id, fields, cost_cap, run_id, now)).fetchone()["id"]
    record_first_party(conn, clock, entity_type, entity_id, run_id)
    state = {f: _status(conn, clock, sources, entity_type, entity_id, f, min_confidence) for f in fields}
    for f, s in state.items():
        if s["status"] == "satisfied":
            s["status"] = "existing"      # already met the bar from first-party/earlier data: no provider call needed
    tried: list[str] = []
    failures: list[dict] = []
    spent, budget_hit = 0.0, False
    remaining = [p for p in providers if p in sources]
    asked: set[str] = set()

    def unmet() -> list[str]:
        return [f for f in fields if state[f]["status"] not in ("satisfied", "existing")]

    def efficiency(p: str, need: list[str]) -> float:
        rel = sum(prior_reliability(sources[p], f) for f in need) / len(need)
        return float(sources[p]["cost_per_call"]) / rel

    parallel_need = unmet()
    while True:
        need_all = parallel_need if mode == "parallel" else unmet()
        cands = [(p, [f for f in need_all if f in caps.get(p, {}).get(entity_type, set())]) for p in remaining if p not in asked]
        cands = [(p, n) for p, n in cands if n]
        if not cands:
            break
        p, need = min(cands, key=lambda t: (efficiency(t[0], t[1]), t[0]))
        asked.add(p)
        cost = float(sources[p]["cost_per_call"])
        if spent + cost > cost_cap:
            budget_hit = True
            break
        try:
            res = fetch_provider(conn, clock, providers[p], p, entity_type, entity_id, need, run_id=run_id, parent_resolver=parent_resolver)
        except RetryableError as e:
            tried.append(f"{p}:failed")
            failures.append({"provider": p, "error": str(e), "retry_after": e.retry_after, "fields": need})
            continue
        spent += res["cost_units"]
        tried.append(p)
        for f in need:
            state[f] = _status(conn, clock, sources, entity_type, entity_id, f, min_confidence)
    gaps = [f for f in fields if state[f]["status"] == "unknown"]
    status = "complete" if not unmet() else ("budget_exhausted" if budget_hit else "partial")
    conn.execute("UPDATE gtm.enrichment_request SET status=%s, providers_tried=%s, cost_total=%s, completed_at=%s WHERE id=%s",
                 (status, tried, spent, clock.now(), req))
    audit.append(conn, clock, actor_type="system", actor_id="system:orchestrator", event_type="enrichment.completed",
                 entity_ref=f"{entity_type}:{entity_id}", run_id=run_id,
                 data={"request_id": req, "status": status, "cost": spent, "providers": tried, "gaps": gaps, "mode": mode})
    resolved = resolve_fields(conn, clock, entity_type, entity_id, [f for f in fields if state[f]["status"] != "unknown"]) if resolve else {}
    return EnrichmentResult(request_id=req, status=status, fields=state, cost=spent, providers_tried=tried, gaps=gaps, failures=failures, resolved=resolved)
