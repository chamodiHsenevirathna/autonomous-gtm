"""Deterministic, rule-based stand-in for the model (SIMULATED: mode='mock', model_id 'mock-heuristic-v1').
Every output is explainable from the input. Nothing here measures real model quality.
Untrusted text (input['untrusted']) is only ever searched for keywords; instructions inside it are never followed,
and injection-looking sentences are removed before any classification."""
from __future__ import annotations
import re
from gtm.llm import register_mock

INJECTION = re.compile(r"(ignore (?:all |your |any )?(?:previous|prior) instructions|\bsystem\s*(?:notice|:)|to ai assistants|approve (?:any |the )?pending|"
                       r"reveal|full (?:customer )?list|internal notes|as an ai|disregard)", re.I)
VENDOR = ("we provide", "offshore", "book a demo", "our platform", "lead generation", "seo", "lower cost", "white-label", "our services")
RECRUITER = ("pool of", "candidates", "placement", "recruit", "available now", "headhunt", "talent")
SPAM = ("congratulations", "claim", "click the link", "reward", "selected to receive", "prize", "winner", "crypto")
LOW_FIT = ("student", "dissertation", "free resources", "cheap", "day rate", "sample project", "one-off")
SERVICE_LINES = ("data engineering", "cloud engineering", "application modernisation", "ai and agent development", "technology consulting")
INTENT_WORDS = ("this quarter", "decision", "pilot", "within two months", "legacy platform", "evaluating partners", "reviewing providers")
ICP = {"min_employees": 50, "regions": ("EMEA", "NA", "APAC")}      # hard constraints, applied in code by the qualify step too
SENIORITY_POINTS = {"c_level": 20, "vp": 20, "director": 15, "manager": 10, "ic": 5}


def strip_injection(text: str) -> tuple[str, bool]:
    """Remove sentences that look like instructions to the model. Returns (clean_text, injection_suspected)."""
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    keep = [p for p in parts if not INJECTION.search(p)]
    return " ".join(keep), len(keep) != len(parts)


def _hits(text: str, words) -> int:
    t = text.lower()
    return sum(1 for w in words if re.search(r"(?<![a-z])" + re.escape(w), t))


def triage(inp: dict) -> dict:
    u = inp.get("untrusted", {})
    text, inj = strip_injection(f"{u.get('subject', '')}. {u.get('message', '')}")
    v, r, s = _hits(text, VENDOR), _hits(text, RECRUITER), _hits(text, SPAM)
    best = max((("vendor", v), ("recruiter", r), ("spam", s)), key=lambda x: x[1])
    if best[1] > 0:
        label, conf = best[0], min(0.95, 0.7 + 0.1 * best[1])
        reason = f"{best[1]} {label} keyword(s) matched"
    elif len(text.split()) < 6:
        label, conf, reason = "unclear", 0.4, "too little text to classify"
    else:
        label, conf, reason = "genuine", 0.8, "no vendor/recruiter/spam markers"
    if inj:
        reason += "; instruction-like text removed and ignored (injection suspected)"
        if label == "genuine":
            label, conf = "unclear", 0.5
    return {"label": label, "confidence": round(conf, 2), "reason": reason, "injection_suspected": inj}


def _val(res: dict, f: str):
    v = res.get(f)
    return v.get("value") if isinstance(v, dict) else v


def qualify(inp: dict) -> dict:
    res, ct = inp.get("resolved", {}), inp.get("contact", {})
    u = inp.get("untrusted", {})
    text, _ = strip_injection(f"{u.get('message', '')} {u.get('service_interest') or ''}")
    low = text.lower()
    crit, unknowns, score = [], [], 0

    def add(name, met, pts, ref=None, note=None):
        nonlocal score
        crit.append({"name": name, "met": met, "evidence_ref": ref, "note": note})
        if met:
            score += pts

    emp = _val(res, "employee_count")
    if emp is None:
        unknowns.append("employee_count"); add("company_size", None, 0, None, "unknown")
    else:
        emp = int(emp)
        pts = 30 if 200 <= emp <= 5000 else 25 if emp > 5000 else 15 if emp >= ICP["min_employees"] else 0
        add("company_size", pts > 0, pts, "resolved:employee_count", f"{emp} employees")
    reg = _val(res, "region")
    if reg is None:
        unknowns.append("region"); add("region_served", None, 0, None, "unknown")
    else:
        add("region_served", reg in ICP["regions"], 15 if reg in ("EMEA", "NA") else 10, "resolved:region", str(reg))
    line = next((s for s in SERVICE_LINES if s in low), None)
    add("service_need_match", line is not None, 25, "enquiry:message", line or "no service line named")
    hiring = _val(res, "hiring_signals")
    add("hiring_signal", bool(hiring), 10, "resolved:hiring_signals", str(hiring) if hiring else "none known")
    sen = ct.get("seniority") or _val(res, "seniority")
    if sen is None:
        unknowns.append("seniority"); add("seniority", None, 0, None, "unknown")
    else:
        add("seniority", sen in SENIORITY_POINTS, SENIORITY_POINTS.get(sen, 0), "resolved:seniority", str(sen))
    add("buying_intent", _hits(low, INTENT_WORDS) > 0, 10, "enquiry:message", "intent wording" if _hits(low, INTENT_WORDS) else "none")
    pen = _hits(low, LOW_FIT) > 0
    if pen:
        score -= 30; crit.append({"name": "low_fit_wording", "met": False, "evidence_ref": "enquiry:message", "note": "student/cheap/one-off wording"})
    score = max(0, min(100, score))
    band = "high" if score >= 70 else "medium" if score >= 45 else "low" if score >= 15 else "none"
    nxt = {"high": "route to owner and reply within one business day", "medium": "owner reviews; reply with discovery question",
           "low": "nurture; no outreach proposed", "none": "archive with reason"}[band]
    return {"score": score, "band": band, "criteria": crit, "service_line": line, "owner_hint": "user:maya" if band in ("high", "medium") else None,
            "next_action": nxt, "unknowns": unknowns,
            "rationale": f"score {score} from {sum(1 for c in crit if c['met'])} met criteria; {len(unknowns)} unknown field(s). (simulated heuristic)"}


def research_brief(inp: dict) -> dict:
    claims, flags = [], []
    for pg in inp.get("untrusted", {}).get("pages", []):
        clean, inj = strip_injection(pg.get("text", ""))
        if inj:
            flags.append(pg["url"])
        for s in re.split(r"(?<=[.!?])\s+", clean):
            if len(s.split()) >= 4 and len(claims) < 8:
                claims.append({"text": s.strip(), "source_ref": pg["url"]})   # claims come ONLY from provided page text
    return {"claims": claims, "unknowns": [] if claims else ["no usable sources"], "injection_flags": flags}


def reply_intent(inp: dict) -> dict:
    u = inp.get("untrusted", {})
    text, _ = strip_injection(f"{u.get('subject', '')} {u.get('body', '')}")
    t = text.lower()
    table = [("not_interested", ("not interested", "no thanks", "no longer")), ("not_now", ("budget freeze", "not now", "come back", "next quarter")),
             ("referral", ("speak to", "talk to my colleague", "reach out to", "better person")),
             ("interested", ("let's talk", "lets talk", "timely", "interested", "happy to", "yes")), ("question", ("?", "how", "what", "could you"))]
    for intent, kws in table:
        if any(k in t for k in kws):
            return {"intent": intent, "confidence": 0.75, "rationale": f"matched '{intent}' wording (simulated heuristic)"}
    return {"intent": "unclear", "confidence": 0.3, "rationale": "no marker matched"}


def draft_message(inp: dict) -> dict:
    c, co, purpose = inp.get("contact", {}), inp.get("company", "your company"), inp.get("purpose", "inbound_response")
    first = (c.get("name") or "there").split()[0]
    src = inp.get("source_ref") or "enquiry"
    line = inp.get("service_interest")
    if purpose == "followup":
        body = (f"Hello {first}, thank you for your reply. It would be good to talk through the next step together. "
                f"Would a short call this week or next suit you? Happy to work around your calendar.")
        claims = [{"text": "You replied to our earlier note", "source_ref": src}]
        subject = "Re: your enquiry"
    else:
        topic = f" about {line}" if line else ""
        body = (f"Hello {first}, thank you for getting in touch{topic}. We would like to understand what you are trying to achieve at {co}. "
                f"Could we find a short call to talk it through?")
        claims = [{"text": f"You enquired{topic}", "source_ref": src}]
        subject = "Re: your enquiry"
    return {"subject": subject, "body": body, "claims": claims}


def account_decide(inp: dict) -> dict:
    ev, acct, ct = inp.get("event", {}), inp.get("account", {}), inp.get("contact", {})
    name, cname = acct.get("name", "the account"), ct.get("name", "the contact")
    evid = [f"event:{ev.get('type')}"] + ([f"interaction:{ev['interaction_id']}"] if ev.get("interaction_id") else [])
    acts, risks, conf, change = [], [], 0.7, "a reply, a stage change or a stall flag"

    def act(t, params=None, why="", refs=None):
        acts.append({"type": t, "params": params or {}, "rationale": why, "evidence_refs": refs or evid})
    etype, intent = ev.get("type"), ev.get("intent")
    if intent in ("unsubscribe", "bounce"):
        act("no_action", why=f"{intent}: contact suppressed by the router; nothing to send")
        act("flag_risk", {"risk": f"{intent} from {cname}", "evidence": evid}, "owner should know the contact is suppressed")
        risks.append(f"{intent}: outreach to this contact is blocked")
        summary = f"{cname} sent a {intent}. No outreach; owner notified."
    elif etype == "lead.qualified" and not acct.get("has_crm_ids"):
        act("propose_crm_create", {}, "qualified inbound lead with no CRM record: create company, contact and deal after approval")
        act("draft_message", {"purpose": "inbound_response"}, "reply to the enquiry (draft only)")
        act("recommend_task", {"title": f"Review new qualified lead: {name}", "detail": "Qualified inbound; CRM create and reply drafted for approval.", "owner": acct.get("owner") or "user:maya"},
            "owner follow-up")
        act("update_agent_fields", {"ai_summary": f"New qualified inbound lead from {cname} at {name}.", "ai_risk_level": "low",
                                    "ai_next_action": "Create CRM records and reply to the enquiry (awaiting approval)."}, "record the agent's view")
        summary = f"New qualified lead {cname} ({name}); proposed CRM create and an intro reply."
        conf = 0.8
    elif intent == "interested":
        act("draft_message", {"purpose": "followup"}, "contact replied with interest: draft a follow-up offering to arrange a call")
        act("recommend_task", {"title": f"Interested reply from {cname}", "detail": "Review and approve the drafted follow-up.", "owner": acct.get("owner") or "user:maya"}, "owner follow-up")
        act("update_agent_fields", {"ai_summary": f"{cname} replied with interest.", "ai_risk_level": "low", "ai_next_action": "Arrange a discovery call."}, "state")
        summary = f"{cname} is interested; follow-up drafted."
        conf = 0.8
    elif etype == "meeting.booked" or intent == "meeting_booked":
        act("recommend_task", {"title": f"Prepare for meeting with {cname}", "detail": "Discovery call booked by the contact.", "owner": acct.get("owner") or "user:maya"}, "prepare")
        act("update_agent_fields", {"ai_summary": f"Meeting booked with {cname}.", "ai_risk_level": "low", "ai_next_action": "Prepare discovery call."}, "state")
        summary = "Meeting booked; preparation task proposed."
    elif intent in ("not_now", "not_interested"):
        act("update_agent_fields", {"ai_summary": f"{cname} replied: {intent}.", "ai_risk_level": "medium", "ai_next_action": "Revisit later; no outreach now."}, "state")
        act("recommend_task", {"title": f"Revisit {name} later ({intent})", "detail": "Contact asked not to be pursued now.", "owner": acct.get("owner") or "user:maya"}, "revisit")
        summary = f"{cname}: {intent}. No outreach."
    elif etype == "deal.flagged" or inp.get("stalled"):
        act("recommend_human_touch", {"reason": "deal flagged as stalled"}, "stall flag from the pipeline monitor (not recomputed here)")
        act("recommend_task", {"title": f"Re-engage stalled deal: {name}", "detail": "Pipeline monitor flagged this deal as stalled.", "owner": acct.get("owner") or "user:maya"}, "owner follow-up")
        risks.append("deal stalled")
        summary = "Deal flagged as stalled; human touch recommended."
    elif intent in ("question", "referral", "unclear") and ev.get("type") == "reply.received":
        act("recommend_task", {"title": f"Review reply from {cname} ({intent})", "detail": "Reply needs a human read.", "owner": acct.get("owner") or "user:maya"}, "human read")
        summary = f"Reply ({intent}) needs a human."
    elif not inp.get("material_change", True):
        act("no_action", why="nothing material changed since last review")
        summary, conf = "No material change.", 0.9
    else:
        act("no_action", why="no rule calls for an action")
        summary, conf = "Reviewed; nothing to do.", 0.6
    return {"actions": acts, "summary": summary, "risks": risks, "confidence": conf, "what_would_change": change}


_TASKS = {"triage": triage, "qualify": qualify, "research_brief": research_brief, "account_decide": account_decide,
          "draft_message": draft_message, "reply_intent": reply_intent}


def register_all() -> None:
    for t, fn in _TASKS.items():
        register_mock(t, fn)
