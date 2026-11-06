"""Entity resolution (docs/data-model.md 5): normalise, block, score, three bands. Never auto-merges.

resolve_* are read-only and return a MatchDecision. ensure_* act on it: same -> link (non-destructive), possible -> create the
new row and record a pending entity_match (the caller turns it into a G1 proposal via `propose_match`), distinct -> create.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from psycopg import Connection
from psycopg.types.json import Jsonb
from gtm import audit
from gtm.clock import Clock

ROLE_LOCALS = {"info", "sales", "hello", "support", "admin", "contact", "office", "enquiries", "inquiries", "team", "help", "marketing",
               "hr", "accounts", "billing", "noreply", "no-reply", "careers", "jobs", "press", "service", "mail", "reception"}
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "aol.com", "proton.me",
             "protonmail.com", "gmx.com", "mail.com", "msn.com", "yandex.com", "freemail.example", "webmail.example"}
LEGAL_SUFFIXES = {"ltd", "limited", "inc", "incorporated", "llc", "plc", "gmbh", "corp", "corporation", "co", "company", "sa", "bv", "ag", "pty", "llp", "lp"}
SAME_NAME_SIM = 0.9
POSSIBLE_SCORE = 0.6


# ---------- normalisation ----------
def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, dom = e.rsplit("@", 1)
    return f"{local.split('+', 1)[0]}@{dom.removeprefix('www.')}"


def is_role_mailbox(email: str) -> bool:
    local = normalize_email(email).split("@", 1)[0]
    return local in ROLE_LOCALS


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    d = re.sub(r"^[a-z]+://", "", domain.strip().lower()).split("/", 1)[0].split("@")[-1]
    return d.removeprefix("www.") or None


def account_domain_key(domain: str | None) -> str | None:
    """Normalised domain usable as an account key (free-mail domains are not)."""
    d = normalize_domain(domain)
    return None if d is None or d in FREE_MAIL else d


def normalize_company_name(name: str) -> str:
    toks = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and ")).split()
    while len(toks) > 1 and toks[-1] in LEGAL_SUFFIXES:
        toks.pop()
    return " ".join(toks)


def normalize_person_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]+", " ", (name or "").lower()).split())


# ---------- decision object ----------
@dataclass
class MatchDecision:
    entity_type: str
    band: str                              # same | possible | distinct
    candidate_id: int | None = None
    score: float = 0.0
    features: dict = field(default_factory=dict)
    reason: str = ""
    candidates: list[tuple[int, float]] = field(default_factory=list)
    remembered_negative: bool = False
    match_id: int | None = None            # entity_match row once recorded

    @property
    def needs_proposal(self) -> bool:
        return self.band == "possible"


def _sim(conn: Connection, a: str, b: str) -> float:
    return float(conn.execute("SELECT similarity(%s,%s) AS s", (a, b)).fetchone()["s"])


def _existing_match(conn: Connection, etype: str, a: int, b: int) -> dict | None:
    return conn.execute("SELECT * FROM gtm.entity_match WHERE entity_type=%s AND ((left_id=%s AND right_id=%s) OR (left_id=%s AND right_id=%s)) "
                        "ORDER BY id LIMIT 1", (etype, a, b, b, a)).fetchone()


def record_match(conn: Connection, clock: Clock, etype: str, left: int, right: int, score: float, features: dict, band: str,
                 decision: str = "pending", decided_by: str | None = None, is_negative: bool = False) -> int:
    return conn.execute(
        "INSERT INTO gtm.entity_match(entity_type, left_id, right_id, score, features, band, decision, decided_by, is_negative, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (entity_type, left_id, right_id) DO UPDATE SET score=EXCLUDED.score, "
        "features=gtm.entity_match.features || EXCLUDED.features RETURNING id",
        (etype, left, right, round(score, 4), Jsonb(features), band, decision, decided_by, is_negative, clock.now())).fetchone()["id"]


def _band_from(candidates: list[dict]) -> tuple[str, dict | None, str]:
    if not candidates:
        return "distinct", None, "no_candidates"
    candidates.sort(key=lambda c: (-c["score"], c["id"]))
    sames = [c for c in candidates if c["band"] == "same"]
    if len(sames) > 1:
        return "possible", sames[0], "multiple_same_candidates"
    if sames:
        return "same", sames[0], sames[0]["reason"]
    best = candidates[0]
    return best["band"], best, best["reason"]


# ---------- accounts ----------
def _account_domains(conn: Connection, account_id: int) -> set[str]:
    rows = conn.execute("SELECT domain FROM gtm.account_domain WHERE account_id=%s UNION SELECT primary_domain FROM gtm.account "
                        "WHERE id=%s AND primary_domain IS NOT NULL", (account_id, account_id)).fetchall()
    return {r["domain"] for r in rows}


def score_account(name_sim: float, domain_exact: bool, domains_conflict: bool) -> tuple[float, str, str]:
    """-> (score, band, reason). `same` needs an exact domain AND name similarity >= 0.9; name-only evidence caps at 0.85."""
    score = max(0.5 * domain_exact + 0.5 * name_sim, 0.85 * name_sim)
    if domain_exact and name_sim >= SAME_NAME_SIM:
        return score, "same", "domain_and_name"
    if domain_exact:    # conflicting strong keys (same domain, different name): a human decides
        return max(score, POSSIBLE_SCORE), "possible", "domain_exact_name_differs"
    if score >= POSSIBLE_SCORE:
        return score, "possible", "name_only_domains_differ" if domains_conflict else "name_only"
    return score, "distinct", "low_score"


def resolve_account(conn: Connection, clock: Clock, *, name: str, domain: str | None = None, exclude_ids: set[int] | None = None) -> MatchDecision:
    exclude_ids = exclude_ids or set()
    dom = account_domain_key(domain)
    nname = normalize_company_name(name)
    rows = conn.execute("SELECT DISTINCT a.id, a.name FROM gtm.account a LEFT JOIN gtm.account_domain d ON d.account_id=a.id "
                        "WHERE a.merged_into_id IS NULL AND (a.primary_domain=%s OR d.domain=%s OR similarity(a.name,%s) >= 0.25 "
                        "OR similarity(lower(a.name),%s) >= 0.25)", (dom, dom, name, nname)).fetchall()
    cands, negatives = [], 0
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        doms = _account_domains(conn, r["id"])
        exact = dom is not None and dom in doms
        sim = _sim(conn, nname, normalize_company_name(r["name"]))
        conflict = dom is not None and bool(doms) and not exact
        score, band, reason = score_account(sim, exact, conflict)
        if band == "distinct":
            continue
        cands.append({"id": r["id"], "score": score, "band": band, "reason": reason, "features": {"name_sim": round(sim, 3), "domain_exact": exact, "domains_conflict": conflict}})
    return _finish("account", cands)


def _finish(etype: str, cands: list[dict]) -> MatchDecision:
    band, best, reason = _band_from(cands)
    d = MatchDecision(entity_type=etype, band=band, reason=reason, candidates=[(c["id"], round(c["score"], 3)) for c in cands])
    if best:
        d.candidate_id, d.score, d.features = best["id"], round(best["score"], 4), best["features"]
    return d


def _apply_memory(conn: Connection, d: MatchDecision, new_id: int | None) -> MatchDecision:
    """A human 'distinct' decision between new_id and the candidate is remembered: never re-ask."""
    if new_id is not None and d.candidate_id is not None and d.band != "distinct":
        m = _existing_match(conn, d.entity_type, new_id, d.candidate_id)
        if m and m["is_negative"]:
            return MatchDecision(entity_type=d.entity_type, band="distinct", reason="remembered_negative", remembered_negative=True,
                                 candidates=d.candidates, match_id=m["id"])
        if m and m["decision"] == "same":
            d.band, d.reason, d.match_id = "same", "human_confirmed", m["id"]
    return d


def ensure_account(conn: Connection, clock: Clock, *, name: str, domain: str | None = None, data_origin: str = "SCR",
                   parent_domain: str | None = None) -> tuple[int, MatchDecision]:
    """Returns (account_id, decision). same -> existing id (alias domain added); possible -> new row + pending entity_match; distinct -> new row."""
    d = resolve_account(conn, clock, name=name, domain=domain)
    dom = account_domain_key(domain)
    now = clock.now()
    if d.band == "same":
        aid = d.candidate_id
        if dom and dom not in _account_domains(conn, aid):
            conn.execute("INSERT INTO gtm.account_domain(account_id, domain, is_primary) VALUES (%s,%s,false) ON CONFLICT DO NOTHING", (aid, dom))
        d.match_id = record_match(conn, clock, "account", aid, aid, d.score, {**d.features, "kind": "link", "incoming_name": name, "incoming_domain": dom},
                                  "same", "same", "system:er")
        audit.append(conn, clock, actor_type="system", actor_id="system:rules", event_type="er.linked", entity_ref=f"account:{aid}", data={"name": name, "domain": dom, "score": d.score})
        return aid, d
    aid = conn.execute("INSERT INTO gtm.account(name, primary_domain, data_origin, created_at, updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                       (name, dom if not _domain_taken(conn, dom) else None, data_origin, now, now)).fetchone()["id"]
    if dom:
        conn.execute("INSERT INTO gtm.account_domain(account_id, domain, is_primary) VALUES (%s,%s,true) ON CONFLICT DO NOTHING", (aid, dom))
    if d.band == "possible":
        d.match_id = record_match(conn, clock, "account", aid, d.candidate_id, d.score, {**d.features, "reason": d.reason}, "possible")
    return aid, _apply_memory(conn, d, aid)


def _domain_taken(conn: Connection, dom: str | None) -> bool:
    return bool(dom) and conn.execute("SELECT 1 FROM gtm.account WHERE primary_domain=%s AND merged_into_id IS NULL", (dom,)).fetchone() is not None


# ---------- contacts ----------
def resolve_contact(conn: Connection, clock: Clock, *, email: str, full_name: str, company_name: str | None = None,
                    exclude_ids: set[int] | None = None) -> MatchDecision:
    exclude_ids = exclude_ids or set()
    ne = normalize_email(email)
    local, _, dom = ne.partition("@")
    if local in ROLE_LOCALS:
        r = conn.execute("SELECT id FROM gtm.contact WHERE merged_into_id IS NULL AND lower(email)=%s", (ne,)).fetchone()
        if r:  # the same shared mailbox seen again (never a person)
            return MatchDecision("contact", "same", r["id"], 1.0, {"role_mailbox": True}, "same_role_mailbox", [(r["id"], 1.0)])
        return MatchDecision("contact", "distinct", reason="role_mailbox", features={"role_mailbox": True})
    exact = conn.execute("SELECT id, email FROM gtm.contact WHERE merged_into_id IS NULL AND email IS NOT NULL "
                         "AND lower(regexp_replace(email, '\\+[^@]*@', '@')) = %s", (ne,)).fetchall()
    exact = [r for r in exact if not is_role_mailbox(r["email"]) and r["id"] not in exclude_ids]
    if exact:
        return MatchDecision("contact", "same", exact[0]["id"], 1.0, {"email_exact": True}, "email_exact", [(r["id"], 1.0) for r in exact])
    nname = normalize_person_name(full_name)
    nco = normalize_company_name(company_name) if company_name else None
    rows = conn.execute("SELECT c.id, c.full_name, c.email, c.account_id, a.name AS account_name FROM gtm.contact c LEFT JOIN gtm.account a ON a.id=c.account_id "
                        "WHERE c.merged_into_id IS NULL AND similarity(lower(c.full_name), %s) >= 0.5", (nname,)).fetchall()
    cands = []
    for r in rows:
        if r["id"] in exclude_ids or (r["email"] and is_role_mailbox(r["email"])):
            continue
        sim = _sim(conn, nname, normalize_person_name(r["full_name"]))
        cdoms = _account_domains(conn, r["account_id"]) if r["account_id"] else set()
        cdoms |= {normalize_email(r["email"]).split("@")[1]} if r["email"] else set()
        same_dom = account_domain_key(dom) is not None and dom in cdoms
        co_sim = _sim(conn, nco, normalize_company_name(r["account_name"])) if nco and r["account_name"] else 0.0
        rel = 1.0 if same_dom else (0.6 if co_sim >= SAME_NAME_SIM else 0.0)
        score = min(0.7 * sim + 0.3 * rel, 0.89)         # no exact email => never 'same'
        if score < POSSIBLE_SCORE:
            continue
        cands.append({"id": r["id"], "score": score, "band": "possible", "reason": "name_and_affiliation",
                      "features": {"name_sim": round(sim, 3), "same_domain": same_dom, "company_sim": round(co_sim, 3)}})
    return _finish("contact", cands)


def ensure_contact(conn: Connection, clock: Clock, *, email: str, full_name: str, company_name: str | None = None, account_id: int | None = None,
                   title: str | None = None, data_origin: str = "SCR") -> tuple[int, MatchDecision]:
    d = resolve_contact(conn, clock, email=email, full_name=full_name, company_name=company_name)
    if d.band == "same":
        d.match_id = record_match(conn, clock, "contact", d.candidate_id, d.candidate_id, d.score,
                                  {**d.features, "kind": "link", "incoming_email": email}, "same", "same", "system:er")
        return d.candidate_id, d
    now = clock.now()
    cid = conn.execute("INSERT INTO gtm.contact(account_id, full_name, email, title, data_origin, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                       (account_id, full_name, email.strip(), title, data_origin, now, now)).fetchone()["id"]
    d = _apply_memory(conn, d, cid)
    if d.band == "possible":
        d.match_id = record_match(conn, clock, "contact", cid, d.candidate_id, d.score, {**d.features, "reason": d.reason}, "possible")
    return cid, d


# ---------- duplicate scan, proposals ----------
def scan_duplicates(conn: Connection, clock: Clock, entity_type: str = "account", *, record: bool = False) -> list[MatchDecision]:
    """Pairwise scan of existing rows: returns 'same'/'possible' pairs not already decided. Humans' 'distinct' decisions are skipped."""
    out = []
    if entity_type == "account":
        rows = conn.execute("SELECT id, name FROM gtm.account WHERE merged_into_id IS NULL ORDER BY id").fetchall()
        doms = {r["id"]: _account_domains(conn, r["id"]) for r in rows}
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if (m := _existing_match(conn, "account", a["id"], b["id"])) and (m["is_negative"] or m["decision"] != "pending"):
                    continue
                shared = bool(doms[a["id"]] & doms[b["id"]])
                conflict = bool(doms[a["id"]] and doms[b["id"]]) and not shared
                sim = _sim(conn, normalize_company_name(a["name"]), normalize_company_name(b["name"]))
                score, band, reason = score_account(sim, shared, conflict)
                if band != "distinct":
                    d = MatchDecision("account", band, b["id"], round(score, 4), {"name_sim": round(sim, 3), "domain_exact": shared}, reason, [(b["id"], round(score, 4))])
                    d.features["left_id"] = a["id"]
                    if record:
                        d.match_id = record_match(conn, clock, "account", a["id"], b["id"], score, d.features, band)
                    out.append(d)
    return out


def propose_match(conn: Connection, clock: Clock, d: MatchDecision, new_id: int, *, proposed_by: str = "system:rules", account_id: int | None = None,
                  emit=None) -> int | None:
    """Create the G1 match_confirmation proposal for a 'possible' decision. Idempotent per pair; returns None when a human already
    decided this pair (negative-match memory) so the question is never re-asked."""
    from gtm.approvals import create_proposal
    m = _existing_match(conn, d.entity_type, new_id, d.candidate_id)
    if m and (m["is_negative"] or m["decision"] != "pending"):
        return None
    lo, hi = sorted((new_id, d.candidate_id))
    return create_proposal(conn, clock, type="match_confirmation", proposed_by=proposed_by, account_id=account_id,
                           payload={"entity_type": d.entity_type, "left_id": new_id, "right_id": d.candidate_id, "score": d.score},
                           evidence=[{"features": d.features, "reason": d.reason}], rationale=f"possible duplicate ({d.reason})",
                           confidence=d.score, idempotency_key=f"match:{d.entity_type}:{lo}:{hi}", emit=emit)


# ---------- hierarchy ----------
def attach_parent(conn: Connection, clock: Clock, account_id: int, parent_domain: str, *, source: str = "provider_b", confidence: float | None = None) -> int | None:
    """Link `account_id` as a subsidiary of the existing account owning `parent_domain` (from a parent_domain observation).
    Returns the parent account id, or None if the parent is unknown, is the account itself, or would create a cycle."""
    dom = account_domain_key(parent_domain)
    if dom is None:
        return None
    p = conn.execute("SELECT a.id FROM gtm.account a LEFT JOIN gtm.account_domain d ON d.account_id=a.id WHERE a.merged_into_id IS NULL "
                     "AND (a.primary_domain=%s OR d.domain=%s) ORDER BY a.id LIMIT 1", (dom, dom)).fetchone()
    if not p or p["id"] == account_id:
        return None
    cur, seen = p["id"], set()
    while cur is not None and cur not in seen:           # cycle guard: the parent must not descend from the child
        if cur == account_id:
            return None
        seen.add(cur)
        row = conn.execute("SELECT parent_account_id FROM gtm.account WHERE id=%s", (cur,)).fetchone()
        cur = row["parent_account_id"] if row else None
    if not conn.execute("SELECT 1 FROM gtm.account_relationship WHERE from_account_id=%s AND to_account_id=%s AND type='parent_of'", (p["id"], account_id)).fetchone():
        conn.execute("INSERT INTO gtm.account_relationship(from_account_id, to_account_id, type, source, confidence) VALUES (%s,%s,'parent_of',%s,%s)",
                     (p["id"], account_id, source, confidence))
    now = clock.now()
    conn.execute("UPDATE gtm.account SET parent_account_id=%s, hierarchy_role='subsidiary', updated_at=%s WHERE id=%s", (p["id"], now, account_id))
    conn.execute("UPDATE gtm.account SET hierarchy_role='ultimate_parent', updated_at=%s WHERE id=%s AND parent_account_id IS NULL AND hierarchy_role='standalone'", (now, p["id"]))
    return p["id"]


def attach_parent_from_resolved(conn: Connection, clock: Clock, account_id: int) -> int | None:
    r = conn.execute("SELECT value, confidence FROM gtm.resolved_field WHERE entity_type='account' AND entity_id=%s AND field='parent_domain'", (account_id,)).fetchone()
    return attach_parent(conn, clock, account_id, r["value"], confidence=float(r["confidence"])) if r and r["value"] else None
