"""Row -> API-shape mapping (frontend/API_SPEC.md). Pure reads over one psycopg connection."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from gtm.data.survivorship import get_resolved

ORIGINS = {"GT", "SIM", "SCR", "MOD", "HUM-sim", "HUM-real", "PLT"}
OPEN = ("pending", "blocked", "parked")
ADAPTER = {"message": "outreach.send", "crm_write": "crm.write", "field_change": "db.field_change", "task": "db.task",
           "lead_disposition": "db.lead_disposition", "merge": "db.merge", "match_confirmation": "db.match_confirmation"}
STEP_NAMES = ["Approval valid (role, expiry, hash match, unconsumed)", "Experiment state and holdout", "Content screens on the final hash",
              "Recipient resolution and data quality", "Suppression and do-not-contact pre-check", "Outreach claims and priority",
              "Frequency caps and duplicate-outreach key", "Human-touch lock", "Domain breaker and throttle",
              "Sync precondition (contact visible in target)", "Authoritative suppression re-read, consume approval, write execution row",
              "Adapter call with execution token", "Audit event and domain event"]


def iso(d) -> str | None:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d, datetime) else None


def _origs(xs) -> list[str]:
    return sorted({x for x in xs if x in ORIGINS})


def _q(c, sql, *a):
    return c.execute(sql, a).fetchall()


def _scalar(c, sql, *a):
    return list(c.execute(sql, a).fetchone().values())[0]


# ------------------------------------------------------------------ proposals
def prose(d) -> str:
    """Render a recorded check detail as a readable sentence, never a Python repr."""
    if d is None or d is True or d is False:
        return ""
    if isinstance(d, dict):
        if "decided_by" in d:
            return f"approved by {d['decided_by']} (approval #{d.get('approval_id')})"
        return "; ".join(f"{k.replace('_', ' ')}: {prose(v) or v}" for k, v in d.items())
    if isinstance(d, list):
        return "; ".join(x for x in (prose(i.get("detail") or i.get("flag") or i) if isinstance(i, dict) else prose(i) for i in d) if x)
    return str(d)


def _group_checks(recorded: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in recorded}


def map_checks(ptype: str, recorded: list[dict], status: str, executed: bool, reason: str | None, parked: bool = False) -> list[dict]:
    """Map the gateway's recorded check results onto the 13 canonical steps; 'skipped' when not reached/not applicable."""
    r = _group_checks(recorded)

    def one(names: list[str]):
        got = [r[n] for n in names if n in r]
        if not got:
            return None
        bad = [g for g in got if not g["passed"]]
        return ("failed" if bad else "passed", "; ".join(prose((b if bad else got[0]).get("detail")) for b in (bad or got[:1]))[:300])

    spec = {1: ["approval_valid", "hash_matches", "dependency_executed", "proposal_status"], 3: ["content_screens"], 4: ["recipient_quality"],
            5: ["suppression_precheck"], 6: ["outreach_claims"], 7: ["frequency_cap", "duplicate_outreach"], 8: ["human_touch_lock"],
            9: ["domain_breaker"], 10: ["sync_precondition"], 11: ["suppression_authoritative"], 12: ["adapter"]}
    out = []
    for i, name in enumerate(STEP_NAMES, 1):
        res = one(spec[i]) if i in spec else None
        if i == 2:
            res = ("failed", "experiments are not enabled") if reason == "experiments_not_enabled" else None
            detail = "not applicable: no experiment on this proposal"
        elif i == 11 and res is None and executed:
            res = ("passed", "approval consumed and execution row written in one transaction")
        elif i == 13:
            res = ("passed", "audit and domain event written") if executed else None
            detail = "not reached"
        elif res is None and executed and i == 1:
            res = ("passed", "approval verified")
        if res is None:
            detail = "not applicable to " + ptype if (i in range(3, 11) and ptype != "message") else "not reached"
            if i == 2:
                detail = "not applicable: no experiment on this proposal"
            out.append({"step": i, "name": name, "status": "skipped", "detail": detail})
        elif res[0] == "failed" and parked:       # not ready yet (e.g. sync pending): the step was not passed, but nothing is wrong
            out.append({"step": i, "name": name, "status": "skipped", "detail": "not ready yet: " + (res[1] or "waiting") + "; will be retried"})
        else:
            out.append({"step": i, "name": name, "status": res[0], "detail": res[1] or "ok"})
    return out


def _excerpt(t, n=220) -> str:
    t = " ".join(str(t or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def evidence_item(c, e, p: dict) -> dict:
    """Normalise a stored evidence entry to {kind, ref, text, source, data_origin} with a real excerpt."""
    if not isinstance(e, dict):
        e = {"text": str(e)}
    ref = str(e.get("ref") or ("draft:%s" % e["draft_id"] if "draft_id" in e else ""))
    kind, text, source, origin = e.get("kind"), e.get("text"), e.get("source"), e.get("data_origin")
    head, _, tail = ref.partition(":")
    rationale = _excerpt(p["rationale"])
    if "screen_flags" in e:
        kind, text, source, origin = "screen", prose(e["screen_flags"]) or "content screen flags", "content screen", "MOD"
    elif not text:
        if head == "lead" and tail.isdigit():
            r = c.execute("SELECT raw_payload FROM gtm.lead WHERE id=%s", (int(tail),)).fetchone()
            text = _excerpt((r["raw_payload"] or {}).get("message") if r else "") or rationale
            kind, source, origin = kind or "enquiry", source or "website form", origin or "SCR"
        elif head == "enquiry":
            r = c.execute("SELECT raw_payload FROM gtm.lead ORDER BY id DESC LIMIT 1").fetchone()
            text = _excerpt((r["raw_payload"] or {}).get("message") if r else "") or rationale
            kind, source, origin = kind or "enquiry", source or "website form", origin or "SCR"
        elif head == "interaction" and tail.isdigit():
            r = c.execute("SELECT subject, body FROM gtm.interaction WHERE id=%s", (int(tail),)).fetchone()
            text = _excerpt(((r["subject"] or "") + ": " + (r["body"] or "")) if r else "") or rationale
            kind, source, origin = kind or "interaction", source or "mailbox", origin or "SCR"
        elif head == "draft":
            text = rationale or "Draft prepared by the account agent."
            kind, source, origin = kind or "draft", source or "account agent (mock model)", origin or "MOD"
        elif head == "event":
            text = f"Triggered by event {tail}. {rationale}".strip()
            kind, source, origin = kind or "event", source or "orchestrator", origin or "SCR"
        elif head in ("provider_a", "provider_b", "provider_c", "enrichment"):
            text, kind, source, origin = rationale or "Enrichment result", kind or "enrichment", source or head, origin or "SIM"
        else:
            text = rationale or "See the proposal rationale."
            kind, source, origin = kind or "note", source or "account agent (mock model)", origin or "MOD"
    return {"kind": str(kind or "note"), "ref": ref, "text": str(text or rationale), "source": source,
            "data_origin": origin if origin in ORIGINS else ("MOD" if p["proposed_by"].startswith("agent:") else "SCR")}


def proposal_out(c, p: dict) -> dict:
    pid = p["id"]
    appr = _q(c, "SELECT * FROM ops.approval_decision WHERE proposal_id=%s ORDER BY id", pid)
    decisions, prev = [], p["payload_hash"]
    payload, phash = p["payload"], p["payload_hash"]
    for a in appr:
        edited = a["decision"] == "approve_with_edits"
        decisions.append({"decision": a["decision"], "decided_by": a["decided_by"], "at": iso(a["decided_at"]), "reason_code": a["reason_code"],
                          "comment": a["comment"], "edited": edited, "old_hash": prev if edited else None,
                          "new_hash": a["approved_payload_hash"] if edited else None})
        if a["approved_payload"] is not None:
            payload, phash = a["approved_payload"], a["approved_payload_hash"]
            prev = phash
    status, reason = p["status"], p["block_reason"]
    dep = p["depends_on_proposal_id"]
    block_kind = None
    if status == "pending" and dep:
        d = c.execute("SELECT status FROM ops.proposal WHERE id=%s", (dep,)).fetchone()
        if d and d["status"] in ("rejected", "superseded", "expired", "failed"):
            status, reason = "superseded", f"Dependency #{dep} was {d['status']}"
        elif d and d["status"] != "executed":
            status, reason = "blocked", f"Waiting for proposal #{dep} to be executed"
    if status == "pending" and p["block_class"] == "soft":
        status, block_kind = "blocked", "soft"
    elif p["status"] == "blocked":
        block_kind = p["block_class"] or "hard"
    gw = c.execute("SELECT event_type, data FROM ops.audit_event WHERE proposal_id=%s AND (event_type LIKE 'gateway.%%' OR event_type IN ('execution.completed','proposal.blocked')) "
                   "ORDER BY seq DESC LIMIT 1", (pid,)).fetchone()
    ex = c.execute("SELECT * FROM ops.execution WHERE proposal_id=%s ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    execution = None
    if ex or gw or status in ("executing", "parked") or block_kind:
        adapter = (ex or {}).get("adapter") or ADAPTER.get(p["type"], "none")
        executed = ex is not None and ex["status"] == "succeeded"
        recorded = (gw["data"].get("checks") if gw else None) or []
        reason_gw = gw["data"].get("reason") if gw else None
        est = {"succeeded": "executed", "failed": "failed", "blocked": "blocked"}[ex["status"]] if ex else (
            "blocked" if status in ("blocked", "superseded") else status if status in ("parked", "executing", "failed") else "blocked")
        last = next((a for a in reversed(appr) if a["decision"] != "reject"), None)
        hv = any(x["name"] == "hash_matches" and x["passed"] for x in recorded) or executed
        outcome = ((ex["result"] or {}).get("summary") if ex and ex["result"] else None) or (ex["error"] if ex and ex["error"] else None) \
            or (gw["data"].get("reason") if gw else None) or reason or est
        execution = {"status": est, "adapter": adapter,
                     "idempotency_key": (ex["idempotency_key"] if ex else f"exec:{pid}:{last['id'] if last else 0}:{adapter}"),
                     "executed_at": iso(ex["executed_at"]) if ex else None, "outcome": str(outcome), "hash_verified": bool(hv),
                     "approval_consumed": bool(last and last["consumed_at"]), "block_kind": block_kind if est == "blocked" else None,
                     "external_ref": ex["external_ref"] if ex else None,
                     "checks": map_checks(p["type"], recorded, status, executed, gw["data"].get("reason") if gw else None,
                                      parked=est == "parked" or (est == "blocked" and not block_kind and status != "superseded"))}
    ev = [evidence_item(c, e, p) for e in p["evidence"] or []]
    acct = c.execute("SELECT name FROM gtm.account WHERE id=%s", (p["account_id"],)).fetchone() if p["account_id"] else None
    return {"id": pid, "type": p["type"], "gate_id": p["gate_id"], "status": status, "account_id": p["account_id"],
            "account_name": acct["name"] if acct else None, "payload": payload, "payload_hash": phash, "evidence": ev,
            "rationale": p["rationale"], "confidence": float(p["confidence"]) if p["confidence"] is not None else None,
            "required_role": p["required_role"], "created_at": iso(p["created_at"]), "expires_at": iso(p["expires_at"]),
            "depends_on": dep, "block_reason": reason if status in ("blocked", "superseded", "parked", "failed") or block_kind else None,
            "decisions": decisions, "execution": execution,
            "data_origins": _origs(["MOD" if p["proposed_by"].startswith("agent:") else "SCR", *[e["data_origin"] for e in ev]])}


def list_proposals(c, status=None, account_id=None) -> list[dict]:
    rows = _q(c, "SELECT * FROM ops.proposal " + ("WHERE account_id=%s " if account_id else "") + "ORDER BY id DESC", *([account_id] if account_id else []))
    out = [proposal_out(c, r) for r in rows]
    return [o for o in out if not status or o["status"] == status]


# ------------------------------------------------------------------ leads, accounts
LEAD_STATUS = {"new": "new", "held": "held", "enriching": "triaged", "qualified": "qualified", "proposed": "qualified", "routed": "converted",
               "disqualified": "disqualified", "archived": "nurture"}
TRIAGE = {"real_lead", "existing_customer", "vendor", "recruiter", "spam", "unclear"}


def leads(c) -> list[dict]:
    out = []
    for r in _q(c, "SELECT l.*, ct.full_name, ct.email, a.name AS account_name FROM gtm.lead l LEFT JOIN gtm.contact ct ON ct.id=l.contact_id "
                   "LEFT JOIN gtm.account a ON a.id=l.account_id ORDER BY l.id DESC"):
        raw = r["raw_payload"] or {}
        tc = {"genuine": "real_lead"}.get(r["triage_class"], r["triage_class"])
        fs = float(r["fit_score"]) if r["fit_score"] is not None else None
        if fs is not None and fs > 1:
            fs /= 100.0
        out.append({"id": r["id"], "received_at": iso(r["created_at"]), "name": r["full_name"] or raw.get("full_name") or raw.get("name") or "",
                    "email": r["email"] or raw.get("email") or "", "company": r["account_name"] or raw.get("company_name") or raw.get("company"),
                    "message": str(raw.get("message") or raw.get("body") or raw.get("text") or ""),
                    "triage_class": (tc if tc in TRIAGE else "unclear") if tc else None,
                    "fit_score": fs,
                    "fit_band": r["fit_band"] if r["fit_band"] in ("high", "medium", "low") else None,
                    "status": LEAD_STATUS.get(r["status"], "new"), "held": r["status"] == "held", "held_reason": r["held_reason"],
                    "account_id": r["account_id"], "service_line": (r["fit_rationale"] or {}).get("service_line") if isinstance(r["fit_rationale"], dict) else None,
                    "data_origins": _origs(["SCR", "MOD" if tc else None])})
    return out


def _resolved_val(c, aid, field):
    r = c.execute("SELECT value FROM gtm.resolved_field WHERE entity_type='account' AND entity_id=%s AND field=%s", (aid, field)).fetchone()
    return r["value"] if r else None


def account_row(c, a: dict) -> dict:
    aid = a["id"]
    st = c.execute("SELECT lifecycle FROM gtm.account_agent_state WHERE account_id=%s", (aid,)).fetchone()
    emp = _resolved_val(c, aid, "employee_count")
    own = c.execute("SELECT display_name FROM ops.principal WHERE id=%s", (a["owner_principal"],)).fetchone() if a["owner_principal"] else None
    fit = c.execute("SELECT fit_band FROM gtm.lead WHERE account_id=%s AND fit_band IS NOT NULL ORDER BY id DESC LIMIT 1", (aid,)).fetchone()
    has_sim = c.execute("SELECT 1 FROM gtm.observation WHERE entity_type='account' AND entity_id=%s AND data_origin='SIM' LIMIT 1", (aid,)).fetchone()
    return {"id": aid, "name": a["name"], "domain": a["primary_domain"], "industry": _resolved_val(c, aid, "industry"),
            "employees": int(emp) if isinstance(emp, (int, float)) else None, "lifecycle": st["lifecycle"] if st else "unprovisioned",
            "owner": own["display_name"] if own else a["owner_principal"],
            "open_proposals": _scalar(c, "SELECT count(*) FROM ops.proposal WHERE account_id=%s AND status IN ('pending','blocked','parked')", aid),
            "last_interaction_at": iso(_scalar(c, "SELECT max(t) FROM (SELECT max(occurred_at) AS t FROM gtm.interaction WHERE account_id=%s "
                                                "UNION ALL SELECT max(created_at) FROM gtm.lead WHERE account_id=%s) x", aid, aid)),
            "fit_band": fit["fit_band"] if fit and fit["fit_band"] in ("high", "medium", "low") else None,
            "data_origins": _origs([a["data_origin"], "SIM" if has_sim else None, "MOD" if st else None])}


def accounts(c) -> list[dict]:
    return [account_row(c, a) for a in _q(c, "SELECT * FROM gtm.account WHERE merged_into_id IS NULL ORDER BY id DESC")]


LABELS = {"employee_count": ("employees", "Employees"), "revenue_band": ("revenue_band", "Revenue band"), "tech_stack": ("tech_stack", "Technology stack"),
          "hiring_signals": ("hiring_signals", "Hiring signals"), "hq_country": ("hq_country", "HQ country"), "parent_domain": ("parent_domain", "Parent domain")}


def _scalarise(v):
    return ", ".join(map(str, v)) if isinstance(v, list) else (v if isinstance(v, (str, int, float)) or v is None else json.dumps(v))


def _fresh(days: int) -> str:
    return "fresh" if days <= 30 else "aging" if days <= 120 else "stale"


def _src(name: str) -> str:
    return {"first_party": "first-party record", "human": "human entered"}.get(name, f"{name} (simulated)")


def account_fields(c, a: dict, now: datetime) -> list[dict]:
    out = []
    for field, r in get_resolved(c, "account", a["id"]).items():
        key, label = LABELS.get(field, (field, field.replace("_", " ").capitalize()))
        win = next((s for s in r["sources"] if s["winner"]), r["sources"][0] if r["sources"] else None)
        if win is None:
            continue
        asof = datetime.fromisoformat(win["observed_at"])
        days = max(0, (now - asof).days)
        alts = [{"source": _src(s["source"]), "value": _scalarise(s["value"]), "confidence": round(s["confidence"], 3), "as_of": iso(datetime.fromisoformat(s["observed_at"]))}
                for s in r["sources"] if not s["agrees"]]
        conflict = bool(r["conflict_flag"] and alts)
        o = c.execute("SELECT data_origin FROM gtm.observation WHERE id=%s", (win["observation_id"],)).fetchone()
        out.append({"key": key, "label": label, "value": _scalarise(r["value"]), "owner": "human" if win["source"] == "human" else "provider",
                    "source": _src(win["source"]), "confidence": round(r["confidence"], 3), "as_of": iso(asof), "freshness_days": days,
                    "freshness": _fresh(days), "conflict": conflict, "alternatives": alts if conflict else [],
                    "data_origin": o["data_origin"] if o and o["data_origin"] in ORIGINS else "SIM"})
    now_s = iso(now)
    out.append({"key": "owner", "label": "Account owner", "value": a["owner_principal"], "owner": "human", "source": "CRM (first-party)", "confidence": 1.0,
                "as_of": iso(a["updated_at"]) or now_s, "freshness_days": 0, "freshness": "fresh", "conflict": False, "alternatives": [], "data_origin": "SCR"})
    for k, label in (("ai_summary", "AI summary"), ("ai_risk_level", "AI risk level"), ("ai_next_action", "AI suggested next step")):
        if a[k] is not None:
            asof = a["ai_last_reviewed_at"] or a["updated_at"]
            out.append({"key": k, "label": label, "value": str(a[k]), "owner": "agent", "source": "account agent (mock model)", "confidence": 0.8,
                        "as_of": iso(asof), "freshness_days": max(0, (now - asof).days), "freshness": _fresh(max(0, (now - asof).days)),
                        "conflict": False, "alternatives": [], "data_origin": "MOD"})
    return out


def _l(x):
    return x if isinstance(x, list) else []


def _s(d, k, default=""):
    v = d.get(k) if isinstance(d, dict) else None
    return default if v is None else str(v)


def _int(v, default):
    import re
    m = re.search(r"\d+", str(v)) if v is not None and not isinstance(v, bool) else None
    return int(m.group()) if m else default


def _text(x) -> str:
    return str(x.get("text", "")) if isinstance(x, dict) else str(x)


def agent_state(c, aid: int, mode: str) -> dict | None:
    r = c.execute("SELECT * FROM gtm.account_agent_state WHERE account_id=%s", (aid,)).fetchone()
    if not r:
        return None
    pick = lambda v, ok, d: v if v in ok else d
    nxt = []
    for i, n in enumerate(_l(r["next_actions"])):
        n = n if isinstance(n, dict) else {"text": str(n)}
        nxt.append({"id": _int(n.get("id"), i + 1), "action": _s(n, "action", "no_action"), "text": _s(n, "text") or _s(n, "action"),
                    "status": pick(n.get("status"), ("proposed", "pending_approval", "done", "dismissed"), "proposed"),
                    "proposal_id": _int(n.get("proposal_id"), None), "rationale": n.get("rationale")})
    hyps = [h for h in _l(r["hypotheses"]) if isinstance(h, dict)]
    ld = hyps[-1] if hyps and "would_change_mind" in hyps[-1] else None
    refs = [str(x) for h in hyps for x in _l(h.get("evidence_refs"))]
    return {"lifecycle": r["lifecycle"], "version": r["version"], "updated_at": iso(r["last_woken_at"]) or iso(c.execute("SELECT now() AS n").fetchone()["n"]),
            "mode": mode, "summary": r["summary"] or "", "summary_refs": list(dict.fromkeys(refs)),
            "stakeholders": [{"name": _s(s, "name"), "role": _s(s, "role"), "stance": pick(s.get("stance"), ("champion", "neutral", "unknown", "blocker"), "unknown"),
                              "source_ref": _s(s, "source_ref")} for s in _l(r["stakeholder_map"]) if isinstance(s, dict)],
            "risks": [{"text": _s(x, "text"), "severity": pick(x.get("severity"), ("low", "medium", "high"), "medium"), "refs": [str(y) for y in _l(x.get("refs"))]}
                      for x in _l(r["risks"]) if isinstance(x, dict)],
            "commitments": [{"party": _s(x, "party"), "text": _s(x, "text"), "due": x.get("due"), "status": pick(x.get("status"), ("open", "proposed", "done"), "open"),
                             "refs": [str(y) for y in _l(x.get("refs"))]} for x in _l(r["commitments"]) if isinstance(x, dict)],
            "open_questions": [_text(q) for q in _l(r["open_questions"])], "next_actions": nxt,
            "last_decision": {"action": (nxt[-1]["action"] if nxt else _s(ld, "text")), "confidence": float(ld.get("confidence") or 0.0),
                              "would_change_mind": _s(ld, "would_change_mind")} if ld else None}


def interactions(c, aid: int) -> list[dict]:
    out = []
    for r in _q(c, "SELECT * FROM gtm.interaction WHERE account_id=%s ORDER BY occurred_at DESC, id DESC", aid):
        k = ("human" if r["classification"] == "human_touch" else "enquiry" if r["channel"] in ("form", "web_form") else
             "email_out" if r["direction"] == "outbound" else "email_in" if r["direction"] == "inbound" and r["channel"] == "email" else
             "crm" if r["channel"] == "crm" else "agent" if r["channel"] == "agent" else "system")
        out.append({"id": r["id"], "at": iso(r["occurred_at"]), "kind": k, "summary": r["subject"] or r["classification"] or r["channel"],
                    "detail": r["body"], "ref": f"interaction:{r['id']}", "data_origin": r["data_origin"] if r["data_origin"] in ORIGINS else "SCR"})
    return out


def opportunities(c, aid=None) -> list[dict]:
    out = []
    for r in _q(c, "SELECT o.*, a.name AS account_name, p.display_name AS owner_name FROM gtm.opportunity o JOIN gtm.account a ON a.id=o.account_id "
                   "LEFT JOIN ops.principal p ON p.id=o.owner_principal " + ("WHERE o.account_id=%s " if aid else "") + "ORDER BY o.id DESC", *([aid] if aid else [])):
        st = (r["stage"] or "").lower()
        out.append({"id": r["id"], "account_id": r["account_id"], "account_name": r["account_name"], "name": r["name"], "stage": r["stage"],
                    "amount": float(r["amount"]) if r["amount"] is not None else None, "currency": "EUR", "owner": r["owner_name"] or r["owner_principal"],
                    "days_in_stage": int(r["days_in_stage"] or 0), "status": "lost" if "lost" in st else "won" if "won" in st else "open", "data_origin": "SIM"})
    return out


def alerts(c) -> list[dict]:
    out = []
    for r in _q(c, "SELECT o.*, a.name AS account_name FROM gtm.opportunity o JOIN gtm.account a ON a.id=o.account_id WHERE o.is_stalled ORDER BY o.updated_at DESC, o.id DESC"):
        why = (r["stall_reason"] or "Stalled").strip()
        days = int(r["days_in_stage"] or 0)
        low = why.lower()
        kind = "no_reply" if "reply" in low else "no_next_step" if "next step" in low else "champion_change" if "champion" in low else "stalled"
        out.append({"id": r["id"], "opportunity_id": r["id"], "opportunity_name": r["name"], "account_id": r["account_id"], "account_name": r["account_name"],
                    "severity": "high" if days >= 45 else "medium" if days >= 30 else "low", "kind": kind, "days_stalled": days, "reasons": [why],
                    "recommendation": f"Review {r['name']} with the owner and agree a concrete next step.", "raised_at": iso(r["updated_at"]), "data_origin": "SIM"})
    return out


# ------------------------------------------------------------------ runs
RUN_STATUS = {"running": "running", "waiting": "waiting", "completed": "succeeded", "failed": "failed", "needs_attention": "dead_letter",
              "budget_exceeded": "failed", "cancelled": "failed"}
NODE_TYPES = {"trigger", "code", "tool", "llm", "agent", "conditional", "map", "reduce", "wait", "approval"}


def _steps(c, run: dict, mode: str) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for s in _q(c, "SELECT * FROM ops.run_step WHERE run_id=%s ORDER BY id", run["id"]):
        groups.setdefault((s["node_id"], s["item_key"]), []).append(s)
    out = []
    for seq, ((node, item), rows) in enumerate(groups.items(), 1):
        last = rows[-1]
        errs = [r for r in rows if r["error"] or r["error_class"]]
        ntype = last["node_type"] if last["node_type"] in NODE_TYPES else "code"
        st = {"succeeded": "succeeded", "failed": "failed", "running": "running", "retrying": "running", "parked": "parked", "skipped": "skipped"}[last["status"]]
        parked = c.execute("SELECT available_at FROM ops.job WHERE run_id=%s AND status='queued' ORDER BY id DESC LIMIT 1", (run["id"],)).fetchone()
        if st == "parked" and ntype in ("wait", "approval"):
            st = "waiting"
        if st == "failed" and run["status"] == "needs_attention":
            st = "dead_letter"
        outp = last["output"] if isinstance(last["output"], dict) else {}
        pid = outp.get("proposal_id") or (last["input"] or {}).get("proposal_id") if isinstance(last["input"], dict) or outp else None
        out.append({"id": last["id"], "seq": seq, "node": node + (f"[{item}]" if item else ""), "node_type": ntype, "status": st,
                    "attempts": max(r["attempt"] for r in rows), "started_at": iso(rows[0]["started_at"]), "finished_at": iso(last["ended_at"]),
                    "error": {"class": errs[-1]["error_class"] or "Error", "message": errs[-1]["error"] or ""} if errs else None,
                    "parked_until": iso(parked["available_at"]) if st in ("parked", "waiting") and parked else None,
                    "waiting_for": f"approval:{pid}" if st == "waiting" and pid else None, "cost_usd": float(sum(r["cost"] for r in rows)),
                    "sim_units": float(outp.get("cost_units", 0) or 0) if ntype == "tool" else 0.0, "model_mode": mode if ntype in ("llm", "agent") else None,
                    "note": outp.get("note") if isinstance(outp.get("note"), str) else None})
    return out


def run_row(c, r: dict, steps: list[dict] | None = None) -> dict:
    ev = c.execute("SELECT type FROM ops.domain_event WHERE id=%s", (r["trigger_event_id"],)).fetchone() if r["trigger_event_id"] else None
    a = c.execute("SELECT name FROM gtm.account WHERE id=%s", (r["account_id"],)).fetchone() if r["account_id"] else None
    n = c.execute("SELECT count(DISTINCT (node_id, coalesce(item_key,''))) AS n FROM ops.run_step WHERE run_id=%s", (r["id"],)).fetchone()["n"]
    d = c.execute("SELECT count(*) AS n FROM (SELECT DISTINCT ON (node_id, coalesce(item_key,'')) status FROM ops.run_step WHERE run_id=%s "
                  "ORDER BY node_id, coalesce(item_key,''), id DESC) x WHERE status IN ('succeeded','skipped')", (r["id"],)).fetchone()["n"]
    status = RUN_STATUS.get(r["status"], "running")
    if status == "waiting" and c.execute("SELECT 1 FROM ops.run_step WHERE run_id=%s AND status='parked' ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone() \
            and not c.execute("SELECT 1 FROM ops.run_step WHERE run_id=%s AND node_type IN ('wait','approval') LIMIT 1", (r["id"],)).fetchone():
        status = "parked"
    row = {"id": r["id"], "workflow": r["workflow"], "status": status, "trigger": f"event:{ev['type']}" if ev else "schedule",
           "account_id": r["account_id"], "account_name": a["name"] if a else None, "started_at": iso(r["started_at"]), "finished_at": iso(r["ended_at"]),
           "steps_total": n, "steps_done": d, "cost_usd": float(r["cost"] or 0)}
    if steps is not None:
        row["steps"] = steps
    return row


# ------------------------------------------------------------------ overview, audit, events
def overview(c, now: datetime) -> dict:
    cnt = lambda sql, *a: int(_scalar(c, sql, *a))
    lead = c.execute("SELECT * FROM gtm.lead ORDER BY id LIMIT 1").fetchone()
    aid = lead["account_id"] if lead else None
    ex = lambda adapter: c.execute("SELECT external_ref FROM ops.execution WHERE adapter=%s AND status='succeeded' ORDER BY id LIMIT 1", (adapter,)).fetchone()
    ast = c.execute("SELECT version FROM gtm.account_agent_state WHERE account_id=%s", (aid,)).fetchone() if aid else None
    acc = c.execute("SELECT name FROM gtm.account WHERE id=%s", (aid,)).fetchone() if aid else None
    crm, send = ex("crm.write"), ex("outreach.send")
    reply = c.execute("SELECT id, occurred_at FROM gtm.interaction WHERE direction='inbound' AND channel='email' AND (account_id=%s OR %s::bigint IS NULL) "
                      "ORDER BY id LIMIT 1", (aid, aid)).fetchone()
    intel = reply and c.execute("SELECT id FROM ops.proposal WHERE created_at >= %s AND (account_id=%s OR %s::bigint IS NULL) ORDER BY id LIMIT 1", (reply["occurred_at"], aid, aid)).fetchone()

    def step(key, label, ok, detail):
        return {"key": key, "label": label, "done": bool(ok), "detail": detail if ok else None}
    gt = [step("enquiry", "Enquiry received", lead, lead and f"Lead #{lead['id']}"),
          step("triage", "Triaged and scored", lead and lead["triage_class"], lead and f"{lead['triage_class']} / fit {lead['fit_band']}"),
          step("account", "Account resolved", aid, acc and f"Account #{aid} {acc['name']}"),
          step("agent", "Account agent provisioned", ast, ast and f"Account agent v{ast['version']}"),
          step("crm", "CRM record created (approved)", crm, crm and f"CRM id {crm['external_ref']}"),
          step("send", "Intro reply sent (approved)", send, send and f"Message {send['external_ref']}"),
          step("reply", "Prospect reply received", reply, reply and f"Interaction #{reply['id']}"),
          step("intel", "Next action proposed", intel, intel and "Follow-up proposed from the reply")]
    act = [{"at": iso(r["at"]), "text": f"{r['event_type']} ({r['actor_id']})", "ref": r["entity_ref"]}
           for r in _q(c, "SELECT * FROM ops.audit_event ORDER BY seq DESC LIMIT 10")]
    return {"clock": iso(now), "counts": {"leads": cnt("SELECT count(*) FROM gtm.lead"), "accounts": cnt("SELECT count(*) FROM gtm.account WHERE merged_into_id IS NULL"),
            "open_proposals": cnt("SELECT count(*) FROM ops.proposal WHERE status IN ('pending','blocked','parked')"), "runs": cnt("SELECT count(*) FROM ops.agent_run"),
            "alerts": cnt("SELECT count(*) FROM gtm.opportunity WHERE is_stalled"), "audit_events": cnt("SELECT count(*) FROM ops.audit_event")},
            "golden_thread": gt, "recent_activity": act}


def audit_rows(c, limit: int) -> list[dict]:
    return [{"seq": r["seq"], "at": iso(r["at"]), "actor_type": r["actor_type"], "actor_id": r["actor_id"], "event_type": r["event_type"],
             "entity_ref": r["entity_ref"], "proposal_id": r["proposal_id"], "run_id": r["run_id"], "data": r["data"], "hash": r["hash"], "prev_hash": r["prev_hash"]}
            for r in _q(c, "SELECT * FROM ops.audit_event ORDER BY seq DESC LIMIT %s", limit)]


def events(c, limit: int) -> list[dict]:
    return [{"id": r["id"], "at": iso(r["occurred_at"]), "event_type": r["type"], "entity_ref": r["entity_ref"], "source": r["source"], "dedupe_key": r["dedupe_key"]}
            for r in _q(c, "SELECT * FROM ops.domain_event ORDER BY id DESC LIMIT %s", limit)]


# ------------------------------------------------------------------ feedback
def feedback(c) -> list[dict]:
    out = []
    for r in _q(c, "SELECT r.*, o.account_id, a.name AS account_name FROM gtm.lost_deal_review r JOIN gtm.opportunity o ON o.id=r.opportunity_id "
                   "JOIN gtm.account a ON a.id=o.account_id ORDER BY r.id DESC"):
        sec = r["secondary_reasons"] or []
        code = next((s[7:] for s in sec if s.startswith("reason:")), None)
        ai = r["ai_suggested_tags"] or []
        quotes = [{"text": q["quote"], "speaker": q["speaker_role"], "source_ref": f"lost_deal_review:{r['id']}"}
                  for q in _q(c, "SELECT * FROM gtm.feedback_item WHERE lost_deal_review_id=%s ORDER BY id", r["id"])]
        out.append({"id": r["id"], "kind": "lost_deal_review", "created_at": iso(r["created_at"]), "account_id": r["account_id"], "account_name": r["account_name"],
                    "summary": r["primary_reason"], "quotes": quotes, "tags_human": [s for s in sec if not s.startswith("reason:")] + ([r["competitor"]] if r["competitor"] else []),
                    "tags_ai_suggested": [str(t.get("label", t) if isinstance(t, dict) else t) for t in ai if t], "reason_code": code,
                    "created_by": r["captured_by"], "data_origin": "SCR"})
    for r in _q(c, "SELECT f.*, a.name AS account_name FROM gtm.feedback_item f LEFT JOIN gtm.account a ON a.id=f.account_id WHERE f.lost_deal_review_id IS NULL ORDER BY f.id DESC"):
        out.append({"id": r["id"] + 1_000_000, "kind": "customer_reply", "created_at": iso(r["created_at"]), "account_id": r["account_id"], "account_name": r["account_name"],
                    "summary": r["label"] or r["topic"] or r["kind"], "quotes": [{"text": r["quote"], "speaker": r["speaker_role"], "source_ref": f"interaction:{r['interaction_id']}" if r["interaction_id"] else None}],
                    "tags_human": [r["label"]] if r["label"] and r["review_status"] in ("confirmed", "edited") else [],
                    "tags_ai_suggested": [r["label"]] if r["label"] and r["review_status"] == "suggested" else [], "reason_code": None,
                    "created_by": "agent:account-agent", "data_origin": "MOD"})
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out
